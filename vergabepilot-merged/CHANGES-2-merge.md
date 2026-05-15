# MERGE NOTES — Dev Branch + Route-Learning Concept

This patch merges two streams of work into the main backend without
changing the architecture from `ARCHITECTURE.md`:

1. **The development-branch standalone tool** (`Vergabepilot-v1-development.zip`).
   A battle-tested CLI scraper with ~89% success rate across 100+ German
   procurement domains. It contributed: a deterministic platform classifier,
   a Playwright wrapper tuned for German portals, and a corpus of platform-
   specific scraping knowledge.

2. **The "Learn Route" implementation plan**. Before generating a scraper,
   visit the URL with a real browser, trace the click path to the documents,
   and pass that verified route to the LLM. Replaces "let the LLM guess
   the navigation" with "let the LLM implement a verified click sequence."

## What changed in the cascade

Old cascade (per `ARCHITECTURE.md`):

    MANUAL → EXISTING → LLM_GENERATED → CUA

New cascade:

    MANUAL → EXISTING → DETERMINISTIC → LLM_GENERATED → CUA
                          ▲                  ▲
                          │                  └─ route-guided when possible
                          └─ DTVP/Satellite/VMPSatellite direct ZIP URL

`DETERMINISTIC` is a new strategy that runs the dev-branch classifier and,
for known templated platforms (DTVP family), constructs the ZIP URL
directly and `requests.get`s it. No LLM, no Playwright. This is the
fast path the dev branch used to handle a large share of its dataset.

`LLM_GENERATED` is unchanged in spirit but smarter:
- Pre-flight calls `route_learner.learn_route()` to trace the navigation.
- The platform classifier runs in parallel.
- Both feed into the generator's prompt — `route_map` provides the exact
  click sequence; `platform` provides the dev-branch's hard-won navigation
  hints for that portal family.

## New files

| Path | Purpose |
|------|---------|
| `app/core/browser_session.py` | Playwright wrapper from dev branch (German locale, cookie banner removal, `find_zip_or_download_all`). Used by the route learner and available to generated scrapers. |
| `app/phase3_integration/platform_classifier.py` | URL + HTML fingerprinting for DTVP, NetServer, evergabe.de, evergabe-online, subreport, deutsche-evergabe, bi-medien, vergabe24, SharePoint, Ariba. Builds DTVP ZIP URLs deterministically. |
| `app/phase3_integration/deterministic.py` | The new "no LLM" strategy. Classifies → builds URL → streams the file. |
| `app/phase1_llm_scraper/route_learner.py` | Opens the URL with Playwright, scores nav candidates by German keywords, clicks the most promising, returns a `RouteMap` describing the verified path. |
| `tests/test_platform_classifier.py` | 22 tests pinning the classifier behaviour from the dev branch's 100-domain dataset. |
| `tests/test_route_and_deterministic.py` | 15 tests covering the deterministic strategy (HTTP mocked) and route learner (BrowserSession mocked). |

## Modified files

### `app/phase1_llm_scraper/prompts.py`
Added 9 platform-specific hint blocks from the dev branch's proven prompts
(NetServer, evergabe.de, evergabe-online, subreport, deutsche-evergabe,
bi-medien, vergabe24, SharePoint, Ariba). Added a new
`build_route_guided_prompt()` template that gets used when the route
learner found documents — the LLM is told to follow the exact sequence
rather than guess.

### `app/phase1_llm_scraper/generator.py`
`generate()` now accepts `route_map: RouteMap | None` and
`platform: str | None`. When `route_map.learned is True`, the
route-guided prompt is used. When `platform` is known but `route_map`
is empty, platform-specific hints still get appended to the plain
prompt. The `GeneratedScraper` dataclass now carries `route_used: bool`
so the registry can record how the code was produced.

### `app/phase1_llm_scraper/feedback_loop.py`
Threaded `route_map` and `platform` through to the first generation
call. Subsequent regeneration calls use the feedback prompt unchanged.

### `app/phase3_integration/pipeline.py`
- Added `_try_deterministic` strategy runner.
- `_try_llm_generated` now calls `learn_route()` + `classify_url()`
  before the LLM and passes both into the feedback loop.
- The cascade list grew to include `Strategy.DETERMINISTIC` in the
  right position.

### `app/phase3_integration/scraper_registry.py`
`upsert_from_generation()` now takes `platform` and `route_used` and
writes them to the new columns on `ScraperTemplate`.

### `app/phase3_integration/fallback.py`
Cascade order is now a single ordered list (`CASCADE_ORDER`) instead of
hardcoded if/elif chains, so adding strategies is a one-line change.

### `app/models.py`
- Added `Strategy.DETERMINISTIC = "deterministic_template"`.
- Added `ScraperTemplate.platform` (nullable string) and
  `ScraperTemplate.route_used` (bool).

### `app/schemas.py`
Added `LearnRouteRequest`, `RouteStepRead`, `RouteMapRead`,
`LearnRouteResponse` for the new endpoint. Added `platform` and
`route_used` to `ScraperTemplateRead`.

### `app/api/routes_scrapers.py`
Added `POST /api/scrapers/learn`: a synchronous endpoint that learns
the route, classifies the platform, runs the LLM, validates the output,
and saves the result to the registry. The frontend "Learn Route" button
from the implementation plan calls this.

### `app/config.py`
Added `enable_route_learning: bool = True` and
`route_learning_max_clicks: int = 2`. Both can be overridden via env.

## What survives unchanged

- `ARCHITECTURE.md` — every module is still in the layout the doc shows.
  Phase 1 / Phase 2 / Phase 3 boundaries are intact. `phase3_integration`
  is still the only place that orchestrates strategies.
- All previously fixed bugs (executor downloads survive, sandbox imports,
  storage resilience, enum value handling). Those are preserved.
- The 17 original tests all still pass.

## How a request flows now

`POST /api/jobs` with a DTVP URL:

1. Pipeline tries MANUAL → no manual scraper hits → fail.
2. Tries EXISTING → no registry entry for this domain → fail.
3. Tries **DETERMINISTIC** → classifier says `dtvp` → builds
   `…/Vergabeunterlagen_<ID>.zip` → `requests.get` → done.
4. The downstream `LLM_GENERATED` and `CUA` strategies never run.
5. Cost: $0, time: ~1s.

`POST /api/jobs` with an unknown German portal:

1. MANUAL, EXISTING, DETERMINISTIC all fail.
2. **LLM_GENERATED**:
   - Classifier returns `unknown` or a non-deterministic platform.
   - `learn_route()` opens the URL with Playwright, finds the
     "Vergabeunterlagen herunterladen" button is the right next step,
     records the selector, finds the resulting downloads.
   - Generator gets the route → produces a scraper that hardcodes
     "click `button:has-text('Vergabeunterlagen herunterladen')`".
   - Sandbox runs it → real downloads land in `output_dir` → persisted
     → registry promoted with `route_used=True`.
3. Next request for the same domain hits EXISTING and skips everything else.

`POST /api/scrapers/learn` for an arbitrary URL:

Same as the LLM_GENERATED branch above but exposed as an explicit
endpoint, so a developer can pre-seed the registry for a new portal
before any real job lands on it.

## Verification

- All 55 tests pass (17 originals + 38 new).
- End-to-end pipeline run with a mocked LLM completes successfully on
  a NetServer URL: platform hint is spliced into the prompt, scraper
  produces files, files survive, registry is upserted with
  `platform="netserver"`.
- FastAPI app loads cleanly with 20 endpoints including the new
  `POST /api/scrapers/learn`.

## Known limitations

- The route learner needs Playwright installed in the worker image
  (already a requirement for the rest of Phase 1/2). Set
  `ENABLE_ROUTE_LEARNING=false` to skip it (e.g. in unit-test
  environments where Playwright isn't available).
- `POST /api/scrapers/learn` is synchronous and can take 30-60 seconds.
  For high-volume use, wrap it in a Celery task; for now it matches
  the implementation plan's spec.
- The 9 platform hint blocks cover the largest dev-branch portals but
  not all 100+. The plain prompt still applies to the long tail.
