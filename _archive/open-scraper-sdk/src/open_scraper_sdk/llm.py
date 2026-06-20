import json
from typing import Optional, Type
import google.generativeai as genai
from pydantic import BaseModel

class LLMProcessor:
    """
    LLM extraction processor.
    
    Uses the user-supplied Gemini API key to structure unstructured page text
    into a typed Pydantic object.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Configure the genai client using the user's provided API key
        genai.configure(api_key=self.api_key)

    def extract(
        self,
        text_content: str,
        schema: Type[BaseModel],
        url: str,
        additional_prompt: Optional[str] = None
    ) -> BaseModel:
        """
        Send text content to Gemini, forcing a structured JSON output matching the Pydantic schema.
        """
        # We can use gemini-1.5-flash or gemini-2.5-flash for speed and structured outputs.
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        system_prompt = (
            "You are an expert web scraper and data extraction assistant.\n"
            "Analyze the scraped web content below and extract the requested fields "
            "strictly conforming to the provided JSON schema."
        )
        
        user_message = f"Web content from URL: {url}\n\n"
        if additional_prompt:
            user_message += f"Extraction Rules/Context: {additional_prompt}\n\n"
            
        # Truncate text content safely if it is extremely large (e.g. 50k tokens)
        user_message += f"Scraped Web Content:\n{text_content[:40000]}"
        
        # Configure Gemini generation to return structured JSON adhering to the Pydantic model's schema
        generation_config = {
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": 0.1,  # Lower temperature for deterministic extraction
        }
        
        response = model.generate_content(
            contents=[system_prompt, user_message],
            generation_config=generation_config
        )
        
        # Parse the JSON response back into the Pydantic model
        try:
            parsed_json = json.loads(response.text)
            return schema.model_validate(parsed_json)
        except Exception as e:
            # Fallback or wrap error gracefully
            raise ValueError(
                f"Failed to parse LLM response into schema {schema.__name__}.\n"
                f"Raw response: {response.text}\nError: {e}"
            ) from e
