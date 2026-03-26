# Vergabepilot.AI Research Notes

## 🛠️ Environment & Infrastructure

- **Target OS**: macOS (Silicon/Intel support via Homebrew).
- **Python Version**: **3.11.15**. This version is mandatory for compatibility with the latest `browser-use` and `playwright` packages.
- **Unified Venv**: All project components (Scraper v5 and CUA Agents) now share a single root-level `.venv`.
  - **Path**: `/Users/siddharthpatni/Project-Pilot/.venv`
  - **Dependencies**: Managed via root `requirements.txt`.
- **API Management**: Credentials (like `OPENROUTER_API_KEY`) are stored in a root `.env` file, handled via `python-dotenv`.

## 🤖 Browser-Use 0.12.5 Transition

Moving to version 0.12.5 required several breaking changes to be addressed:

### 1. API Structure Changes
- **Obsolete `BrowserConfig`**: The `BrowserConfig` class has been removed from the main export. Configuration is now passed directly as keyword arguments to the `Browser` (BrowserSession) constructor (e.g., `Browser(headless=True)`).
- **Stop vs Close**: The `.close()` method has been replaced by `.stop()`. Using `.close()` results in an `AttributeError`.

### 2. LLM Adapter Migration
`browser-use` 0.12.5 has moved away from direct LangChain support for its internal Agent logic.
- **Problem**: `ChatOpenAI` from `langchain_openai` lacks the `provider` attribute expected by the `Agent`.
- **Solution**: Use native `browser-use` adapters. For OpenRouter, use:
  ```python
  from browser_use.llm.openrouter.chat import ChatOpenRouter
  llm = ChatOpenRouter(model="google/gemini-2.5-flash", api_key=api_key)
  ```

## 📁 Download & Verification Strategy

### 1. Persistent Storage
- **Directory**: `Project-Pilot/cua/downloads/`
- **Implementation**: Every agent variant (`cua_pure_agent.py`, `Cua_v1.py`, `scraper.py`) is now hardcoded to use this directory for all browser-use downloads. This prevents files from being lost in system temp folders.

### 2. Vision-Based Verification
To ensure high accuracy (as requested by the user), the agent prompts have been updated with a **Visual Verification** requirement:
- **Instruction**: The agent must visually confirm that download links have changed state (e.g., clicked/greyed out) or that a "downloading" indicator appeared on screen before it is allowed to finish the task.
- **Benefit**: Reduces "false positives" where the agent thinks it clicked a button but no download actually occurred.

## 🏗️ 3-Layer Hybrid Scraper Architecture

The system is designed for maximum resilience and cost-efficiency:

1.  **Layer 1: Fast Scraper (Deterministic)**:
    - Uses static CSS/XPath selectors.
    - Highest speed, zero cost.
2.  **Layer 2: Heuristic Scraper (Pattern-Based)**:
    - Scans for German keywords ("Unterlagen", "Download") and interacts with UI elements to "reveal" content.
    - Moderate speed, zero cost.
3.  **Layer 3: CUA Agent (Vision-Based Fallback)**:
    - Autonomous browsing using `browser-use` and Gemini.
    - Handles complex JS navigation, cookie banners, and session timeouts.
    - Low speed, variable cost (OpenRouter tokens).

## 💡 Optimization Tips
- **Model Selection**: `google/gemini-2.5-flash-lite` on OpenRouter is recommended for daily scraping as it is nearly free and highly capable of handling simple navigation.
- **Parallelism**: While Layers 1 and 2 can be parallelized, Layer 3 (CUA) is heavy on system resources (RAM/CPU) and should ideally be run sequentially or with a strict semaphore.