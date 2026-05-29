import json
import os
from typing import Optional, Type
import google.generativeai as genai
from pydantic import BaseModel

from open_scraper_sdk.feedback_loop import run_feedback_loop

class OpenScraperClient:
    """
    Main SDK Orchestrator Client.
    
    Coordinates the safe, self-correcting generation and sandboxed execution 
    of site scrapers, ensuring that extracted data is structured into target
    Pydantic models using client-provided API keys.
    """
    
    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        scraping_api_key: Optional[str] = None,
    ):
        # 1. Resolve keys, preferring explicit parameters over environment variables
        self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
        self.scraping_api_key = scraping_api_key or os.environ.get("SCRAPING_API_KEY")
        
        if not self.gemini_api_key:
            raise ValueError(
                "Gemini API key is required. Pass it in __init__(gemini_api_key='...') "
                "or set the GEMINI_API_KEY environment variable."
            )
            
        genai.configure(api_key=self.gemini_api_key)

    def scrape_and_extract(
        self,
        url: str,
        schema: Type[BaseModel],
        additional_prompt: Optional[str] = None,
        max_iterations: int = 3,
    ) -> BaseModel:
        """
        Runs the advanced self-correcting pipeline:
        1. Invokes the code generation & subprocess sandboxing retry loop.
        2. Formats and validates the scraper's extracted output into the target Pydantic schema.
        
        Args:
            url: Target page to scrape.
            schema: Target Pydantic model class definition.
            additional_prompt: Optional extraction guidelines or criteria.
            max_iterations: Max retry budget for code self-correction.
            
        Returns:
            An instance of the target Pydantic schema containing the parsed data.
        """
        # A. Serialize schema to JSON format so the code generator can align with it
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        
        # B. Run the self-correcting sandboxed feedback loop
        print(f"[{self.__class__.__name__}] Launching advanced self-correcting sandboxed loop for {url}...")
        loop_res = run_feedback_loop(
            url=url,
            gemini_api_key=self.gemini_api_key,
            schema_json=schema_json,
            additional_prompt=additional_prompt or "",
            max_iterations=max_iterations
        )
        
        if not loop_res.success:
            err = (
                loop_res.metrics.error_message 
                if (loop_res.metrics and loop_res.metrics.error_message) 
                else "Unsuccessful scraper execution."
            )
            raise RuntimeError(
                f"Failed to scrape and extract page after {loop_res.iterations} iterations.\n"
                f"Diagnostic details: {err}"
            )
            
        raw_scraped_dict = loop_res.final_output
        print(f"[{self.__class__.__name__}] Scrape successful! Validating extracted fields against Pydantic schema...")
        
        # C. Gemini validation step to guarantee type correctness and schema compliance
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        system_prompt = (
            "You are a schema compliance and structured data validation assistant.\n"
            "Map the raw parsed scraper dictionary to the target JSON schema."
        )
        
        user_message = (
            f"Raw Scraped Dict:\n{json.dumps(raw_scraped_dict, indent=2)}\n\n"
            f"Target Schema:\n{schema_json}"
        )
        
        generation_config = {
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": 0.1
        }
        
        response = model.generate_content(
            contents=[system_prompt, user_message],
            generation_config=generation_config
        )
        
        try:
            validated_json = json.loads(response.text)
            return schema.model_validate(validated_json)
        except Exception as e:
            raise ValueError(
                f"Failed to parse validated output into schema {schema.__name__}.\n"
                f"Validated output: {response.text}\nError: {e}"
            ) from e
