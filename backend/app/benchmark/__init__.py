"""The Indian Hyperlocal Campaign Benchmark — a synthetic dataset.

Three fictional companies in three Indian cities, at three company sizes, in
three industries, with three campaigns each. The dataset exists to answer one
question: **does Campaign OS adapt a campaign to a local market, or does it
translate one?**

Everything here is expressed in the product's own domain models —
`BrandProfile`, `CampaignBrief`, `CreativeDirection`, `CreativeSpecification`,
`ReferenceAnalysis` — so the dataset cannot drift from the schemas it claims
to exercise without failing to import. There is no parallel benchmark schema
and no second application.

**Every company, brand, product, person, claim and figure in this package is
fictional**, written for this benchmark. Nothing here is market research and
no claim is a real product claim.

See `docs/HYPERLOCAL_BENCHMARK.md` for the methodology, and
`scripts/seed_benchmark.py` to load it into a database.
"""

from __future__ import annotations

from app.benchmark import aarohan_foods, mitti_and_bean, nila_living
from app.benchmark.matrix import (
    CASES,
    NAIVE_VS_HYPERLOCAL,
    BenchmarkCase,
    LocalisationDimension,
    NaiveVsHyperlocal,
)
from app.benchmark.types import (
    BENCHMARK_CHANNELS,
    FICTIONAL_NOTICE,
    BenchmarkCampaign,
    BenchmarkCompany,
    CompanySize,
    LanguagePreference,
    LocalMarketContext,
)

#: The three companies, in ascending order of governance weight. The order is
#: meaningful: the benchmark's governance dimension reads down this list.
COMPANIES: tuple[BenchmarkCompany, ...] = (
    mitti_and_bean.COMPANY,
    nila_living.COMPANY,
    aarohan_foods.COMPANY,
)


def company(slug: str) -> BenchmarkCompany:
    """One company by slug, or `KeyError` naming what is available."""
    for candidate in COMPANIES:
        if candidate.slug == slug:
            return candidate
    raise KeyError(f"No benchmark company {slug!r}. Available: {[c.slug for c in COMPANIES]}")


def campaign(slug: str) -> tuple[BenchmarkCompany, BenchmarkCampaign]:
    """One campaign by slug, with the company that owns it.

    Returns the owner as well as the campaign because almost nothing about a
    campaign in this benchmark is interpretable without its brand — which is
    the dataset making the product's own argument about governance.
    """
    for owner in COMPANIES:
        for candidate in owner.campaigns:
            if candidate.slug == slug:
                return owner, candidate
    available = [c.slug for owner in COMPANIES for c in owner.campaigns]
    raise KeyError(f"No benchmark campaign {slug!r}. Available: {available}")


def all_campaigns() -> tuple[tuple[BenchmarkCompany, BenchmarkCampaign], ...]:
    """Every campaign with its owner, in dataset order."""
    return tuple((owner, candidate) for owner in COMPANIES for candidate in owner.campaigns)


__all__ = [
    "BENCHMARK_CHANNELS",
    "CASES",
    "COMPANIES",
    "FICTIONAL_NOTICE",
    "NAIVE_VS_HYPERLOCAL",
    "BenchmarkCampaign",
    "BenchmarkCase",
    "BenchmarkCompany",
    "CompanySize",
    "LanguagePreference",
    "LocalMarketContext",
    "LocalisationDimension",
    "NaiveVsHyperlocal",
    "all_campaigns",
    "campaign",
    "company",
]
