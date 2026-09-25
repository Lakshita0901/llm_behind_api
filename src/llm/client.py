"""
src/llm/client.py
OpenAI-compatible client configured from environment variables.
Swap provider by changing 3 env vars: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
"""
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_base_url = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
_api_key = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "openrouter/auto")

# Explicit 30-second timeout — never rely on the SDK's 10-minute default
client = OpenAI(
    base_url=_base_url,
    api_key=_api_key,
    timeout=30.0,
)
