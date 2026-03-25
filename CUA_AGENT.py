import pandas as pd
import json
import os
from openai import OpenAI
from playwright.sync_api import sync_playwright
import time
from typing import Dict, List, Any
import logging
import re
from datetime import datetime

# Setup robust logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TenderCUAAgent:
    def __init__(self, openai_api_key: str, input_csv_path: str, output_dir: str = "."):
        if not openai_api_key or openai_api_key == "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":
            raise ValueError("Please set valid OPENAI_API_KEY")
        self.client = OpenAI(api_key=openai_api_key)
        self.model = "gpt-4o-mini"
        self.input_csv_path = input_csv_path
        self.output_dir = output_dir
        self.documents = pd.DataFrame()
        self.doc_count = 0
        
        os.makedirs(output_dir, exist_ok=True)
        logger.info("Tender CUA Agent initialized")
        
    def load_documents(self) -> bool:
        """Load CSV with tender website validation."""
        try:
            if not os.path.exists(self.input_csv_path):
                raise FileNotFoundError(f"CSV not found: {self.input_csv_path}")
            
            self.documents = pd.read_csv(self.input_csv_path)
            self.doc_count = len(self.documents)
            
            # Ensure URL column exists
            if 'url' not in self.documents.columns:
                logger.error("No 'url' column found. Expected tender website URLs.")
                return False
            
            self.documents['url'] = self.documents['url'].astype(str)
            logger.info(f"Loaded {self.doc_count} tender websites")
            return True
        except Exception as e:
            logger.error(f"CSV error: {e}")
            return False
    
    def select_documents(self, num_docs: int = 10) -> pd.DataFrame:
        """Select first N tender websites."""
        num_docs = min(num_docs, self.doc_count)
        selected = self.documents.head(num_docs).copy()
        logger.info(f"Selected {len(selected)} tender websites")
        return selected
    
    def extract_tender_info(self, page, url: str) -> Dict[str, Any]:
        """Extract structured tender information using AI + selectors."""
        try:
            # Take screenshot first
            screenshot_path = f"{self.output_dir}/tender_{int(time.time())}.png"
            page.screenshot(path=screenshot_path, full_page=True)
            
            # Common tender selectors
            selectors = [
                "h1, h2, h3",  # Titles
                "[class*='tender'], [class*='bid'], [class*='procurement']",  # Tender keywords
                ".title, .name, .subject",  # Common title classes
                ".deadline, .closing, .end-date",  # Dates
                ".amount, .value, .budget",  # Money
                ".description, .scope, .requirements"  # Content
            ]
            
            # Get visible text from key elements
            page_content = {
                "title": page.title(),
                "url": url,
                "screenshot": screenshot_path,
                "html_head": page.locator("head").inner_text()[:2000],
            }
            
            for selector in selectors:
                try:
                    elements = page.locator(selector).all()
                    if elements:
                        page_content[f"content_{selector[:20]}"] = "\n".join([el.inner_text() for el in elements[:5]])
                except:
                    continue
            
            # AI extraction for perfect structured data
            prompt = f"""
            Extract TENDER details from this webpage content. Return ONLY JSON.
            
            URL: {url}
            Content preview: {page_content.get('content_h1 h2 h3', '')[:3000]}
            
            Required fields:
            {{"tender_id": "ID or reference",
              "title": "Full tender title",
              "issuer": "Authority/organization",
              "deadline": "Closing date (YYYY-MM-DD)",
              "value": "Budget/amount (number or 'N/A')",
              "status": "Open/Closed/Active",
              "description": "Summary (200 words max)",
              "requirements": "Key requirements",
              "documents": "List of attached files",
              "contact": "Contact info",
              "url": "{url}",
              "extraction_confidence": "high/medium/low",
              "screenshot": "{screenshot_path}"
            }}
            """
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0
            )
            
            # Parse AI response
            ai_json = json.loads(response.choices[0].message.content)
            ai_json.update({
                "screenshot": screenshot_path,
                "url": url,
                "timestamp": datetime.now().isoformat()
            })
            
            return ai_json
            
        except Exception as e:
            return {
                "url": url,
                "error": str(e),
                "status": "extraction_failed",
                "timestamp": datetime.now().isoformat()
            }
    
    def process_tenders(self, selected_docs: pd.DataFrame) -> List[Dict]:
        """Process all selected tender websites."""
        results = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, slow_mo=1500)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()
            
            for idx, row in selected_docs.iterrows():
                url = row['url']
                logger.info(f"Processing tender {len(results)+1}/{len(selected_docs)}: {url}")
                
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    time.sleep(5)  # Wait for dynamic content
                    
                    tender_info = self.extract_tender_info(page, url)
                    results.append(tender_info)
                    
                except Exception as e:
                    logger.error(f"Failed {url}: {e}")
                    results.append({"url": url, "error": str(e), "status": "navigation_failed"})
                
                time.sleep(2)
            
            browser.close()
        
        return results
    
    def save_tender_outputs(self, results: List[Dict]):
        """Save PERFECT formatted CSV + JSON."""
        csv_path = os.path.join(self.output_dir, "CUA_AGENT.csv")
        json_path = os.path.join(self.output_dir, "CUA_AGENT.json")
        
        # Normalize for CSV (handle nested data)
        flat_results = []
        for r in results:
            flat = {k: (v if isinstance(v, str) else str(v)) for k, v in r.items()}
            flat_results.append(flat)
        
        # Save CSV with all columns
        df = pd.DataFrame(flat_results)
        df.to_csv(csv_path, index=False, encoding='utf-8')
        
        # Save complete JSON
        full_data = {
            "extraction_date": datetime.now().isoformat(),
            "total_processed": len(results),
            "success_count": len([r for r in results if r.get('status') != 'extraction_failed']),
            "results": results
        }
        
        with open(json_path, "w", encoding='utf-8') as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"Saved {len(results)} tenders → {csv_path}, {json_path}")

def main():
    print("TENDER CUA AGENT - Extract Tender Info from Websites")
    print("=" * 60)
    
    # === CONFIG ===
    API_KEY = "sk-your-openai-api-key-here"  # ← YOUR OPENAI KEY HERE
    INPUT_CSV = r"C:\Users\Victus\Downloads\publications_a.csv"
    OUTPUT_DIR = "./tender_output"
    
    try:
        agent = TenderCUAAgent(API_KEY, INPUT_CSV, OUTPUT_DIR)
    except ValueError as e:
        print(f"❌ {e}")
        return
    
    if not agent.load_documents():
        print("❌ CSV load failed")
        return
    
    print(f"✅ Found {agent.doc_count} tender websites")
    
    # === SELECT HOW MANY ===
    print("\nFirst 10 URLs:")
    preview = agent.documents.head(10)[['url']].to_string(index=False)
    print(preview)
    
    num_tenders = int(input(f"\nProcess first HOW MANY tenders? (1-{agent.doc_count}): "))
    selected = agent.select_documents(num_tenders)
    
    print(f"\n🎯 Processing {len(selected)} tender websites...")
    
    # === EXTRACT ===
    results = agent.process_tenders(selected)
    
    # === SAVE PERFECT FORMAT ===
    agent.save_tender_outputs(results)
    
    print("\n✅ TENDER EXTRACTION COMPLETE!")
    print(f"📁 Output folder: {OUTPUT_DIR}")
    print(f"📊 {len([r for r in results if 'tender_id' in r])} successful extractions")
    print("- CUA_AGENT.csv (Excel-ready table)")
    print("- CUA_AGENT.json (complete data)")
    print("- tender_*.png (screenshots)")

if __name__ == "__main__":
    main()
