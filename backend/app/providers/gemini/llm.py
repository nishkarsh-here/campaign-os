"""Gemini text and multimodal reasoning.

Uses the Interactions API — `client.aio.interactions.create(...)` — which is
the shape the current Gemini API documentation and the installed `google-genai`
SDK both describe, and the same surface the image adapter already talks to.
Structured output is requested with a `response_format` of type `text` whose
`mime_type` is `application/json` and whose `schema` is the Pydantic model's
own JSON Schema; the reply comes back on `interaction.output_text`.

**Structure is handled once, here** (ADR-009). `structured()` returns a
validated instance of the caller's model or raises — a node never sees a
string, never sees a `dict`, and never parses JSON itself. When the first
reply does not validate, one repair pass asks the model again with the
validation errors attached. That is a second constrained model call whose
result is validated exactly as strictly; nothing is coerced, defaulted or
hand-patched here, because a quietly repaired object is a schema violation
that reaches the database instead of the log.

**Credentials are server-side only.** The key is read from `Settings`, which
reads it from the environment. It never appears in a response, a log line, an
error message or anything that reaches the browser.

**No vendor exception escapes.** Everything becomes a `ProviderError` subclass
carrying a message safe to show a user, with the vendor's own words kept in
`detail` for the log.

This adapter is never exercised automatically: the test suite runs on
`LLM_PROVIDER=mock`, and reaching Gemini requires deliberately configuring it.
Its behaviour is covered by tests that drive a fake SDK client through this
same class, so every branch is verified without spending a credit.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.logging import get_logger
from app.providers.base import (
    ImageRef,
    ProviderError,
    ProviderInvalidResponse,
    ProviderTimeout,
    ProviderUnavailable,
    TModel,
)
from app.providers.gemini.errors import translate

log = get_logger(__name__)

#: The noun the user sees in a translated error. Classification is shared with
#: the other Gemini adapters (`errors.py`); only the wording is local.
_SUBJECT = "The model service"

#: How much of an unusable reply is worth keeping for the log. Enough to see
#: what shape came back, short enough not to paste a whole document into a log
#: line. It passes through `ProviderError`'s redaction like every other detail.
_EXCERPT = 300


class GeminiLLMProvider:
    """Text and multimodal reasoning through the Gemini API."""

    name = "gemini"

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._model = settings.gemini_llm_model
        self._timeout = settings.llm_timeout_s
        # Injected in tests. Built lazily otherwise so importing this module
        # never requires a key — the registry imports adapters lazily too, but
        # a constructor that reached for credentials would still break
        # `--collect-only` on a machine with none.
        self._client = client
        self._api_key = settings.gemini_api_key

    def _ensure_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ProviderUnavailable(
                    "Gemini reasoning is not configured.",
                    detail="GEMINI_API_KEY is unset",
                    provider=self.name,
                )
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        images: tuple[ImageRef, ...] = (),
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Free-form text. Used only where structure genuinely does not apply."""
        return await self._interact(
            prompt,
            system=system,
            images=images,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def structured(
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str | None = None,
        images: tuple[ImageRef, ...] = (),
        temperature: float = 0.4,
    ) -> TModel:
        """Return a validated instance of `schema`, or raise."""
        response_format = {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema.model_json_schema(),
        }
        text = await self._interact(
            prompt,
            system=system,
            images=images,
            temperature=temperature,
            response_format=response_format,
        )
        try:
            return schema.model_validate_json(text)
        except ValidationError as first:
            log.warning(
                "gemini_structured_invalid",
                schema=schema.__name__,
                errors=first.error_count(),
                repairing=True,
            )

        # One repair pass, still schema-constrained and still validated. The
        # model is shown its own reply and what was wrong with it; decoding is
        # made as deterministic as the API allows, because a repair that
        # wanders is not a repair.
        repaired = await self._interact(
            _repair_prompt(prompt, text, schema.__name__),
            system=system,
            images=images,
            temperature=0.0,
            response_format=response_format,
        )
        try:
            return schema.model_validate_json(repaired)
        except ValidationError as second:
            raise ProviderInvalidResponse(
                "The model returned a response we could not use.",
                detail=(
                    f"{schema.__name__} still invalid after one repair pass: "
                    f"{second.error_count()} error(s); reply began {repaired[:_EXCERPT]!r}"
                ),
                provider=self.name,
            ) from second

    async def health(self) -> bool:
        """Cheap reachability: is this adapter configured at all?

        Deliberately not a live call — a health probe that ran a completion
        would charge for every check.
        """
        return bool(self._api_key or self._client)

    # ------------------------------------------------------------------ call
    async def _interact(
        self,
        prompt: str,
        *,
        system: str | None,
        images: tuple[ImageRef, ...],
        temperature: float,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """One Interactions call, with every failure already typed."""
        client = self._ensure_client()

        generation_config: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            generation_config["max_output_tokens"] = max_tokens

        body: dict[str, Any] = {
            "model": self._model,
            "input": _input(prompt, images),
            "generation_config": generation_config,
        }
        if system:
            body["system_instruction"] = system
        if response_format is not None:
            body["response_format"] = response_format

        try:
            interaction = await asyncio.wait_for(
                client.aio.interactions.create(**body), timeout=self._timeout
            )
        except TimeoutError as exc:
            raise ProviderTimeout(
                "The model did not respond in time.",
                detail=f"exceeded {self._timeout}s",
                provider=self.name,
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — the vendor's error tree stops here
            raise translate(exc, provider=self.name, subject=_SUBJECT) from exc

        text = getattr(interaction, "output_text", None)
        if not text or not str(text).strip():
            # A reply with no text is a failure even when the call "succeeded":
            # every caller here is asking a question and expects an answer.
            raise ProviderInvalidResponse(
                "The model returned an empty response.",
                detail=f"status={getattr(interaction, 'status', 'unknown')}",
                provider=self.name,
            )
        return str(text)


def _input(prompt: str, images: tuple[ImageRef, ...]) -> str | list[dict[str, Any]]:
    """The interaction input: a bare string, or content blocks when there are
    images. Images come first so the instruction is the last thing read."""
    if not images:
        return prompt
    blocks: list[dict[str, Any]] = [_image_block(image) for image in images]
    blocks.append({"type": "text", "text": prompt})
    return blocks


def _image_block(image: ImageRef) -> dict[str, Any]:
    if image.data is None:
        # The provider layer has no storage — resolving a key is the calling
        # service's job, and every call site in this application already does
        # it. Failing loudly beats sending a request with a missing image.
        raise ProviderError(
            "An image was passed to the model by storage key rather than bytes.",
            detail=f"storage_key={bool(image.storage_key)}",
            provider="gemini",
        )
    return {
        "type": "image",
        "data": base64.b64encode(image.data).decode("ascii"),
        "mime_type": image.mime_type,
    }


def _repair_prompt(prompt: str, reply: str, schema_name: str) -> str:
    """Ask again, showing the model what it sent and what was wrong with it.

    The schema itself is not restated: `response_format` already carries it,
    and a second copy in prose is one more thing that can drift out of step
    with the model the caller actually asked for.
    """
    return (
        f"Your previous reply did not validate against the required "
        f"{schema_name} schema.\n\n"
        f"--- your previous reply ---\n{reply[:4000]}\n--- end ---\n\n"
        "Return the same information again as a single JSON object that "
        "satisfies the schema exactly. Do not add fields the schema does not "
        "define, and do not invent facts that were not in your previous reply "
        "or in the original request.\n\n"
        f"--- original request ---\n{prompt}"
    )
