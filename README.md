# Vergabepilot.AI: Agentic AI for Automated Public Project Scraping

Welcome to the **Vergabepilot.AI** repository, a project created in cooperation with the digitecstudieren.de Machine Learning and Cognitive Software (CORE) Research Group. The objective of this project is to explore both standard automation and advanced Agentic AI approaches for interacting with and scraping German public procurement (tender) websites.

This project is divided into two primary exploration fields based on the Hackathon and Final Week goals.

---

## 📂 Project Structure

The repository is modularised into two distinct directories representing the evolution of our approaches:

### 1. `scraper/` (Hackathons 1)
This directory contains the foundational scraping tools, focusing on parsing and extracting structured data directly from URL endpoints. 
- **Phase 1 (Manual Scraping):** Uses raw browser automation (Playwright) and XPath selectors to manually extract fields from over 25 unique German procurement portal frontends. No LLMs are used here to provide a baseline.
- **Phase 2 (LLM-Assisted Scraping):** Replaces handcrafted text selectors with OpenRouter API calls (various LLMs) capable of reading the raw text of complex webpages and returning valid JSON metadata schemas. Includes robust proxy bypass and URL recovery tactics.

*See the `scraper/README.md` for dedicated instructions on running the Python scraping batch jobs.*

### 2. `cua/` (Final Week Goals)
This directory focuses on the implementation and experimentation with **Computer-Use Agents (CUAs)**.
As scraping individual URLs becomes harder due to advanced anti-bot protections, this workspace explores GUI-driven agents that interact dynamically with the tender websites to:
- Authenticate and traverse portals.
- Autonomously discover and download deeply-nested procurement documents.
- Compare reliability and performance against the traditional Phase 1 & 2 manual automation.

---

## 🎯 Final Week Objectives

As outlined in the `Vergabepilot_AI_Week_Goals.pdf`, our ultimate task is to:
1. Research and set up different GUI / Computer-Use Agents (CUAs).
2. Establish a browser environment for the agents to run experiments.
3. Conduct **Document Downloading** experiments using a manually annotated test dataset.
4. Compare agent limitations and behaviors directly to the deterministic approaches found in the `scraper/` module.
