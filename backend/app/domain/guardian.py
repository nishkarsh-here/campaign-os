"""The Brand Guardian.

A different question from the Creative Evaluator's, and therefore a different
module:

  Evaluator      "How good is this creative?"          -> scores, ranking
  Brand Guardian "Is this acceptable for this brand?"  -> PASS / NEEDS_REVISION

Conflating them is the classic mistake. A beautiful creative that implies a
prohibited claim must fail; a merely adequate one that is perfectly on-brand
must pass. Ranking uses the score; the guardian holds a veto. They lived in one
file while both were sketches — Milestone 8 separates them, because the
boundary is the point.

**Checks are observations; the verdict is computed.** The model reports what it
sees, check by check. `decide_verdict` turns those observations plus the
deterministic checks into PASS, NEEDS_REVISION or REJECT using published rules,
so a verdict can always be argued with from its own findings.

**A failed check is never an implicit pass.** When the guardian itself could not
run, the verdict is `UNKNOWN` — visibly not-a-pass, so nothing downstream can
mistake an outage for approval.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.domain.common import DomainModel, Id, new_id, utc_now

#: Bumped whenever the checks or the verdict rules change, so results from
#: different rules are never silently compared as though they were equivalent.
GUARDIAN_VERSION = "v1"


class GuardianVerdict(StrEnum):
    PASS = "PASS"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECT = "REJECT"
    #: The check itself failed. Never silently a pass.
    UNKNOWN = "UNKNOWN"


class GuardianCheck(StrEnum):
    """What the guardian looks at.

    Each one maps to something the Brand Brain actually defines. The guardian
    never invents a rule — a compliance requirement the brand has not stated is
    not a finding, it is an opinion.
    """

    BRAND_TONE = "brand_tone"
    VISUAL_IDENTITY = "visual_identity"
    CLAIM_SAFETY = "claim_safety"
    PRODUCT_REPRESENTATION = "product_representation"
    BRAND_RESTRICTIONS = "brand_restrictions"
    LOGO_READINESS = "logo_readiness"
    COLOR_CONSTRAINTS = "color_constraints"
    POLICY_COMPLIANCE = "policy_compliance"


#: What each check means, in the words the model is given and a user reads.
CHECK_GUIDANCE: dict[GuardianCheck, str] = {
    GuardianCheck.BRAND_TONE: (
        "Does the image carry the brand's stated tone, or does it feel like a "
        "different company's advertising?"
    ),
    GuardianCheck.VISUAL_IDENTITY: (
        "Is this recognisably within the brand's visual world — its restraint, "
        "its material language, its level of polish?"
    ),
    GuardianCheck.CLAIM_SAFETY: (
        "Does the image visually imply any claim the brand prohibits? Judge what "
        "the picture asserts, not what text says — the text is added later."
    ),
    GuardianCheck.PRODUCT_REPRESENTATION: (
        "Is the product depicted accurately and fairly? Misrepresenting what the "
        "product is or does is a brand failure, not a taste question."
    ),
    GuardianCheck.BRAND_RESTRICTIONS: (
        "Does the image break any stated visual restriction the brand listed?"
    ),
    GuardianCheck.LOGO_READINESS: (
        "Is there a clean, uncluttered area where the logo will be placed later, "
        "and is the image free of any competing or invented logo or wordmark?"
    ),
    GuardianCheck.COLOR_CONSTRAINTS: (
        "Does the palette sit within the brand's colour world, or does it fight it?"
    ),
    GuardianCheck.POLICY_COMPLIANCE: (
        "Anything in the image that conflicts with a restriction the brand has "
        "explicitly stated. Do not invent legal or regulatory requirements."
    ),
}

#: The checks a model is asked to judge. The rest are settled in code, and a
#: model is never asked to confirm a fact the backend already holds.
QUALITATIVE_CHECKS: tuple[GuardianCheck, ...] = (
    GuardianCheck.BRAND_TONE,
    GuardianCheck.VISUAL_IDENTITY,
    GuardianCheck.CLAIM_SAFETY,
    GuardianCheck.PRODUCT_REPRESENTATION,
    GuardianCheck.LOGO_READINESS,
    GuardianCheck.POLICY_COMPLIANCE,
)


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    #: The brand defines nothing to check against. Not a pass, not a failure.
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Severity(StrEnum):
    MINOR = "minor"
    MAJOR = "major"
    BLOCKING = "blocking"


class GuardianCheckResult(DomainModel):
    """One check, its outcome, and what would fix it."""

    check: GuardianCheck
    status: CheckStatus
    #: Only meaningful when the check did not pass.
    severity: Severity | None = None
    detail: str = Field(default="", max_length=400)
    #: A guardian that only says "no" makes the revision loop useless.
    suggested_fix: str | None = Field(default=None, max_length=300)
    #: True when code decided this, not a model. Shown to the user, because
    #: "we matched a prohibited claim" and "a model thought so" carry different
    #: weight.
    deterministic: bool = False

    @model_validator(mode="after")
    def _failures_explain_themselves(self) -> GuardianCheckResult:
        if self.status in (CheckStatus.FAIL, CheckStatus.WARN):
            if self.severity is None:
                raise ValueError(f"{self.check.value}: a non-passing check needs a severity")
            if not self.detail:
                raise ValueError(f"{self.check.value}: a non-passing check needs a detail")
        return self

    def is_blocking(self) -> bool:
        return self.status is CheckStatus.FAIL and self.severity is Severity.BLOCKING


def decide_verdict(
    checks: list[GuardianCheckResult],
) -> tuple[GuardianVerdict, list[str], list[str]]:
    """Verdict, critical issues, warnings — computed, never asked of a model.

    The rules, in order of severity:

    * a **blocking** failure is a REJECT on its own;
    * any other **failure** is NEEDS_REVISION;
    * a **warning** is worth saying but does not hold the creative back;
    * no checks at all is UNKNOWN — an outage must never read as approval.
    """
    if not checks:
        return GuardianVerdict.UNKNOWN, ["The brand check did not complete."], []

    critical = [f"{_label(c.check)}: {c.detail}" for c in checks if c.is_blocking()]
    failures = [
        f"{_label(c.check)}: {c.detail}"
        for c in checks
        if c.status is CheckStatus.FAIL and not c.is_blocking()
    ]
    warnings = [f"{_label(c.check)}: {c.detail}" for c in checks if c.status is CheckStatus.WARN]

    if critical:
        return GuardianVerdict.REJECT, critical, warnings
    if failures:
        return GuardianVerdict.NEEDS_REVISION, failures, warnings
    return GuardianVerdict.PASS, [], warnings


def _label(check: GuardianCheck) -> str:
    return check.value.replace("_", " ").capitalize()


class BrandGuardianResult(DomainModel):
    """One asset, judged against the brand's own rules."""

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    generated_asset_id: Id
    #: The plan the asset came from. A guardian result, like an evaluation, is
    #: always about the version the asset was actually generated from.
    specification_id: Id
    specification_version: int = Field(default=1, ge=1)
    guardian_version: str = GUARDIAN_VERSION
    guardian_model: str | None = None

    verdict: GuardianVerdict
    checks: list[GuardianCheckResult] = Field(default_factory=list)
    #: What must change. Empty on a pass.
    critical_issues: list[str] = Field(default_factory=list, max_length=10)
    warnings: list[str] = Field(default_factory=list, max_length=10)
    #: One or two sentences a human reads. Never a reasoning trace.
    summary: str = Field(default="", max_length=600)
    evaluated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _verdict_follows_from_the_checks(self) -> BrandGuardianResult:
        """The guard that keeps the verdict honest.

        Nothing may construct a result whose verdict does not follow from its
        own checks — not a model, not a migration, not a future caller taking a
        shortcut. `UNKNOWN` is exempt: it means the checks never ran.
        """
        if self.verdict is GuardianVerdict.UNKNOWN:
            return self
        expected, _, _ = decide_verdict(self.checks)
        if expected is not self.verdict:
            raise ValueError(
                f"verdict {self.verdict.value} does not follow from the checks "
                f"(expected {expected.value})"
            )
        return self

    def blocks_release(self) -> bool:
        """A veto. Ranking may still love this asset; it cannot be used."""
        return self.verdict in (GuardianVerdict.REJECT, GuardianVerdict.NEEDS_REVISION)

    def failed_checks(self) -> list[GuardianCheckResult]:
        return [c for c in self.checks if c.status in (CheckStatus.FAIL, CheckStatus.WARN)]

    def fixes(self) -> list[str]:
        """Everything the guardian suggested, for the revision planner to read."""
        return [c.suggested_fix for c in self.checks if c.suggested_fix]


def build_guardian_result(
    *,
    campaign_id: str,
    generated_asset_id: str,
    specification_id: str,
    specification_version: int,
    checks: list[GuardianCheckResult],
    summary: str,
    guardian_model: str | None = None,
) -> BrandGuardianResult:
    """The only way a result is made.

    Checks come from the deterministic rules and the model; the verdict is
    computed here. A caller cannot supply one, which is what makes every stored
    verdict reproducible from its own findings.
    """
    verdict, critical, warnings = decide_verdict(checks)
    return BrandGuardianResult(
        campaign_id=campaign_id,
        generated_asset_id=generated_asset_id,
        specification_id=specification_id,
        specification_version=specification_version,
        guardian_model=guardian_model,
        verdict=verdict,
        checks=checks,
        critical_issues=critical[:10],
        warnings=warnings[:10],
        summary=summary,
    )
