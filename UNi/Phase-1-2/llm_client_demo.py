import os
from llm_client import OpenRouterClient, BudgetExceededError

print("--- OpenRouter LLM Client Demo ---\n")

try:
    # 1. Initialize the OpenRouter wrapper.
    #    Because we don't pass a budget explicitly here, it automatically looks into
    #    your .env file to load the LLM_BUDGET and the OPENROUTER_API_KEY.
    client = OpenRouterClient()
    print(f"Client Initialized. Current Budget: ${client.budget}")

    # 2. Define the messages array exactly as you would for the standard OpenAI API.
    #    This format works universally across GPT, Claude, and Gemini when using OpenRouter.
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Tell me a short joke."}
    ]

    print("\nSending request to OpenRouter (openai/gpt-4o)...")
    
    # 3. Generate the response! 
    #    This method abstracts away the HTTP request and handles cost accounting.
    #    To change the AI, simply change the model string (e.g., 'anthropic/claude-3-opus').
    response = client.generate(model="openai/gpt-4o", messages=messages)
    
    # 4. Print the final text output extracted from the raw JSON response
    print("\n--- LLM RESPONSE ---")
    print(response["choices"][0]["message"]["content"])
    
except BudgetExceededError as e:
    # 5. This block is triggered if the request pushes you over your budget ceiling.
    print(f"\n[Budget Guard] Failed to generate: {e}")
except Exception as e:
    # 6. Catch-all for network issues, invalid API keys, etc.
    print(f"\n[Error] An error occurred: {e}")
    print("\nDid you remember to set your actual OPENROUTER_API_KEY in the .env file?")
