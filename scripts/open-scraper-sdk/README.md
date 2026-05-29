# Open Scraper SDK 🕸️✨

A clean, modular, and self-correcting Python library designed for safe, LLM-powered web scraping and structured data extraction. 

This SDK operates entirely on the client side, allowing developers to supply their **own API keys** (for the Gemini LLM or paid scraping/proxy services) while running untrusted LLM-generated scrapers inside a **restricted subprocess sandbox**.

---

## 🏗️ Architecture Design

The library is split into three decoupled layers to guarantee flexibility, speed, and safety:

```
        +-----------------------------------------------+
        |              Consumer Application             |
        +-----------------------------------------------+
                                |
             1. Supply API Keys | 2. Pass Pydantic Schema
                                v
        +-----------------------------------------------+
        |              OpenScraperClient                |
        +-----------------------------------------------+
                                |
                                v
        +-----------------------------------------------+
        |             Self-Correcting Loop              | <---+ (Retry on error)
        +-----------------------------------------------+     |
             /                  |                  \          |
    (Code Gen)             (AST Guard)          (Sandbox)     |
           /                    |                    \        |
          v                     v                     v       |
+-------------------+ +-------------------+ +-------------------+ |
|  ScraperGenerator | |   Static AST      | | Subprocess      | |
|  (Writes scraper  | |   Validator       | | Sandbox         | |
|   via Gemini)     | | (Blocks dangerous | | (Executes code  | |
|                   | |   system calls)   | |  caps memory)   | |
+-------------------+ +-------------------+ +-------------------+ |
                                |                             |
                                +-------[Evaluation]----------+
                                     (If fail -> self-correct)
```

---

## 🔒 Safety and Isolation Features

When executing LLM-generated code, safety is paramount. The SDK implements **two distinct defense fences** before executing any generated script:

### 1. AST Static Verification (`validator.py`)
Before code enters the compiler, the SDK parses the Python script into an **Abstract Syntax Tree (AST)**. It walks the tree and immediately rejects execution if:
- **Disallowed Imports** are present (e.g. `subprocess`, `ctypes`, `socket`, `multiprocessing`).
- **Dangerous Commands** are called (e.g. `eval`, `exec`, `os.system`, `os.popen`, `shutil.rmtree`, `socket.socket`).

### 2. Isolated Subprocess Sandbox (`sandbox.py`)
If static verification passes, the scraper runs in a restricted subprocess:
- **Secret Scrubbing**: All sensitive system variables (like your `AWS_`, `GOOGLE_`, `ANTHROPIC_`, or `DATABASE_URL` configurations) are automatically scrubbed from the subprocess environment so that generated code cannot exfiltrate credentials.
- **Resource Constraints**: Applies address-space memory caps (on Unix/macOS systems) and strict wall-clock timeout thresholds to stop infinite loops or memory leaks immediately.

---

## 📦 Installation

Initialize your virtual environment and install the package along with its runtime requirements:

```bash
# Clone or move this directory
cd open-scraper-sdk

# Install in editable mode along with package dependencies
pip install -e .

# Install Playwright browser binaries (required for JS-heavy web pages)
playwright install chromium
```

---

## 🛠️ Usage Example

Here is how easily a developer can import and consume your library using their **own credentials** and **custom structures**:

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from open_scraper_sdk import OpenScraperClient

# 1. Define YOUR custom Pydantic schema structure
class TechArticle(BaseModel):
    title: str = Field(description="The primary heading or title of the article")
    author: Optional[str] = Field(description="Name of the author, if listed")
    key_takeaways: List[str] = Field(description="Bullet points of the main ideas or conclusions")
    reading_time_minutes: Optional[int] = Field(description="Reading time in minutes, as an integer")

# 2. Instantiate the orchestrator client with your credentials
# (Alternatively, let it fall back to your GEMINI_API_KEY environment variable)
client = OpenScraperClient(
    gemini_api_key="AIzaSyYourGeminiKeyHere",
    scraping_api_key="your_scraper_api_key"  # Optional scraping proxy key
)

# 3. Fetch, write code, run sandbox, self-correct, and parse in a single call!
try:
    result = client.scrape_and_extract(
        url="https://example.com/blog/future-of-ai",
        schema=TechArticle,
        additional_prompt="Focus heavily on extraction of future technological predictions.",
        max_iterations=3  # Sandbox self-correction retry budget
    )
    
    # 4. Interact with the fully typed Pydantic object
    print(f"Parsed Title: {result.title}")
    print(f"Takeaways: {result.key_takeaways}")
    print(f"Reading Time: {result.reading_time_minutes} min")
    
except Exception as e:
    print(f"Scraper execution failed: {e}")
```

---

## 🔄 How the Self-Correcting Loop Works

If a scraper is generated but runs into an exception (e.g. missing elements, broken page structures, or syntax errors):
1. The **Sandbox** intercepts the standard error traceback and returns a detailed diagnostics log.
2. The **Feedback Loop** sends the error trace and previous script attempt back to the Gemini LLM.
3. Gemini **self-corrects** the logic, rewrites the code, and submits it to the validation and sandbox engine again.
4. Once execution succeeds without errors and returns structured data, it is validated and converted into a type-safe object.

---

## 🚢 Publishing to PyPI (Python Package Index)

If you would like to publish this package publicly so that anyone can run `pip install open-scraper-sdk`, use the standard modern Python packaging commands:

```bash
# 1. Install packaging dependencies
pip install build twine

# 2. Compile distribution archives (.whl and .tar.gz)
python -m build

# 3. Validate compiled archives
twine check dist/*

# 4. Upload your package to PyPI (requires PyPI token/credentials)
twine upload dist/*
```

---

## 📄 License

This project is licensed under the **MIT License** — feel free to use and distribute it as you please!
