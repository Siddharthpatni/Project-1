"""Phase 2 — global coverage: URL classification + ordering across continents.

Pure logic (no network/DB): verifies classify_url_type recognises at least one
representative URL per continent and that get_strategy_order keeps the free
ADAPTIVE step ahead of the paid LLM step for the new public portal types.
"""
from __future__ import annotations

import pytest

from app.models import Strategy
from app.phase3_integration.url_intelligence import (
    URL_TYPE_SUCCESS_RATE,
    UrlType,
    classify_url_type,
    get_strategy_order,
)


@pytest.mark.parametrize("url,expected", [
    # ── Americas ──
    ("https://sam.gov/opp/123/view", UrlType.US_SAM),
    ("https://www.grants.gov/web/grants/view-opportunity.html?oppId=1", UrlType.US_SAM),
    ("https://canadabuys.canada.ca/en/tender-opportunities/tender-notice/123", UrlType.CA_TENDERS),
    ("https://www.merx.com/public/solicitations/456", UrlType.CA_TENDERS),
    ("https://www.comprasnet.gov.br/edital/abc", UrlType.LATAM),
    ("https://www.mercadopublico.cl/Procurement/Modules/RFB/x.aspx", UrlType.LATAM),
    ("https://community.secop.gov.co/Public/Tendering/x", UrlType.LATAM),
    # ── Asia ──
    ("https://gem.gov.in/bidding/bid/789", UrlType.IN_GEM),
    ("https://eprocure.gov.in/eprocure/app", UrlType.IN_GEM),
    ("https://www.gebiz.gov.sg/ptn/opportunity/x", UrlType.ASIA_OTHER),
    ("https://www.ccgp.gov.cn/cggg/x.htm", UrlType.ASIA_OTHER),
    # ── Africa ──
    ("https://www.etenders.gov.za/Home/TenderOpportunities/", UrlType.AFRICA),
    ("https://tenders.go.ke/website/tenders/index", UrlType.AFRICA),
    # ── Oceania ──
    ("https://www.tenders.gov.au/atm/show/abc", UrlType.AU_AUSTENDER),
    ("https://www.tenders.nsw.gov.au/?event=public.rft.show&RFTUUID=x", UrlType.AU_AUSTENDER),
    ("https://www.gets.govt.nz/ExternalIndex.htm", UrlType.NZ_GETS),
    # ── More Europe ──
    ("https://www.acquistinretepa.it/opencms/opencms/scheda_x.html", UrlType.IT_PROC),
    ("https://www.etenders.gov.ie/epps/cft/x.do", UrlType.IE_ETENDERS),
    ("https://www.doffin.no/Notice/Details/2024-123", UrlType.NORDIC),
    ("https://hankintailmoitukset.fi/fi/public/procurement/123", UrlType.NORDIC),
    ("https://www.e-licitatie.ro/pub/notices/c-notice/v2/view/x", UrlType.EU_EAST),
    ("https://nen.nipez.cz/profil/x", UrlType.EU_EAST),
])
def test_classify_url_type_global(url, expected):
    assert classify_url_type(url) == expected


def test_unknown_still_unknown():
    assert classify_url_type("https://random-company.example.com/page") == UrlType.UNKNOWN


def test_all_new_types_have_success_rate():
    """Every UrlType must have a success-rate entry (used by prevalidate)."""
    for t in UrlType:
        assert t in URL_TYPE_SUCCESS_RATE, f"missing success rate for {t}"


@pytest.mark.parametrize("url_type", [
    UrlType.US_SAM, UrlType.CA_TENDERS, UrlType.AU_AUSTENDER, UrlType.NZ_GETS,
    UrlType.IE_ETENDERS, UrlType.NORDIC, UrlType.LATAM, UrlType.IN_GEM,
    UrlType.IT_PROC, UrlType.EU_EAST, UrlType.AFRICA, UrlType.ASIA_OTHER,
])
def test_new_types_run_adaptive_before_llm(url_type):
    order = get_strategy_order(url_type, "unknown")
    assert Strategy.ADAPTIVE in order
    assert Strategy.LLM_GENERATED in order
    assert order.index(Strategy.ADAPTIVE) < order.index(Strategy.LLM_GENERATED)
    # and a learned CUA route is still replayed before the expensive CUA
    assert order.index(Strategy.LEARNED_ROUTE) < order.index(Strategy.CUA)
