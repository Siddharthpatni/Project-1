# Cascade Pipeline — Vergabepilot.AI

## Overview

The cascade pipeline is the core engine of Vergabepilot.AI. For every procurement notice URL, it tries up to 5 strategies in order, stopping as soon as one succeeds. Each stage is cheaper and faster than the next; expensive AI stages are only used as a last resort.

```
Existing Cached → Deterministic → LLM Generated → CUA Agent → Manual Scraper
     ↓ fast              ↓ free         ↓ LLM           ↓ visual      ↓ legacy
     ms                 seconds        10–45s          30–120s       5–45s
```

---

## Full Pipeline Flow

```mermaid
flowchart TD
    START([URL Submitted to Job]) --> LOCK{Domain Lock?}
    LOCK -- already processing this domain --> WAIT[Wait for lock release]
    WAIT --> TRY
    LOCK -- free --> TRY

    TRY --> S1{Strategy 1<br/>Existing Cached Scraper}
    S1 -- found in registry --> RUN1[Run saved scraper code<br/>in sandbox]
    RUN1 --> V1{Documents?}
    V1 -- yes --> SUCCESS

    V1 -- no --> S2
    S1 -- not found --> S2{Strategy 2<br/>Deterministic Template}
    S2 -- DTVP / NetServer / Satellite --> D2[Build direct download URL<br/>stream ZIP]
    D2 --> V2{ZIP valid?}
    V2 -- yes --> SUCCESS
    V2 -- no --> S3
    S2 -- other portal --> S3

    S3{Strategy 3<br/>LLM Scraper Generation}
    S3 --> G3[LLM reads portal HTML<br/>generates Playwright code]
    G3 --> SBX3[Sandboxed execution<br/>timeout=45s]
    SBX3 --> V3{Documents?}
    V3 -- yes --> SAVE[Save to registry] --> SUCCESS
    V3 -- no, retries left --> FB3[LLM Feedback Loop<br/>with error context]
    FB3 --> SBX3
    V3 -- retries exhausted --> S4

    S4{Strategy 4<br/>Computer Use Agent}
    S4 --> CUA[Visual browser session<br/>screenshot + click loop]
    CUA --> V4{Documents?}
    V4 -- yes --> HINT[Store CUA trace as hint] --> SUCCESS
    V4 -- no --> S5

    S5{Strategy 5<br/>Manual Phase 0 Scraper}
    S5 -- domain has manual scraper --> RUN5[Run pre-written script]
    RUN5 --> V5{Documents?}
    V5 -- yes --> SUCCESS
    V5 -- no --> FAIL
    S5 -- no manual scraper --> FAIL

    SUCCESS([Download Documents<br/>Validate + Store to MinIO<br/>Update JobItem: success]) --> EXTRACT[Trigger Deep Extraction]
    FAIL([Mark JobItem: failed<br/>Classify error category<br/>Write audit event])
```

---

## Strategy 1 — Existing Cached Scraper

**Cost:** Free (no LLM call)  
**Speed:** Milliseconds to seconds  
**File:** `app/phase3_integration/scraper_registry.py`

The fastest path. When a scraper was previously generated and saved for this domain, it is loaded and run again immediately. The registry checks PostgreSQL for a `ScraperTemplate` row by domain.

```mermaid
flowchart LR
    URL --> LOOKUP[Registry lookup by domain]
    LOOKUP -- found --> LOAD[Load Python code]
    LOAD --> SBX[Sandboxed execution]
    SBX -- downloaded files --> VALID[Validate magic bytes]
    VALID --> STORE[Store to MinIO]
    LOOKUP -- not found --> NEXT[Next strategy]
```

**Registry update rules:**
- `success_count` incremented on each successful run
- `failure_count` incremented on failure
- `avg_runtime` updated with exponential moving average
- Scrapers with `failure_count / (success_count + failure_count) > 0.8` are deprioritised

---

## Strategy 2 — Deterministic Template

**Cost:** Free (no LLM call)  
**Speed:** 2–10 seconds  
**File:** `app/phase3_integration/deterministic.py`

For known platform families where the download URL can be constructed directly from the notice URL using a template. No scraping needed — just a direct HTTP download.

```mermaid
flowchart LR
    URL --> PCF[Platform Classifier]
    PCF -- DTVP / Satellite --> TMPL[URL Template Builder]
    PCF -- NetServer --> NS[NetServer API call]
    TMPL --> DL[Stream download with<br/>chunk validation]
    NS --> DL
    DL -- 200 OK + valid content --> STORE[Store ZIP]
    DL -- 404 / HTML --> NEXT[Next strategy]
```

**Supported platforms:**

| Platform | Detection | Template |
|---|---|---|
| DTVP / Satellite | URL contains `dtvp.de/Satellite` | `{base}/de/documents` → ZIP |
| NetServer | URL hostname in NetServer registry | API endpoint construction |

---

## Strategy 3 — LLM Scraper Generation

**Cost:** ~$0.00001 per URL (Gemini 2.5 Flash Lite)  
**Speed:** 10–45 seconds  
**Files:** `app/phase1_llm_scraper/generator.py`, `executor.py`, `feedback_loop.py`

The LLM reads the portal's HTML structure and generates custom Playwright code to navigate and download documents. A feedback loop retries up to 3 times with full error context.

```mermaid
flowchart TD
    HTML[Fetch portal HTML<br/>+ extract text/links] --> PROMPT[Build LLM prompt<br/>with portal structure + CUA hint]
    PROMPT --> LLM[Gemini 2.5 Flash Lite<br/>via OpenRouter]
    LLM --> CODE[Generated Playwright code]
    CODE --> VAL{Safety validation<br/>SSRF + blocked ops?}
    VAL -- blocked --> FAIL[Skip + error]
    VAL -- passes --> SBX[Sandboxed execution<br/>timeout=45s · memory=512MB]
    SBX --> OUT{Stdout analysis}
    OUT -- documents found --> REGISTER[Save to registry<br/>ScraperTemplate]
    OUT -- error + retries left --> FB[Feedback Loop:<br/>LLM sees full error + code]
    FB --> CODE
    OUT -- retries exhausted --> NEXT[Next strategy]
    REGISTER --> SUCCESS
```

**Feedback loop detail:**

The error context sent back to the LLM includes:
- The original generated code
- The complete stdout/stderr from the failed run
- The exception traceback if any
- The portal URL and detected platform

This allows the LLM to self-diagnose and correct issues like wrong selectors, missing waits, or incorrect download logic.

---

## Strategy 4 — Computer Use Agent (CUA)

**Cost:** ~$0.001–0.05 per session (vision model)  
**Speed:** 30–120 seconds  
**Files:** `app/phase2_cua/browser_agent.py`, `browser_use_agent.py`, `orchestrator.py`

A visual browser automation agent that takes screenshots of the portal and uses a vision LLM to decide what to click. Bypasses portals that resist traditional scraping (heavy JS, CAPTCHA-adjacent flows, session-gated downloads).

```mermaid
flowchart TD
    URL --> AGENT[Dispatch CUA Agent<br/>playwright_cua or browser_use]
    AGENT --> OPEN[Open Chromium browser<br/>navigate to URL]
    OPEN --> SS[Take screenshot]
    SS --> VIS[Vision LLM analyses screenshot<br/>identifies download links / buttons]
    VIS --> ACT{Action}
    ACT -- click button --> CLICK[Playwright click + wait]
    ACT -- follow link --> NAV[Navigate to link]
    ACT -- download detected --> DL[Intercept download]
    CLICK & NAV --> SS
    DL --> VALID[Validate file]
    VALID --> STORE[Store to MinIO]
    AGENT --> HINT[Save CUA trace<br/>as domain hint for future LLM gen]
```

**Agent types:**

| Engine | Technology | Best for |
|---|---|---|
| `playwright_cua` | Raw Playwright + vision LLM | Standard portals, custom flows |
| `browser_use` | browser-use framework | Portals with complex state |

**CUA Hints:** After every CUA run (success or failure), the interaction trace is stored in `ScraperTemplate.cua_hint`. This gives the LLM generator verified navigation knowledge in future scraper generation calls, improving success rates.

---

## Strategy 5 — Manual Phase 0 Scraper

**Cost:** Free  
**Speed:** 5–45 seconds  
**File:** `app/phase0_manual/v1_reference.py`

Pre-written, battle-tested Playwright scripts for high-volume domains that are too complex or auth-gated for generated scrapers. These scripts are maintained manually and have the highest reliability.

```mermaid
flowchart LR
    URL --> CHECK{Manual scraper<br/>for this domain?}
    CHECK -- yes --> RUN[Run v1_reference.py<br/>Playwright script]
    RUN --> DWNLD[Priority: Download All button<br/>→ ZIP links → scored docs]
    DWNLD --> VALID[Magic byte validation]
    VALID --> STORE[Store to MinIO]
    CHECK -- no --> FAIL[Classify failure]
```

**Priority order inside manual scraper:**
1. "Download All" button → downloads complete ZIP
2. Individual ZIP download links
3. Scored document links (PDFs ranked by relevance)
4. Button `onclick` handlers
5. NetServer URL recovery from tender IDs

---

## Error Classification

When all strategies fail, the failure is classified into one of 27 categories for analytics:

```mermaid
mindmap
  root((Failure Categories))
    Infrastructure
      timeout
      network
      dns
      ssl
      redirect_loop
      encoding_error
    Security / Validation
      code_validation
      prompt_injection
      blocked_url
      sandbox
    Access / Auth
      login_required
      registration_required
      auth
    Bot Protection
      captcha
    HTTP Errors
      not_found
      rate_limit
      server_error
    Tender Lifecycle
      expired
      maintenance
    Scraper Content
      js_required
      empty_page
      scraper_crash
    Documents / Storage
      no_documents
      storage
    Pipeline
      no_strategy
      loop_exhausted
      unknown
```

---

## Self-Healing Mechanism

For **moderate-risk errors** (timeout, network, empty_page, js_required), the pipeline attempts automatic recovery before escalating:

```mermaid
flowchart LR
    ERR[Strategy Failed] --> CLASS{Error category}
    CLASS -- critical: injection, SSRF --> ABORT[Abort entire job]
    CLASS -- high: auth, captcha --> SKIP[Skip to next strategy]
    CLASS -- moderate: timeout, network --> HEAL{Self-heal attempt}
    HEAL -- add wait, retry headers --> RETRY[Retry same strategy]
    RETRY -- success --> SUCCESS
    RETRY -- fails again --> SKIP
```

---

## Deep Extraction (Post-Download)

After documents are stored, deep extraction runs automatically:

```mermaid
flowchart LR
    DOCS[Downloaded PDFs / ZIPs / DOCX] --> PARSE[Parse text<br/>PDF · DOCX · XLSX]
    PARSE --> REGEX[Regex field extraction<br/>50+ German procurement patterns]
    REGEX --> LLM[Gemini enhancement<br/>22 structured fields]
    LLM --> MERGE[Merge results<br/>LLM wins on specificity]
    MERGE --> DB[Save ExtractionRecord<br/>to PostgreSQL]
    DB --> REPORT[Generate PDF / DOCX report<br/>on demand]
```

**Extracted fields:** `vergabenummer`, `ted_reference`, `auftraggeber`, `vergabestelle`, `titel`, `vergabeverfahren`, `auftragsart`, `veroeffentlichungsdatum`, `abgabefrist`, `bindefrist`, `cpv_codes`, `nuts_codes`, `auftragswert`, `waehrung`, `leistungsort`, `laufzeit`, `ansprechpartner`, `email`, `telefon`, `fax`, `zuschlagskriterien`, `eignungskriterien`
