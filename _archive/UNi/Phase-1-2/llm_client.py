import os
import logging
import requests
from typing import Dict, Any, Optional, List

# Attempt to load environment variables from a .env file if the python-dotenv package is installed.
# This ensures that API keys and pricing aren't hardcoded in the codebase.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure basic logging to print INFO level messages and above to the console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BudgetExceededError(Exception):
    """Custom exception raised when the LLM usage exceeds the allocated budget."""
    pass

class OpenRouterClient:
    """
    Wrapper around OpenRouter that exposes a unified interface for multiple LLMs 
    (e.g., OpenAI's GPT, Anthropic's Claude, Google's Gemini, etc.).
    It automatically calculates the cost of each call and tracks the total $ spent 
    against a configurable starting budget (default: $50).
    """
    def __init__(self, budget: Optional[float] = None):
        # 1. Load the OpenRouter API key securely from environment variables
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY environment variable is not set")
            
        # 2. Load the total budget ceiling. If a budget isn't passed directly into the class,
        #    it defaults to reading 'LLM_BUDGET' from .env, or falls back to $50.0.
        env_budget = float(os.getenv("LLM_BUDGET", "50.0"))
        self.budget = budget if budget is not None else env_budget
        
        # 3. Initialize state variables for tracking costs over the lifecycle of this object
        self.total_spent = 0.0
        self.warned_80_percent = False
        self.base_url = "https://openrouter.ai/api/v1"
        
        # 4. Load API pricing per 1,000 tokens from .env
        #    This allows updating costs without changing the Python code when OpenRouter updates pricing.
        self.pricing = {
            "openai/gpt-4o": {
                "prompt": float(os.getenv("PRICE_OPENAI_GPT4O_PROMPT", "0.005")),
                "completion": float(os.getenv("PRICE_OPENAI_GPT4O_COMPLETION", "0.015"))
            },
            "anthropic/claude-3-opus": {
                "prompt": float(os.getenv("PRICE_ANTHROPIC_CLAUDE3_PROMPT", "0.015")),
                "completion": float(os.getenv("PRICE_ANTHROPIC_CLAUDE3_COMPLETION", "0.075"))
            },
            "google/gemini-1.5-pro": {
                "prompt": float(os.getenv("PRICE_GOOGLE_GEMINI_PROMPT", "0.0035")),
                "completion": float(os.getenv("PRICE_GOOGLE_GEMINI_COMPLETION", "0.0105"))
            },
        }
        # Fallback pricing if the user requests an unknown model
        self.default_pricing = {
            "prompt": float(os.getenv("PRICE_DEFAULT_PROMPT", "0.001")),
            "completion": float(os.getenv("PRICE_DEFAULT_COMPLETION", "0.002"))
        }

    def _calculate_cost(self, model: str, usage: Dict[str, int]) -> float:
        """
        Internal helper method to calculate the dollar cost of a specific API call 
        based on the number of prompt and completion tokens used.
        """
        # Get the specific rates for the requested model, or use defaults
        rates = self.pricing.get(model, self.default_pricing)
        
        # Extract token counts safely (defaulting to 0 if missing)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        # Calculate final cost by dividing tokens by 1,000 since prices are per 1k tokens
        cost = (prompt_tokens / 1000.0) * rates["prompt"] + (completion_tokens / 1000.0) * rates["completion"]
        return cost

    def _check_budget(self):
        """
        Internal budget guard:
        - Warns the user in the logs when 80% of the total budget is reached.
        - Triggers a HARD STOP (raises an exception) if 100% of the budget is reached.
        """
        # Hard stop condition: Throw an error if total spent has reached or exceeded the ceiling
        if self.total_spent >= self.budget:
            logger.error(f"HARD STOP: Budget of ${self.budget:.2f} exceeded. Total spent: ${self.total_spent:.4f}")
            raise BudgetExceededError(f"Budget of ${self.budget:.2f} exceeded. Total spent: ${self.total_spent:.4f}")
            
        # Warning condition: Log exactly once when crossing the 80% threshold
        if not self.warned_80_percent and self.total_spent >= (self.budget * 0.8):
            logger.warning(f"BUDGET WARNING: 80% of budget reached. Total spent: ${self.total_spent:.4f} / ${self.budget:.2f}")
            self.warned_80_percent = True

    def generate(self, model: str, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """
        Public method to generate a response from a given LLM model through OpenRouter.
        
        Args:
            model (str): The OpenRouter model ID string (e.g., 'openai/gpt-4o').
            messages (list): A list of message dictionaries [{"role": "user", "content": "..."}].
            **kwargs: Any additional OpenRouter/OpenAI parameters (temperature, max_tokens, etc.).
            
        Returns:
            Dict: The raw JSON response dictionary from OpenRouter.
        """
        # 1. Ensure we haven't already blown the budget before making the network request
        self._check_budget()
        
        # 2. Setup the authentication headers required by OpenRouter
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 3. Assemble the HTTP JSON payload dynamically
        payload = {
            "model": model,
            "messages": messages,
            **kwargs
        }
        
        # 4. Make the HTTP POST request to the OpenRouter chat completions endpoint
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status() # Raises an exception for 4xx or 5xx status codes
            data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise

        # 5. Extract the token usage from the response and calculate the exact dollar cost
        usage = data.get("usage", {})
        cost = self._calculate_cost(model, usage)
        
        # 6. Update the cumulative spend tracker and log the event
        self.total_spent += cost
        logger.info(f"API Call Cost: ${cost:.6f} | Total Spent: ${self.total_spent:.4f} | Model: {model}")
        
        # 7. Check the budget again to log a warning if this specific call pushed us over the 80% mark.
        #    If this call pushed us completely over 100%, we catch the exception so we can still return 
        #    the data we just paid for, but the NEXT call will trigger the Hard Stop.
        try:
            self._check_budget()
        except BudgetExceededError:
            pass 
            
        return data
