# Phase 0 — Manual Scraping Baseline

This phase establishes the "Source of Truth" for the Vergabepilot.AI project. It consists of high-quality, human-written scrapers that serve as the baseline for evaluating Phase 1 (LLM-generated) and Phase 2 (CUA).

## Reference Scraper (V1 Port)

The reference implementation is located at:
[`backend/app/phase0_manual/v1_reference.py`](file:///Users/siddharthpatni/vergabepilot-ai/backend/app/phase0_manual/v1_reference.py)

### Capabilities

1.  **URL Recovery**: Automatically handles expired or obfuscated URLs (specifically for Vergabe24 and Tender24) by attempting to find alternative NetServer endpoints.
2.  **Cookie Handling**: Dismisses common German-language cookie banners to reveal document links.
3.  **Document Scoring**: Uses a ranking system (0-3) based on link text keywords (e.g., *Leistungsbeschreibung*, *LV*, *Unterlagen*) and file extensions.
4.  **Hybrid Download Strategy**:
    - **Primary**: Intercepts Playwright's `expect_download` events after clicking elements.
    - **Secondary**: Falls back to direct `requests` if the UI interaction fails or the file is behind a direct link.
5.  **Deduplication**: Files are deduplicated by name and size to ensure a clean result set.

## Integration

Phase 0 scrapers are registered in the system's **Scraper Registry** (the database) with the source tag `manual`.

During the **Phase 3 Pipeline**, if the system encounters a URL from a domain that has a Phase 0 scraper, it will:
1.  Try the **Existing (Manual) Scraper** first.
2.  Only proceed to Phase 1 generation if the manual scraper fails or doesn't exist for that domain.

## Writing New Phase 0 Scrapers

All scrapers in this project must adhere to the following interface:

```python
def scrape(url: str, output_dir: str) -> list[str]:
    """
    Args:
        url: The absolute target URL of the tender detail page.
        output_dir: The directory where downloaded documents must be saved.
        
    Returns:
        A list of absolute paths to the downloaded files.
    """
    # implementation using playwright.sync_api ...
    return ["/path/to/file1.pdf", "/path/to/file2.zip"]
```

> [!CAUTION]
> **Safety Requirements:** To be compatible with the Phase 1 validator, manual scrapers should avoid `subprocess`, `os.system`, and restricted imports unless explicitly registered as an internal system tool.
