"""
src/llm/hello.py
Stage 0 throwaway check — verifies the provider is reachable and the key works.
Run with:  python src/llm/hello.py
Expected:  output contains the word "ready"
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.llm.client import client, MODEL

def main():
    print(f"Connecting to model: {MODEL}")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": "Reply with exactly one word: ready",
            }
        ],
        max_tokens=10,
        temperature=0,
    )
    text = response.choices[0].message.content.strip()
    print(f"Model replied: {text!r}")
    if "ready" in text.lower():
        print("✅  Stage 0 checkpoint passed — provider is reachable.")
    else:
        print("⚠️  Response did not contain 'ready'. Check your key/model.")
        sys.exit(1)

if __name__ == "__main__":
    main()
