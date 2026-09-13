"""The Brand Guardian domain: checks, verdict rules, versioning.

The guardian holds a veto over the ranking, so its verdict has to be
reproducible from its own findings. These tests pin the rules that turn checks
into a verdict, and the guard that stops anything constructing a result whose
verdict does not follow from them.
"""

from __future__ import annotations

import pytest

from app.domain.guardian import (
    CHECK_GUIDANCE,
    GUARDIAN_VERSION,
    QUALITATIVE_CHECKS,
    BrandGuardianResult,
    CheckStatus,
    GuardianCheck,
    GuardianCheckResult,
    GuardianVerdict,
    Severity,
    build_guardian_result,
    decide_verdict,
)

pytestmark = pytest.mark.unit


def _passing(check: GuardianCheck) -> GuardianCheckResult:
    return GuardianCheckResult(check=check, status=CheckStatus.PASS, detail="fine")


def _failing(check: GuardianCheck, severity: Severity = Severity.MAJOR) -> GuardianCheckResult:
    return GuardianCheckResult(
        check=check,
        status=CheckStatus.FAIL,
        severity=severity,
        detail="a stated problem",
        suggested_fix="do it differently",
    )


def _warning(check: GuardianCheck) -> GuardianCheckResult:
    return GuardianCheckResult(
        check=check, status=CheckStatus.WARN, severity=Severity.MINOR, detail="worth a look"
    )


def _all_passing() -> list[GuardianCheckResult]:
    return [_passing(check) for check in GuardianCheck]


class TestChecks:
    def test_every_check_is_explained(self) -> None:
        """The same words go to the model and to the user, so a check with no
        definition would be judged on guesswork."""
        assert set(CHECK_GUIDANCE) == set(GuardianCheck)
        assert all(text.strip() for text in CHECK_GUIDANCE.values())

    def test_the_qualitative_checks_are_a_subset(self) -> None:
        """The rest are settled in code — a model is never asked to confirm a
        fact the backend already holds."""
        assert set(QUALITATIVE_CHECKS) < set(GuardianCheck)

    def test_a_failure_must_carry_a_severity_and_a_detail(self) -> None:
        with pytest.raises(ValueError, match="needs a severity"):
            GuardianCheckResult(check=GuardianCheck.BRAND_TONE, status=CheckStatus.FAIL, detail="x")
        with pytest.raises(ValueError, match="needs a detail"):
            GuardianCheckResult(
                check=GuardianCheck.BRAND_TONE,
                status=CheckStatus.FAIL,
                severity=Severity.MAJOR,
            )

    def test_a_passing_check_needs_neither(self) -> None:
        assert _passing(GuardianCheck.BRAND_TONE).severity is None

    def test_not_applicable_is_neither_pass_nor_fail(self) -> None:
        """A brand that defines no colour rules has nothing to violate."""
        result = GuardianCheckResult(
            check=GuardianCheck.COLOR_CONSTRAINTS,
            status=CheckStatus.NOT_APPLICABLE,
            detail="the brand defines no palette",
        )
        assert result.is_blocking() is False


class TestVerdict:
    def test_all_passing_is_a_pass(self) -> None:
        verdict, critical, warnings = decide_verdict(_all_passing())
        assert verdict is GuardianVerdict.PASS
        assert critical == [] and warnings == []

    def test_a_blocking_failure_is_a_reject(self) -> None:
        checks = [*_all_passing()[:-1], _failing(GuardianCheck.CLAIM_SAFETY, Severity.BLOCKING)]
        verdict, critical, _ = decide_verdict(checks)
        assert verdict is GuardianVerdict.REJECT
        assert critical and "Claim safety" in critical[0]

    def test_a_major_failure_needs_revision(self) -> None:
        checks = [*_all_passing()[:-1], _failing(GuardianCheck.PRODUCT_REPRESENTATION)]
        verdict, critical, _ = decide_verdict(checks)
        assert verdict is GuardianVerdict.NEEDS_REVISION
        assert critical

    def test_a_warning_does_not_hold_a_creative_back(self) -> None:
        checks = [*_all_passing()[:-1], _warning(GuardianCheck.COLOR_CONSTRAINTS)]
        verdict, critical, warnings = decide_verdict(checks)
        assert verdict is GuardianVerdict.PASS
        assert critical == []
        assert warnings and "Color constraints" in warnings[0]

    def test_a_blocking_failure_outranks_a_major_one(self) -> None:
        checks = [
            _failing(GuardianCheck.BRAND_TONE),
            _failing(GuardianCheck.CLAIM_SAFETY, Severity.BLOCKING),
        ]
        verdict, critical, _ = decide_verdict(checks)
        assert verdict is GuardianVerdict.REJECT
        # Only the blocking one is called critical; severity is not flattened.
        assert len(critical) == 1
        assert "Claim safety" in critical[0]

    def test_no_checks_is_unknown_never_a_pass(self) -> None:
        """An outage must never read as brand approval."""
        verdict, critical, _ = decide_verdict([])
        assert verdict is GuardianVerdict.UNKNOWN
        assert critical

    def test_it_is_deterministic(self) -> None:
        checks = [*_all_passing()[:-2], _warning(GuardianCheck.BRAND_TONE)]
        assert decide_verdict(checks) == decide_verdict(list(reversed(checks)))


class TestResultConstruction:
    def test_building_computes_the_verdict(self) -> None:
        result = build_guardian_result(
            campaign_id="c1",
            generated_asset_id="a1",
            specification_id="s1",
            specification_version=2,
            checks=_all_passing(),
            summary="On brand.",
        )
        assert result.verdict is GuardianVerdict.PASS
        assert result.guardian_version == GUARDIAN_VERSION
        assert result.specification_version == 2

    def test_a_verdict_that_does_not_follow_is_rejected(self) -> None:
        """The guard that stops a model — or a shortcut — declaring a pass over
        its own failing checks."""
        with pytest.raises(ValueError, match="does not follow"):
            BrandGuardianResult(
                campaign_id="c1",
                generated_asset_id="a1",
                specification_id="s1",
                verdict=GuardianVerdict.PASS,
                checks=[_failing(GuardianCheck.CLAIM_SAFETY, Severity.BLOCKING)],
            )

    def test_unknown_is_exempt_because_the_checks_never_ran(self) -> None:
        result = BrandGuardianResult(
            campaign_id="c1",
            generated_asset_id="a1",
            specification_id="s1",
            verdict=GuardianVerdict.UNKNOWN,
            checks=[],
            summary="The brand check could not run.",
        )
        assert result.verdict is GuardianVerdict.UNKNOWN

    def test_a_failing_result_carries_its_issues(self) -> None:
        result = build_guardian_result(
            campaign_id="c1",
            generated_asset_id="a1",
            specification_id="s1",
            specification_version=1,
            checks=[*_all_passing()[:-1], _failing(GuardianCheck.BRAND_RESTRICTIONS)],
            summary="One restriction broken.",
        )
        assert result.verdict is GuardianVerdict.NEEDS_REVISION
        assert result.critical_issues
        assert result.failed_checks()

    def test_it_offers_fixes_for_the_revision_planner(self) -> None:
        """A guardian that only says no makes the revision loop useless."""
        result = build_guardian_result(
            campaign_id="c1",
            generated_asset_id="a1",
            specification_id="s1",
            specification_version=1,
            checks=[*_all_passing()[:-1], _failing(GuardianCheck.PRODUCT_REPRESENTATION)],
            summary="Product reads as a prop.",
        )
        assert result.fixes() == ["do it differently"]

    def test_a_veto_covers_reject_and_needs_revision(self) -> None:
        """Ranking may still love the asset; it cannot be used either way."""
        for checks, expected in (
            (_all_passing(), False),
            ([*_all_passing()[:-1], _failing(GuardianCheck.BRAND_TONE)], True),
            (
                [*_all_passing()[:-1], _failing(GuardianCheck.CLAIM_SAFETY, Severity.BLOCKING)],
                True,
            ),
        ):
            result = build_guardian_result(
                campaign_id="c1",
                generated_asset_id="a1",
                specification_id="s1",
                specification_version=1,
                checks=checks,
                summary="x",
            )
            assert result.blocks_release() is expected

    def test_the_summary_is_concise(self) -> None:
        with pytest.raises(ValueError):
            BrandGuardianResult(
                campaign_id="c1",
                generated_asset_id="a1",
                specification_id="s1",
                verdict=GuardianVerdict.UNKNOWN,
                summary="x" * 601,
            )
