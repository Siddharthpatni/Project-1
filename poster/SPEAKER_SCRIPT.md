# Vergabepilot.AI — Speaker Script (11 + 4 min)

**Format:** 11 min presentation + 4 min Q&A · DIGIT Review Party #3, Goslar, 3 July 2026
**Deck:** `deck.html` (present in browser — arrow keys / click to advance, `F` for fullscreen) · backup `VergabePilot_Deck.pdf`
**Demo:** slide 7 auto-plays `demo_vergabepilot.mp4`. Have the live app open in a second window as a backup.

**Timing target: 11:00.** Keep an eye on the progress bar at the bottom of the deck.

| # | Slide | Time | Cumulative |
|---|-------|------|-----------|
| 1 | Title | 0:30 | 0:30 |
| 2 | Problem & Motivation | 1:00 | 1:30 |
| 3 | The Idea | 0:45 | 2:15 |
| 4 | System Architecture | 1:15 | 3:30 |
| 5 | Phase 1 — Feedback loop | 2:00 | 5:30 |
| 6 | Phase 2 & 3 | 1:30 | 7:00 |
| 7 | **Demo** | 1:45 | 8:45 |
| 8 | Results | 1:00 | 9:45 |
| 9 | Benchmarking | 0:45 | 10:30 |
| 10 | Roadmap | 0:20 | 10:50 |
| 11 | Team / Thank you | 0:10 | 11:00 |

---

## 1 · Title (0:30)
> "Good [morning]. We're team Vergabepilot — a CORE and CICONIA initiative with TU Clausthal and Babeș-Bolyai. Our project asks a simple question: instead of *writing* a web scraper for every procurement portal, what if the **AI writes, tests and fixes its own scraper**? Let me show you how — and that it costs almost nothing."

Keep it short. Don't read the team names — they're on the slide.

## 2 · Problem & Motivation (1:00)
- Public tenders — *Vergabe* — are published across **hundreds of portals**: DTVP, NetServer, Cosinex, RIB, Subreport, and many more.
- Today, **every new data source needs a scraper built from scratch.** It's slow, it's costly, and it doesn't scale.
- Two extra pains: portals **change** and scrapers silently break; and the **maintenance** burden grows with every source you add.
> "As the number of domains grows, the engineering effort itself becomes the bottleneck. That's the problem we set out to remove."

## 3 · The Idea (0:45)
> "Our core idea: a system that writes, validates, runs and evaluates its **own** scraper for any portal — in a closed loop. When code isn't enough, a visual computer-use agent steps in, and a cost-aware cascade makes sure we only pay for AI when we have to."

This slide sets up the next three. Don't over-explain — the detail comes next.

## 4 · System Architecture (1:15)
Walk the arrows once, left to right:
- **Next.js UI** → **FastAPI** receives a job → it's **enqueued** and fanned out across a **Celery worker pool**, coordinated by **Redis**.
- Each URL is routed through **three phases**: the Phase-1 feedback loop, the Phase-2 CUA agent, and the Phase-3 cascade.
- Output: **documents → MinIO (S3)**, **metadata → Postgres**.
> "Everything you'll see runs through this one pipeline."

## 5 · Phase 1 — Feedback loop (2:00) — *the core, spend time here*
Go agent by agent:
- **Generator** — takes a URL and writes a Python scraper for that domain with an LLM.
- **Validator** — before any code runs, it does an **AST safety check**. This matters: the model writes code, so we statically verify it's safe to execute.
- **Executor** — runs the scraper in a **sandboxed subprocess** with memory and timeout limits.
- **Evaluator** — compares what came back against the expected output and **flags discrepancies**.
> "And here's the key: if the Evaluator isn't happy, that feedback goes **back to the Generator**, which rewrites the scraper. It's a closed generate–validate–execute–evaluate loop that **repairs itself** until it extracts the right documents. A manual engineering task becomes an automated one."

## 6 · Phase 2 & 3 (1:30)
- **Phase 2 — CUA agent (left):** when a generated scraper can't reach the documents — dynamic pages, odd flows — a **computer-use agent navigates the portal like a human** with Playwright. It's powerful but the most expensive path, so it's a *fallback*, not the default.
- **Phase 3 — Cost-aware cascade (right):** for every URL we try the **cheapest viable strategy first** and escalate only on a miss: cached scraper → deterministic template → LLM-generated → CUA → store.
> "This ordering is what keeps the cost down — which you'll see in a second."

## 7 · DEMO (1:45)
Advance to the slide; the video starts automatically (or click it). Narrate over it:
> "This is a real run: **100 procurement URLs, four parallel workers.** Watch each one resolve — you can see the platform it detected: NetServer, DTVP, Cosinex, and so on. … And the summary: **97 of 100 scraped successfully**, 3 had no documents. Total runtime under six minutes. And look at the bottom — only **4 new LLM calls, 75 served from cache**, for a **total cost of two cents.**"

If the video doesn't play, narrate the summary frame (it's the PDF fallback) or switch to the live app.

## 8 · Results (1:00)
Hit the four numbers, let them land:
- **97% success** on the 100-URL benchmark (3 simply had no documents).
- **$0.02** total LLM cost for the whole run — because of caching.
- **5.8 minutes** end-to-end across 4 workers.
- **4 new vs. 75 cached** LLM calls — the cache does the heavy lifting.
> "Without the cache, single-shot regeneration was 87% at 53 cents — so the feedback loop **and** the cache are both doing real work."

## 9 · Benchmarking (0:45)
> "We benchmarked **10 models**. The surprise: the **cheapest and fastest model, Gemini 2.5 Flash Lite, won** — same extraction quality as the big, expensive models, at a fraction of the cost and latency. For this task, bigger did **not** mean better."

## 10 · Roadmap (0:20)
> "Discovery, Phase 1, 2 and 3 are done. We're now on the **final phase** — wiring the frontend to the backend with server-side loading."

## 11 · Team / Thank you (0:10)
> "That's Vergabepilot — self-improving scrapers that turn fragmented portals into reliable, near-zero-cost document discovery. Thank you — happy to take questions."

---

## Q&A prep (4:00) — anticipated questions

**Q: The model generates code that you then execute — isn't that dangerous?**
A: Yes, which is why the **Validator does AST static analysis before execution**, and the **Executor runs in a sandboxed subprocess** with memory and timeout limits. Generated code never runs unchecked.

**Q: What happens with login-gated portals or CAPTCHAs?**
A: Those are genuine walls. The cascade detects them and, rather than failing silently, routes them to the CUA agent or flags them as needing manual action with an explained reason. We don't claim to break authentication.

**Q: Portals change — doesn't the scraper break again?**
A: That's exactly the point of the loop. When a cached scraper stops returning documents, the Evaluator catches it and the Generator **regenerates** — self-healing instead of a human patch.

**Q: Why did the expensive models underperform?**
A: For structured extraction from HTML, capability saturates early; the larger models added latency and cost without better extraction. Some even failed our format/JSON contract. So we pick the smallest model that passes the eval.

**Q: How is "success" measured — what's the ground truth?**
A: The Evaluator compares extracted output against expected outcomes per URL (documents found / fields), which also feeds the annotated dataset we built between the Romania and Goslar weeks.

**Q: Does this generalise beyond Germany?**
A: The pipeline is portal-agnostic — in one run it auto-classified 30+ platform types. The same generate-and-verify approach extends to other countries; that's on the roadmap.

**Q: What does cost look like at 10k or 100k URLs?**
A: Cost scales with **new** domains, not URL count, because of the per-domain cache. Once a domain has a verified scraper, subsequent URLs are near-free — the 4-new-vs-75-cached ratio is the whole story.

**Q: Legal / terms of service?**
A: We focus on **public** tender publications and respect rate limits (per-domain limiting is built in). Productionising would include per-portal ToS review.

---

### Presenter tips
- **Practice the hand-off** if multiple people speak; agree who drives the deck.
- The demo is your strongest 90 seconds — rehearse the narration so you're not just watching the video.
- If you're running long, **compress slides 6, 9 and 10** — protect the loop (5) and the demo (7).
- Keep the live app open as a backup, and pre-load the deck in fullscreen before you start.
