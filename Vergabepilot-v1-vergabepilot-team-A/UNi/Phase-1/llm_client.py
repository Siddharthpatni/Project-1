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
        
        # 4. Fetch LIVE pricing from OpenRouter's /api/v1/models endpoint.
        #    This ensures we always use the exact current rates — no stale .env values.
        #    The pricing dict maps model_id → {"prompt": rate_per_token, "completion": rate_per_token}.
        self.pricing = self._fetch_live_pricing()

    def _fetch_live_pricing(self) -> Dict[str, Dict[str, float]]:
        """
        Fetches the current per-token pricing for ALL models from OpenRouter's
        public /api/v1/models endpoint.  Prices are returned as floats
        representing USD cost per single token.

        Returns:
            Dict mapping model_id → {"prompt": float, "completion": float}

        If the API call fails (network error, etc.), returns an empty dict
        and logs a warning.  Cost calculation will then fall back to the
        default rate defined in _calculate_cost().
        """
        try:
            response = requests.get(
                f"{self.base_url}/models",
                timeout=10  # Don't hang forever if OpenRouter is slow
            )
            response.raise_for_status()
            data = response.json()

            pricing = {}
            for model in data.get("data", []):
                model_id = model.get("id", "")
                price_info = model.get("pricing", {})

                # OpenRouter returns prices as strings (e.g. "0.0000025"),
                # representing the cost in USD per single token.
                prompt_price = price_info.get("prompt", "0")
                completion_price = price_info.get("completion", "0")

                pricing[model_id] = {
                    "prompt": float(prompt_price),
                    "completion": float(completion_price),
                }

            logger.info(f"Loaded live pricing for {len(pricing)} models from OpenRouter")
            return pricing

        except Exception as e:
            logger.warning(f"Could not fetch live pricing from OpenRouter: {e}. "
                           "Falling back to conservative default rates.")
            return {}

    def _calculate_cost(self, model: str, usage: Dict[str, int]) -> float:
        """
        Calculates the dollar cost of a specific API call based on the
        number of prompt and completion tokens used.

        Uses LIVE pricing fetched from OpenRouter at startup.
        If the model isn't in the pricing dict (e.g. the fetch failed),
        falls back to a conservative default of $0.01 / 1k tokens.

        Note: OpenRouter prices are per SINGLE token, so we multiply
        directly (no division by 1000 needed).
        """
        # Look up the live rates for this specific model
        rates = self.pricing.get(model)

        if rates:
            # Live pricing is per-token — just multiply
            prompt_cost = usage.get("prompt_tokens", 0) * rates["prompt"]
            completion_cost = usage.get("completion_tokens", 0) * rates["completion"]
        else:
            # Fallback: conservative default of $0.01 per 1k tokens
            logger.warning(f"No live pricing found for '{model}', using default rate")
            prompt_cost = usage.get("prompt_tokens", 0) * 0.00001
            completion_cost = usage.get("completion_tokens", 0) * 0.00001

        return prompt_cost + completion_cost

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
