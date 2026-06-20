"""
URL Intelligence Layer — pre-classify every incoming URL before the cascade starts.

For 10,000+ URL production runs, the biggest performance wins come from:
  1. Not wasting 90s of LLM generation on auth-gated portals that will always fail.
  2. Routing Satellite/DTVP directly to deterministic (skips Playwright entirely).
  3. Circuit-breaking repeatedly failing domains so workers stay free for winnable URLs.
  4. Domain-level rate limiting so portals don't ban the scraper.

Architecture
────────────
                     ┌─────────────────────────┐
  URL ──────────────►│ classify_url_type()      │
                     └──────────┬──────────────┘
                                │
                     ┌──────────▼──────────────┐
                     │ CircuitBreaker.check()   │◄── Redis (per-domain state)
                     └──────────┬──────────────┘
                                │
                     ┌──────────▼──────────────┐
                     │ get_strategy_order()     │ optimised per URL type
                     └──────────┬──────────────┘
                                │
                     ┌──────────▼──────────────┐
                     │ DomainRateLimiter        │◄── Redis (per-domain token bucket)
                     └──────────┬──────────────┘
                                │
                           Cascade pipeline
"""
from __future__ import annotations

import re
import time
from enum import Enum
from typing import Optional

from app.utils.logger import get_logger

log = get_logger(__name__)


# ─── URL Type Classification ──────────────────────────────────────────────────

class UrlType(str, Enum):
    """Predicted scrapeability of a URL — derived from URL structure alone."""
    # ── German / DTVP family ──────────────────────────────────────────────────
    SATELLITE     = "satellite"       # DTVP/VMPSatellite — deterministic ZIP, ~95% success
    NETSERVER_PUB = "netserver_pub"   # NetServer publication page — public docs, ~70% success
    NETSERVER_AUTH= "netserver_auth"  # NetServer procedure — login required, ~5% success
    EVERGABE_DEEP = "evergabe_deep"   # eVergabe Cosinex deeplink — auth required, ~5% success
    EVA_PORTAL    = "eva_portal"      # e-VA bieter portal — auth required, ~5% success
    SUBREPORT     = "subreport"       # subreport ELViS — subscription service, ~40% success
    EVERGABE_WEB  = "evergabe_web"    # evergabe-online.de Wicket — ~50% success
    # ── EU / International ────────────────────────────────────────────────────
    TED_EUROPA    = "ted_europa"      # TED Europa (EU Official Journal) — ~85% success
    UK_TENDER     = "uk_tender"       # UK Find a Tender / Contracts Finder — ~80% success
    FR_PLACE      = "fr_place"        # French PLACE / BOAMP / marchés publics — ~70% success
    PL_MINIPORTAL = "pl_miniportal"   # Polish miniPortal / BZP — ~70% success
    ES_PLACE      = "es_place"        # Spanish PLACE / contratación del estado — ~70% success
    PT_BASE       = "pt_base"         # Portuguese BASE / IncaFE — ~70% success
    NL_TENDERNED  = "nl_tenderned"    # Dutch TenderNed — ~80% success
    BE_EPROCURE   = "be_eprocure"     # Belgian e-Procurement — ~75% success
    AT_AUSSCHREIB = "at_ausschreib"   # Austrian ausschreibungen.at — ~70% success
    CH_SIMAP      = "ch_simap"        # Swiss SIMAP / Bund procurement — ~75% success
    # ── More Europe ───────────────────────────────────────────────────────────
    IT_PROC       = "it_proc"         # Italy CONSIP/MEPA/acquistinrete — ~60% success
    IE_ETENDERS   = "ie_etenders"     # Ireland eTenders — ~70% success
    NORDIC        = "nordic"          # Doffin/Mercell/Visma-Opic/Hilma/Udbud (NO/SE/FI/DK) — ~70%
    EU_EAST       = "eu_east"         # GR/CZ/HU/RO/SK/SI/HR/BG/EE/LV/LT portals — ~60% success
    # ── Americas ──────────────────────────────────────────────────────────────
    US_SAM        = "us_sam"          # USA SAM.gov / grants.gov — ~65% success
    CA_TENDERS    = "ca_tenders"      # Canada CanadaBuys / MERX — ~65% success
    LATAM         = "latam"           # BR/MX/CL/AR/CO/PE procurement — ~60% success
    # ── Asia ──────────────────────────────────────────────────────────────────
    IN_GEM        = "in_gem"          # India GeM / eProcure / NIC — ~60% success
    ASIA_OTHER    = "asia_other"      # SG/JP/CN/KR/other Asia — mixed, often login ~45%
    # ── Africa ────────────────────────────────────────────────────────────────
    AFRICA        = "africa"          # ZA/KE/NG/EG e-tender portals — ~55% success
    # ── Oceania ───────────────────────────────────────────────────────────────
    AU_AUSTENDER  = "au_austender"    # Australia AusTender + state portals — ~75% success
    NZ_GETS       = "nz_gets"         # New Zealand GETS — ~75% success
    UNKNOWN       = "unknown"         # Needs full cascade


# Patterns evaluated in order — first match wins
_URL_TYPE_PATTERNS: list[tuple[UrlType, list[str]]] = [
    # ── German / DTVP family (checked first — most common in current dataset) ──
    (UrlType.SATELLITE, [
        r"/Satellite/notice/",
        r"/Satellite/public/company/project/",
        r"/VMPSatellite/notice/",
        r"/VMPSatellite/public/company/project/",
        r"/Vergabe/notice/",
        r"/Vergabe/public/company/project/",
    ]),
    (UrlType.EVERGABE_DEEP, [
        r"/evergabe\.bieter/api/supplier/external/deeplink/",
        r"/bieter/api/supplier/external/deeplink/",
        r"evergabe\.bieter",
        r"evergabe\.nrw\.de/evergabe\.bieter",
        r"evergabe\.nrw\.de/bieter",
        r"evergabe\.bayern",
        r"vergabemarktplatz\.brandenburg",
        r"vergabe\.muenchen\.de/.*evergabe",
    ]),
    (UrlType.EVA_PORTAL, [
        r"e-va\.eu",
        r"e-va\.de",
        r"/bundde\?data=",
    ]),
    (UrlType.NETSERVER_AUTH, [
        r"/NetServer/TenderingProcedureDetails\?function=_Details",
        r"/NetServer/TenderingProcedureDetails\?function=_Tender",
        r"beschaffungen\.barmer\.de",
    ]),
    (UrlType.NETSERVER_PUB, [
        r"/NetServer/PublicationControllerServlet\?function=Detail",
        r"/NetServer/PublicationControllerServlet\?function=GetDocumentFile",
        r"vergabe24\.de/NetServer/",
        r"tender24\.de/NetServer/",
    ]),
    (UrlType.SUBREPORT, [
        r"subreport\.de",
        r"subreport-elvis\.de",
    ]),
    (UrlType.EVERGABE_WEB, [
        r"evergabe-online\.de",
        r"evergabe\.de/",
    ]),
    # ── EU / International portals ────────────────────────────────────────────
    (UrlType.TED_EUROPA, [
        r"ted\.europa\.eu",
        r"etendering\.ted\.europa\.eu",
        r"simap\.ted\.europa\.eu",
        r"eprocurement\.ted\.europa\.eu",
        r"enotices\.ted\.europa\.eu",
        r"enotices2\.ted\.europa\.eu",
    ]),
    (UrlType.UK_TENDER, [
        r"find-tender\.service\.gov\.uk",
        r"contractsfinder\.service\.gov\.uk",
        r"procurementjourney\.scotland\.gov\.uk",
        r"sell2wales\.gov\.wales",
        r"etenderwales\.bravosolution\.co\.uk",
        r"procontract\.due-north\.com",
    ]),
    (UrlType.FR_PLACE, [
        r"marches-publics\.info",
        r"place\.gouv\.fr",
        r"boamp\.fr",
        r"aws\.achatpublic\.com",
        r"achatpublic\.com",
        r"megalis\.bretagne\.fr",
        r"klekoon\.com",
        r"atexo\.fr.*marche",
    ]),
    (UrlType.PL_MINIPORTAL, [
        r"miniportal\.uzp\.gov\.pl",
        r"ezamowienia\.gov\.pl",
        r"przetargi\.pl",
        r"bzp\.uzp\.gov\.pl",
    ]),
    (UrlType.ES_PLACE, [
        r"contrataciondelestado\.es",
        r"contratacion\.gob\.es",
        r"licitacion\.es",
        r"perfiles\.contratosdelsector\.es",
    ]),
    (UrlType.PT_BASE, [
        r"base\.gov\.pt",
        r"acingov\.pt",
        r"ancp\.gov\.pt",
        r"vortal\.pt",
        r"sapoempresas\.pt.*concurso",
    ]),
    (UrlType.NL_TENDERNED, [
        r"tenderned\.nl",
        r"tenderned\.com",
        r"negometrix\.com",
        r"aanbestedingskalender\.nl",
    ]),
    (UrlType.BE_EPROCURE, [
        r"eten\.be",
        r"publicprocurement\.be",
        r"jepp\.be",
        r"e-procurement\.be",
        r"bda-online\.be",
    ]),
    (UrlType.AT_AUSSCHREIB, [
        r"ausschreibungen\.at",
        r"bieterportal\.at",
        r"beschaffung\.gv\.at",
        r"bbg\.gv\.at",
    ]),
    (UrlType.CH_SIMAP, [
        r"simap\.ch",
        r"beschaffung\.admin\.ch",
        r"ausschreibungen\.admin\.ch",
        r"bkb\.admin\.ch",
    ]),
    # ── More Europe ────────────────────────────────────────────────────────────
    (UrlType.IT_PROC, [
        r"acquistinretepa\.it",
        r"acquistinrete",
        r"consip\.it",
        r"tuttogare",
        r"appaltipubblici",
        r"serviziocontrattipubblici\.it",
    ]),
    (UrlType.IE_ETENDERS, [
        r"etenders\.gov\.ie",
        r"irlgov.*etender",
    ]),
    (UrlType.NORDIC, [
        r"doffin\.no",                 # Norway
        r"mercell\.com",
        r"e-avrop\.com",               # Sweden
        r"visma.*opic|opic\.com",
        r"kommers\.se",
        r"tendsign\.com",
        r"hankintailmoitukset\.fi",    # Finland (Hilma)
        r"udbud\.dk|ethics\.dk",       # Denmark
    ]),
    (UrlType.EU_EAST, [
        r"promitheus\.gov\.gr|eprocurement\.gov\.gr",  # Greece
        r"nen\.nipez\.cz|tenderarena\.cz",             # Czechia
        r"kozbeszerzes\.hu|ekr\.gov\.hu",              # Hungary
        r"e-licitatie\.ro",                            # Romania
        r"uvo\.gov\.sk|eks\.sk",                       # Slovakia
        r"enarocanje\.si",                             # Slovenia
        r"eojn\.nn\.hr",                               # Croatia
        r"eop\.bg|aop\.bg",                            # Bulgaria
        r"riigihanked\.riik\.ee",                      # Estonia
        r"eis\.gov\.lv",                               # Latvia
        r"cvpp\.lt|vpt\.lt",                           # Lithuania
    ]),
    # ── Americas ───────────────────────────────────────────────────────────────
    (UrlType.US_SAM, [
        r"sam\.gov",
        r"grants\.gov",
        r"fbo\.gov",
        r"acquisition\.gov",
        r"unison.*marketplace",
        r"bonfirehub\.com",
    ]),
    (UrlType.CA_TENDERS, [
        r"canadabuys\.canada\.ca",
        r"buyandsell\.gc\.ca",
        r"merx\.com",
        r"bidsandtenders\.ca",
        r"biddingo\.com",
        r"bcbid\.gov\.bc\.ca",
    ]),
    (UrlType.LATAM, [
        r"comprasnet|gov\.br/compras|\.gov\.br.*licita|licitacoes-e",  # Brazil
        r"compranet|comprasmx",                                        # Mexico
        r"mercadopublico\.cl",                                         # Chile
        r"comprar\.gob\.ar|argentinacompra",                          # Argentina
        r"colombiacompra|secop\.gov\.co",                             # Colombia
        r"seace\.gob\.pe|perucompras",                                # Peru
    ]),
    # ── Asia ───────────────────────────────────────────────────────────────────
    (UrlType.IN_GEM, [
        r"gem\.gov\.in",
        r"eprocure\.gov\.in",
        r"etenders?\.gov\.in",
        r"\.nic\.in.*tender",
        r"tenderwizard\.com",
    ]),
    (UrlType.ASIA_OTHER, [
        r"gebiz\.gov\.sg",             # Singapore
        r"njss\.info|geps\.go\.jp|p-portal\.go\.jp",  # Japan
        r"ccgp\.gov\.cn|chinabidding",  # China
        r"g2b\.go\.kr",                # South Korea
        r"eprocure.*gov\.(np|bd|pk|lk)",  # Nepal/Bangladesh/Pakistan/Sri Lanka
    ]),
    # ── Africa ─────────────────────────────────────────────────────────────────
    (UrlType.AFRICA, [
        r"etenders\.gov\.za|etender.*\.gov\.za",  # South Africa
        r"tenders\.go\.ke",                       # Kenya
        r"bpp\.gov\.ng|nocopo\.bpp\.gov\.ng",     # Nigeria
        r"etenders\.gov\.eg",                     # Egypt
        r"ghana.*tender|tender.*gov\.gh",         # Ghana
    ]),
    # ── Oceania ────────────────────────────────────────────────────────────────
    (UrlType.AU_AUSTENDER, [
        r"tenders\.gov\.au",
        r"austender",
        r"tenders\.nsw\.gov\.au",
        r"tenders\.vic\.gov\.au",
        r"qtenders|hpw\.qld\.gov\.au",
        r"tenders\.sa\.gov\.au|tenders\.wa\.gov\.au",
        r"etender.*\.gov\.au",
    ]),
    (UrlType.NZ_GETS, [
        r"gets\.govt\.nz",
    ]),
]


def classify_url_type(url: str) -> UrlType:
    """
    Classify a URL into a scrapeability category using URL patterns alone.
    No HTTP requests — pure string matching. O(n patterns) per URL.

    Returns UrlType enum value that drives strategy selection.
    """
    for url_type, patterns in _URL_TYPE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return url_type
    return UrlType.UNKNOWN


# Expected success rate per URL type — used for analytics and priority queuing
URL_TYPE_SUCCESS_RATE: dict[UrlType, float] = {
    # German / DTVP family
    UrlType.SATELLITE:      0.93,
    UrlType.NETSERVER_PUB:  0.65,
    UrlType.NETSERVER_AUTH: 0.05,
    UrlType.EVERGABE_DEEP:  0.05,
    UrlType.EVA_PORTAL:     0.05,
    UrlType.SUBREPORT:      0.40,
    UrlType.EVERGABE_WEB:   0.50,
    # International
    UrlType.TED_EUROPA:    0.85,
    UrlType.UK_TENDER:     0.80,
    UrlType.FR_PLACE:      0.70,
    UrlType.PL_MINIPORTAL: 0.70,
    UrlType.ES_PLACE:      0.70,
    UrlType.PT_BASE:       0.70,
    UrlType.NL_TENDERNED:  0.80,
    UrlType.BE_EPROCURE:   0.75,
    UrlType.AT_AUSSCHREIB: 0.70,
    UrlType.CH_SIMAP:      0.75,
    # More Europe
    UrlType.IT_PROC:       0.60,
    UrlType.IE_ETENDERS:   0.70,
    UrlType.NORDIC:        0.70,
    UrlType.EU_EAST:       0.60,
    # Americas
    UrlType.US_SAM:        0.65,
    UrlType.CA_TENDERS:    0.65,
    UrlType.LATAM:         0.60,
    # Asia
    UrlType.IN_GEM:        0.60,
    UrlType.ASIA_OTHER:    0.45,
    # Africa
    UrlType.AFRICA:        0.55,
    # Oceania
    UrlType.AU_AUSTENDER:  0.75,
    UrlType.NZ_GETS:       0.75,
    UrlType.UNKNOWN:       0.35,
}


# ─── Optimised Strategy Ordering ─────────────────────────────────────────────

from app.models import Strategy


def _inject_adaptive(order: list[Strategy]) -> list[Strategy]:
    """Insert ADAPTIVE immediately before the paid LLM step.

    ADAPTIVE is a free, country-agnostic heuristic scraper — try it before
    spending LLM budget. Only injected for orders that actually reach
    LLM_GENERATED, so deliberately-minimal orders (auth-gated, SATELLITE) keep
    their tuned fast paths. No-op when already present.
    """
    if Strategy.ADAPTIVE in order or Strategy.LLM_GENERATED not in order:
        return order
    idx = order.index(Strategy.LLM_GENERATED)
    return order[:idx] + [Strategy.ADAPTIVE] + order[idx:]


def _inject_learned_route(order: list[Strategy]) -> list[Strategy]:
    """Insert LEARNED_ROUTE immediately before CUA in a strategy order.

    A previously-learned CUA route should always be replayed (cheap Playwright)
    before re-invoking the expensive CUA. Inserting it directly before CUA keeps
    each per-URL-type order's intent intact. No-op when CUA isn't in the order
    or LEARNED_ROUTE is already present.
    """
    if Strategy.CUA not in order or Strategy.LEARNED_ROUTE in order:
        return order
    idx = order.index(Strategy.CUA)
    return order[:idx] + [Strategy.LEARNED_ROUTE] + order[idx:]


def get_strategy_order(url_type: UrlType, platform: str, force: Strategy | None = None) -> list[Strategy]:
    """Public entry point: optimal strategy order with ADAPTIVE + LEARNED_ROUTE injected.

    Delegates to ``_strategy_order_for_type`` then inserts ADAPTIVE (free
    universal heuristic) before the paid LLM step, and LEARNED_ROUTE before CUA
    so a previously-learned route is replayed cheaply before the expensive CUA.
    The ``force`` path is passed through untouched (run exactly that one).
    """
    if force:
        return [force]
    order = _strategy_order_for_type(url_type, platform)
    return _inject_learned_route(_inject_adaptive(order))


def _strategy_order_for_type(url_type: UrlType, platform: str, force: Strategy | None = None) -> list[Strategy]:
    """
    Return the optimal strategy execution order for this URL type.

    Key insight: the default cascade wastes 90s on LLM generation for auth-gated
    portals. This function skips LLM entirely for URL types where it never works,
    saving budget and time for URLs that are actually winnable.

    Strategy time cost:
      EXISTING     ~1–25s   (disk scraper — free)
      DETERMINISTIC ~1–52s  (direct HTTP — free)
      LLM_GENERATED ~30–120s (LLM call + sandbox — costs money)
      CUA           ~30–120s (browser + vision LLM — costs money)
      MANUAL        ~5–45s  (Playwright — free)
    """
    if force:
        return [force]

    if url_type == UrlType.SATELLITE:
        # Deterministic first (fastest, free), then cached scraper as backup.
        # Skip LLM and CUA — if deterministic and cached fail, the specific
        # notice is likely expired or restricted.
        return [Strategy.DETERMINISTIC, Strategy.EXISTING, Strategy.MANUAL]

    if url_type == UrlType.NETSERVER_PUB:
        # Try existing scraper (may have domain-specific one) → deterministic →
        # generic NetServer pub scraper (via MANUAL which calls v1_reference) → LLM last.
        return [Strategy.EXISTING, Strategy.DETERMINISTIC, Strategy.MANUAL, Strategy.LLM_GENERATED, Strategy.CUA]

    if url_type in (UrlType.NETSERVER_AUTH, UrlType.EVA_PORTAL):
        # Login required — LLM generation is guaranteed to fail (logs show 0% over
        # hundreds of attempts). Skip straight to CUA (only hope) then manual.
        # Do NOT waste LLM budget on these.
        return [Strategy.EXISTING, Strategy.CUA, Strategy.MANUAL]

    if url_type == UrlType.EVERGABE_DEEP:
        # Angular deeplink requiring vendor account. CUA is the only strategy with
        # any chance (visual login flow). Skip LLM — it generates scrapers that
        # successfully navigate to the page but cannot log in.
        return [Strategy.EXISTING, Strategy.CUA, Strategy.MANUAL]

    if url_type == UrlType.SUBREPORT:
        # subreport ELViS: has a specific scraper, try it first.
        return [Strategy.EXISTING, Strategy.MANUAL, Strategy.LLM_GENERATED]

    if url_type == UrlType.EVERGABE_WEB:
        return [Strategy.EXISTING, Strategy.MANUAL, Strategy.LLM_GENERATED, Strategy.CUA]

    # ── International portals: try existing scraper first, then LLM (no CUA unless needed)
    if url_type == UrlType.TED_EUROPA:
        # TED has a well-documented REST API — LLM can generate a clean scraper quickly.
        return [Strategy.EXISTING, Strategy.LLM_GENERATED, Strategy.MANUAL, Strategy.CUA]

    if url_type in (
        UrlType.UK_TENDER, UrlType.NL_TENDERNED, UrlType.BE_EPROCURE,
        UrlType.CH_SIMAP, UrlType.AT_AUSSCHREIB,
        # Well-structured public international portals worldwide.
        UrlType.IE_ETENDERS, UrlType.NORDIC, UrlType.US_SAM, UrlType.CA_TENDERS,
        UrlType.AU_AUSTENDER, UrlType.NZ_GETS,
    ):
        # Well-structured public portals — LLM-generated scraper works reliably.
        # (ADAPTIVE is injected before LLM, so the free heuristic runs first.)
        return [Strategy.EXISTING, Strategy.LLM_GENERATED, Strategy.MANUAL, Strategy.CUA]

    if url_type in (
        UrlType.FR_PLACE, UrlType.PL_MINIPORTAL, UrlType.ES_PLACE, UrlType.PT_BASE,
        # Moderately complex portals across other regions.
        UrlType.IT_PROC, UrlType.EU_EAST, UrlType.LATAM, UrlType.IN_GEM,
        UrlType.AFRICA, UrlType.ASIA_OTHER,
    ):
        # Moderately complex portals — try manual reference first, then LLM.
        return [Strategy.EXISTING, Strategy.MANUAL, Strategy.LLM_GENERATED, Strategy.CUA]

    # UNKNOWN: full cascade in default order
    if platform in ("dtvp", "netserver"):
        return [Strategy.DETERMINISTIC, Strategy.EXISTING, Strategy.LLM_GENERATED, Strategy.CUA, Strategy.MANUAL]

    return [Strategy.EXISTING, Strategy.DETERMINISTIC, Strategy.LLM_GENERATED, Strategy.CUA, Strategy.MANUAL]


# ─── Circuit Breaker ─────────────────────────────────────────────────────────

def _cb_event(event: str) -> None:
    """Record a circuit-breaker state event in metrics (never raises)."""
    try:
        from app.core.metrics import CIRCUIT_BREAKER_EVENTS  # noqa: PLC0415
        CIRCUIT_BREAKER_EVENTS.labels(event=event).inc()
    except Exception:  # noqa: BLE001
        pass


def _rl_hit() -> None:
    """Record a rate-limiter rejection in metrics (never raises)."""
    try:
        from app.core.metrics import RATE_LIMIT_HITS  # noqa: PLC0415
        RATE_LIMIT_HITS.inc()
    except Exception:  # noqa: BLE001
        pass


class CircuitState(str, Enum):
    CLOSED   = "closed"    # Normal — allow requests
    OPEN     = "open"      # Tripped — reject requests fast
    HALF_OPEN= "half_open" # Probing — allow one request to test recovery


class CircuitBreaker:
    """
    Per-domain Redis-backed circuit breaker.

    Prevents the system from hammering portals that are down or require auth,
    saving worker slots for URLs that can actually succeed.

    State machine:
      CLOSED  ──(failure_threshold exceeded)──► OPEN
      OPEN    ──(reset_timeout expired)───────► HALF_OPEN
      HALF_OPEN ──(success)──────────────────► CLOSED
      HALF_OPEN ──(failure)──────────────────► OPEN

    All state is stored in Redis so it is shared across all Celery workers.
    Falls back gracefully to CLOSED (allow) if Redis is unavailable.
    """

    def __init__(
        self,
        failure_threshold: int  = 5,      # trips after this many consecutive failures
        reset_timeout:     int  = 1800,   # seconds before testing recovery (30 min)
        half_open_timeout: int  = 300,    # seconds to wait for half-open probe result
        key_prefix:        str  = "vcb:", # Redis key namespace
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout     = reset_timeout
        self.half_open_timeout = half_open_timeout
        self.key_prefix        = key_prefix
        self._redis: object | None = None

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis as _redis
                from app.config import settings
                self._redis = _redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def _key(self, domain: str, suffix: str) -> str:
        return f"{self.key_prefix}{domain}:{suffix}"

    def get_state(self, domain: str) -> CircuitState:
        """Return current circuit state for the domain. Falls back to CLOSED on error."""
        r = self._get_redis()
        if not r:
            return CircuitState.CLOSED
        try:
            state = r.get(self._key(domain, "state"))
            if not state:
                return CircuitState.CLOSED
            return CircuitState(state)
        except Exception:
            return CircuitState.CLOSED

    def allow_request(self, domain: str) -> bool:
        """
        Returns True if a request to this domain should be attempted.
        Returns False if the circuit is OPEN (domain recently failed too many times).
        """
        state = self.get_state(domain)
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.OPEN:
            # Check if reset_timeout has passed → move to HALF_OPEN
            r = self._get_redis()
            if r:
                try:
                    tripped_at = r.get(self._key(domain, "tripped_at"))
                    if tripped_at and (time.time() - float(tripped_at)) > self.reset_timeout:
                        r.set(self._key(domain, "state"), CircuitState.HALF_OPEN.value)
                        r.set(self._key(domain, "half_open_at"), str(time.time()))
                        log.info("circuit_breaker.half_open", domain=domain)
                        _cb_event("half_open")
                        return True  # let one probe through
                except Exception:
                    pass
            _cb_event("reject")
            return False  # still OPEN
        if state == CircuitState.HALF_OPEN:
            # Only allow one probe at a time
            r = self._get_redis()
            if r:
                try:
                    half_open_at = r.get(self._key(domain, "half_open_at"))
                    if half_open_at and (time.time() - float(half_open_at)) > self.half_open_timeout:
                        # Probe timed out without result — re-open
                        r.set(self._key(domain, "state"), CircuitState.OPEN.value)
                        r.set(self._key(domain, "tripped_at"), str(time.time()))
                        return False
                except Exception:
                    pass
            return True  # allow the half-open probe
        return True

    def record_success(self, domain: str) -> None:
        """Record a successful scrape — resets failure count, closes circuit."""
        r = self._get_redis()
        if not r:
            return
        try:
            prev_state = r.get(self._key(domain, "state"))
            pipe = r.pipeline()
            pipe.set(self._key(domain, "state"), CircuitState.CLOSED.value)
            pipe.delete(self._key(domain, "failures"))
            pipe.delete(self._key(domain, "tripped_at"))
            pipe.execute()
            if prev_state and prev_state != CircuitState.CLOSED.value:
                _cb_event("reset")
        except Exception:
            pass

    def record_failure(self, domain: str, error_category: str = "unknown") -> None:
        """
        Record a failed scrape. Trips the circuit when threshold is exceeded.
        Auth errors (login_required, auth, registration_required) trip immediately
        after 3 failures since no strategy can fix them without credentials.
        """
        r = self._get_redis()
        if not r:
            return

        # Immediate-trip categories: no point retrying different strategies
        immediate_trip_categories = {"login_required", "registration_required", "auth", "captcha"}
        immediate_threshold = 3 if error_category in immediate_trip_categories else self.failure_threshold

        try:
            key_failures = self._key(domain, "failures")
            failures = r.incr(key_failures)
            r.expire(key_failures, self.reset_timeout * 2)

            if failures >= immediate_threshold:
                pipe = r.pipeline()
                pipe.set(self._key(domain, "state"), CircuitState.OPEN.value)
                pipe.set(self._key(domain, "tripped_at"), str(time.time()))
                pipe.execute()
                _cb_event("trip")
                log.warning("circuit_breaker.tripped", domain=domain,
                            failures=failures, category=error_category)
        except Exception:
            pass

    def get_stats(self) -> dict:
        """Return all open circuits for monitoring dashboard."""
        r = self._get_redis()
        if not r:
            return {}
        try:
            keys = r.keys(f"{self.key_prefix}*:state")
            stats = {}
            for key in keys:
                domain = key.replace(self.key_prefix, "").replace(":state", "")
                state  = r.get(key)
                failures = r.get(self._key(domain, "failures")) or "0"
                stats[domain] = {"state": state, "failures": int(failures)}
            return stats
        except Exception:
            return {}


# ─── Domain Rate Limiter ──────────────────────────────────────────────────────

class DomainRateLimiter:
    """
    Token-bucket rate limiter per domain — prevents hammering a portal with
    too many concurrent requests, which causes IP bans and 429 errors.

    For 10,000+ URL runs, without rate limiting, 32 workers might all hit
    dtvp.de simultaneously with 200 requests in 10 seconds — triggering a ban.

    Stored in Redis as a simple counter with TTL.
    Falls back gracefully (allows request) if Redis is unavailable.
    """

    def __init__(
        self,
        max_concurrent: int = 3,       # max simultaneous requests per domain
        window_seconds:  int = 30,      # rolling window
        key_prefix:      str = "vrl:",  # Redis key namespace
    ):
        self.max_concurrent = max_concurrent
        self.window_seconds = window_seconds
        self.key_prefix     = key_prefix
        self._redis: object | None = None

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis as _redis
                from app.config import settings
                self._redis = _redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def acquire(self, domain: str) -> bool:
        """
        Attempt to acquire a slot for this domain.
        Returns True (allowed) or False (rate-limited — caller should back off).
        """
        r = self._get_redis()
        if not r:
            return True  # graceful degradation
        try:
            key = f"{self.key_prefix}{domain}"
            current = r.incr(key)
            if current == 1:
                r.expire(key, self.window_seconds)
            allowed = current <= self.max_concurrent
            if not allowed:
                _rl_hit()
            return allowed
        except Exception:
            return True

    def release(self, domain: str) -> None:
        """Release a slot (decrement counter)."""
        r = self._get_redis()
        if not r:
            return
        try:
            key = f"{self.key_prefix}{domain}"
            r.decr(key)
        except Exception:
            pass


# ─── URL Pre-Validator ────────────────────────────────────────────────────────

def prevalidate_url_batch(urls: list[str]) -> dict[str, dict]:
    """
    Fast pre-validation of a batch of URLs before queuing.
    Returns per-URL metadata: type, platform, expected_success_rate, skip_reason.

    Used by the job submission endpoint to:
    - Warn about auth-gated URLs before starting
    - Sort by expected success (high-probability first)
    - Deduplicate identical URLs
    """
    from app.phase3_integration.platform_classifier import classify_url as clf_url

    seen: set[str] = set()
    results: dict[str, dict] = {}

    for url in urls:
        if url in seen:
            results[url] = {"duplicate": True, "skip_reason": "duplicate URL in batch"}
            continue
        seen.add(url)

        url_type = classify_url_type(url)
        platform = clf_url(url)
        success_rate = URL_TYPE_SUCCESS_RATE.get(url_type, 0.35)

        skip_reason: str | None = None
        if url_type in (UrlType.NETSERVER_AUTH, UrlType.EVERGABE_DEEP, UrlType.EVA_PORTAL):
            skip_reason = (
                f"URL type '{url_type.value}' requires vendor login — "
                "expect ~5% success rate. Only CUA can attempt visual login."
            )

        results[url] = {
            "url_type":           url_type.value,
            "platform":           platform,
            "expected_success":   success_rate,
            "skip_reason":        skip_reason,
            "strategy_order":     [s.value for s in get_strategy_order(url_type, platform)],
        }

    return results


# ─── Singleton instances (shared across pipeline calls in one worker) ─────────

circuit_breaker   = CircuitBreaker(failure_threshold=5, reset_timeout=1800)
rate_limiter      = DomainRateLimiter(max_concurrent=4, window_seconds=30)
