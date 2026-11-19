"""LLM Client wrapper for Deal Scout (Gemini)."""
from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

_CLIENT = None
_CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",
    "gemini-1.5-flash",
]


def get_llm_client():
    global _CLIENT
    if _CLIENT is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        from google import genai
        _CLIENT = genai.Client(api_key=api_key)
    return _CLIENT


def call_llm(prompt: str, models: Optional[List[str]] = None) -> str:
    """Call Gemini with fallback model sequence."""
    client = get_llm_client()
    if not client:
        raise RuntimeError("GEMINI_API_KEY not configured in environment or .env")

    models_to_try = models or _CANDIDATE_MODELS
    last_err = None

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if resp.text and resp.text.strip():
                    return resp.text.strip()
            except Exception as e:
                last_err = e
                time.sleep(1)

    raise RuntimeError(f"All Gemini candidate models failed. Last error: {last_err}")
