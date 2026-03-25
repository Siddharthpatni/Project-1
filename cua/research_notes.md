# Computer-Use Agent (CUA) Research Notes

## Overview of Candidate Frameworks

Based on recent developments in open-source agentic AI, several frameworks exist for navigating user interfaces and the web autonomously. For our goal—interacting with German public procurement (tender) websites to find and download documents—we need agents that excel at reading complex DOM structures, bypassing cookie banners, and initiating file downloads.

### 1. Browser-Use (Top Candidate)
- **Description:** A state-of-the-art framework that simplifies web interaction for LLMs. It exposes a powerful Python API for agents to autonomously control browsers, fill forms, and conduct complex research.
- **Pros:** Specifically built for the web; highly active open-source community; natively supports Playwright (which we used in Phase 1); handles dynamic modern web apps excellent; easy integration with Python.
- **Cons:** Limited strictly to the browser (cannot operate desktop apps like Excel or local file managers natively, though we don't need that for this).
- **Suitability:** **High**. Since our objective is to navigate tender portals (web pages) and download documents, this framework is purpose-built for our exact use case.

### 2. OS-Copilot
- **Description:** A generalist OS agent capable of interacting with the web, code terminals, local files, and third-party desktop applications.
- **Pros:** Extremely versatile; can perform data manipulation on the downloaded files locally using the terminal.
- **Cons:** Overkill for purely web-based extraction workflows; heavier setup requirement (often requires sandboxing or dedicated containers).
- **Suitability:** **Medium**. Great if we later need the agent to open the downloaded PDFs, analyze them using a local PDF viewer, and compile reports, but too heavy for just the downloading phase.

### 3. Agent S / CUA (trycua)
- **Description:** Frameworks focused on general GUI automation (clicking and typing on physical desktop screens using Vision-Language Models).
- **Pros:** Truly "computer-use" in that they visually see the screen like a human.
- **Cons:** Slower than DOM-based browser agents; highly token-intensive (requires sending streams of screenshots to Vision models); much higher error rate for precise text targets in dense tables (like procurement portals).
- **Suitability:** **Low to Medium**. While closer to the academic definition of "Computer-Use Agent", Vision-based desktop agents will struggle with the dense, text-heavy nature of German procurement tables compared to DOM-aware agent frameworks.

## Conclusion & Recommendation

For the task of autonomous document downloading from tender websites, **Browser-Use** is the optimal choice. It balances the "agentic" nature of autonomous decision-making with the reliable DOM-parsing capabilities needed to traverse deeply nested procurement HTML structures.
