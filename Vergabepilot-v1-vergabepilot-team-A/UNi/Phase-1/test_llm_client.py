import os
import unittest
from unittest.mock import patch, MagicMock
from llm_client import OpenRouterClient, BudgetExceededError

# ── Fake pricing data (same format as OpenRouter's /api/v1/models response) ──
# Prices are per SINGLE token (not per 1k).  We use these in every test
# so that cost assertions are deterministic and don't depend on the live API.
MOCK_PRICING = {
    "openai/gpt-4o": {
        "prompt": 0.0000025,       # $2.50 per 1M tokens
        "completion": 0.00001,     # $10.00 per 1M tokens
    },
}


class TestOpenRouterClient(unittest.TestCase):
    """
    Test suite for the OpenRouterClient wrapper.
    Uses 'unittest.mock' to intercept network calls so that we can safely 
    test our cost logic and budget limits without spending real money.
    """

    @patch.object(OpenRouterClient, '_fetch_live_pricing', return_value=MOCK_PRICING)
    def setUp(self, _mock_pricing):
        # 1. Setup a dummy testing environment before every test runs.
        #    We inject a fake API key so the initialization logic succeeds.
        #    _fetch_live_pricing is mocked so no real HTTP call is made during init.
        os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-test-key-for-unit-tests"
        self.client = OpenRouterClient(budget=50.0)

    def test_api_key_loading(self):
        """Verifies that the API key from environment variables is properly loaded."""
        self.assertEqual(self.client.api_key, "sk-or-v1-test-key-for-unit-tests")

    @patch('llm_client.requests.post')
    def test_successful_generation_and_cost_logging(self, mock_post):
        """
        Simulates a successful generation request and verifies that
        the cost is accurately calculated and added to the total_spent tracker.
        """
        # 1. Create a fake response object that OpenRouter would normally return
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1000}
        }
        mock_response.raise_for_status.return_value = None
        
        # 2. Tell the mocked 'requests.post' to return our fake response
        mock_post.return_value = mock_response

        # 3. Perform the actual test call
        model = "openai/gpt-4o"
        messages = [{"role": "user", "content": "Hi"}]
        response = self.client.generate(model, messages)
        
        # 4. Verify the output structure is intact
        self.assertIn("choices", response)
        self.assertEqual(response["choices"][0]["message"]["content"], "Hello!")
        
        # 5. Verify the mathematical cost logic (per-token pricing from MOCK_PRICING)
        #    prompt:     1000 tokens × $0.0000025  = $0.0025
        #    completion: 1000 tokens × $0.00001    = $0.01
        #    total = $0.0125
        self.assertAlmostEqual(self.client.total_spent, 0.0125)

    @patch('llm_client.requests.post')
    def test_budget_warning_at_80_percent(self, mock_post):
        """
        Simulates the client reaching the 80% budget threshold ($40 out of $50)
        and verifies that it properly logs a warning message.
        """
        # 1. Artificially inflate the total spent tracker to just under the warning line
        self.client.total_spent = 39.99
        
        # 2. Setup a mock response that will push the budget over $40.00
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Warning test"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1000}
            # cost = $0.0125 (from MOCK_PRICING above)
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # 3. Patch the internal logger so we can spy on it
        with patch('llm_client.logger.warning') as mock_warning:
            self.client.generate("openai/gpt-4o", [{"role": "user", "content": "test"}])
            
            # The total spent becomes 39.99 + 0.0125 = 40.0025 (which is > 40.0)
            # 4. Verify that the logger warning was triggered exactly once
            mock_warning.assert_called_once()
            
            # 5. Verify the internal flag flipped to True to avoid spamming the log in the future
            self.assertTrue(self.client.warned_80_percent)

    def test_hard_stop_at_100_percent(self):
        """
        Verifies the hard stop mechanism. If the budget is fully exhausted,
        it should immediately throw a BudgetExceededError and completely block the request.
        """
        # 1. Exhaust the budget
        self.client.total_spent = 50.0
        
        # 2. Ensure that making another call correctly raises the exception
        with self.assertRaises(BudgetExceededError):
            self.client.generate("openai/gpt-4o", [{"role": "user", "content": "This should fail"}])

if __name__ == '__main__':
    unittest.main()
