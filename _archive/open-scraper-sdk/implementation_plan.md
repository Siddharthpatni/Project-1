# Implementation Plan: Generalizing Vergabepilot Scraping Engine into a Public SDK

This plan outlines how to port the full, advanced scraping architecture from `vergabepilot-ai` (including AST validation, sandboxed execution, and the self-correcting LLM feedback loop) into the standalone **`open-scraper-sdk`** package, while removing all procurement/German-specific traces to make it a general-purpose, open-source web scraping SDK.

---

## 🔒 User Review Required

> [!IMPORTANT]
> **IP Isolation & Traces Removal**: We will completely strip out the custom knowledge lists for German portals (evergabe, DTVP, NetServer, subreport, etc.). The new module will be purely generic, prompting the LLM based on standard HTML/JS structure.
> 
> **Sandbox Dependability**: The subprocess sandbox utilizes `resource` (Unix-only limits) and standard `subprocess` execution. It requires the host system to have Python and relevant libraries (e.g. `requests`, `playwright`, `beautifulsoup4`) installed to run sandboxed scripts that require them.

---

## 🏗️ Proposed Architecture & Changes

We will port and adapt 5 main components from the private codebase into the public SDK directory `scripts/open-scraper-sdk/src/open_scraper_sdk/`:

```
+-----------------------------------------------------------------------------------+
|                              open-scraper-sdk                                     |
+-----------------------------------------------------------------------------------+
|  [OpenScraperClient] (Orchestrator)                                               |
|          |                                                                        |
|          v                                                                        |
|  [run_feedback_loop]  <===================> [ScraperGenerator]                    |
|          |                                    (LLM code generator)                |
|          | (AST Validation)                                                       |
|          v                                                                        |
|  [validate] (AST check)                                                           |
|          |                                                                        |
|          v (Execute code)                                                         |
|  [run_script] (Subprocess Sandbox)                                                |
|          |                                                                        |
|          v (Evaluate Output)                                                      |
|  [evaluate]  (If fails, error -> generator to try again)                          |
+-----------------------------------------------------------------------------------+
```

---

## 📁 Proposed File Modifications

### 1. 📄 `pyproject.toml`
Add dependencies for Playwright and Beautifulsoup, which generated scrapers will frequently use.
- **Path**: `[pyproject.toml](file:///Users/siddharthpatni/vergabepilot-ai/scripts/open-scraper-sdk/pyproject.toml)`

### 2. [NEW] 📄 `sandbox.py`
Port the cross-platform subprocess sandbox (`core.sandbox.py`) that strips secret environmental variables, applies CPU/memory caps via UNIX resource limits, and manages PYTHONPATH.
- **Path**: `[sandbox.py](file:///Users/siddharthpatni/vergabepilot-ai/scripts/open-scraper-sdk/src/open_scraper_sdk/sandbox.py)`

### 3. [NEW] 📄 `validator.py`
Port AST (Abstract Syntax Tree) validator (`phase1_llm_scraper/validator.py`) to prevent dangerous code calls (like `subprocess.Popen`, `eval`, `socket.socket`) before execution.
- **Path**: `[validator.py](file:///Users/siddharthpatni/vergabepilot-ai/scripts/open-scraper-sdk/src/open_scraper_sdk/validator.py)`

### 4. [NEW] 📄 `prompts.py`
Create generic prompt templates for scraping *any website* and extracting *any custom structure*, eliminating all tender-related guidelines.
- **Path**: `[prompts.py](file:///Users/siddharthpatni/vergabepilot-ai/scripts/open-scraper-sdk/src/open_scraper_sdk/prompts.py)`

### 5. [NEW] 📄 `feedback_loop.py` & `evaluator.py`
Create a generalized self-correction loop that spawns the generator, runs the sandbox, parses the output JSON, checks for code failures/exceptions, and feeds diagnostics back to Gemini to self-correct up to a specified retry budget.
- **Path**: `[feedback_loop.py](file:///Users/siddharthpatni/vergabepilot-ai/scripts/open-scraper-sdk/src/open_scraper_sdk/feedback_loop.py)`
- **Path**: `[evaluator.py](file:///Users/siddharthpatni/vergabepilot-ai/scripts/open-scraper-sdk/src/open_scraper_sdk/evaluator.py)`

### 6. 📄 `client.py` & `__init__.py`
Upgrade the client to support the full feedback loop, sandbox execution, and structured extraction in one simple call: `client.scrape_and_extract(url, schema, max_iterations=3)`.
- **Path**: `[client.py](file:///Users/siddharthpatni/vergabepilot-ai/scripts/open-scraper-sdk/src/open_scraper_sdk/client.py)`

---

## 🧪 Verification Plan

### Automated Tests
1. **AST Validation Test**: Run `validator.py` against valid and invalid code snippets (e.g. scripts attempting `os.system` or `eval`) to confirm security blocks work.
2. **Sandbox Spawning Test**: Verify `sandbox.py` successfully runs a basic script inside the restricted subprocess environment.
3. **Orchestrator Execution**: Run the updated `examples/demo.py` to confirm the client generates a scraper, validates it, executes it, self-corrects if needed, and successfully formats the output matching the custom Pydantic schema.

### Manual Verification
1. Inspect generated files in `scripts/open-scraper-sdk/` to ensure no traces of Vergabepilot, German language, or procurement logic remain.
