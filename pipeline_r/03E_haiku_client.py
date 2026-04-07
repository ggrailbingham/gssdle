"""
haiku_client.py — Thin wrapper around the Anthropic Messages API.

All pipeline modules import call_haiku() rather than constructing
requests directly, so model/version/retry logic lives in one place.
"""

import json
import time
import anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds, doubles each retry


def call_haiku(
    system_prompt: str,
    user_message: str,
    max_tokens: int = MAX_TOKENS,
    expect_json: bool = True,
) -> dict | str:
    """
    Call Haiku with a system + user message.

    If expect_json=True (default), parses and returns the response as a dict/list.
    If expect_json=False, returns the raw text string.

    Raises on non-retryable errors; retries on rate limits and transient failures.
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            raw_text = response.content[0].text

            if not expect_json:
                return raw_text

            # Strip markdown fences if present
            clean = raw_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]  # drop ```json line
                clean = clean.rsplit("```", 1)[0]  # drop closing fence
            return json.loads(clean.strip())

        except json.JSONDecodeError as e:
            raise ValueError(
                f"Haiku returned non-JSON response:\n{raw_text}\n\nError: {e}"
            ) from e

        except anthropic.RateLimitError:
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            print(f"  Rate limit hit; retrying in {wait:.0f}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)

        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                print(f"  Server error {e.status_code}; retrying in {wait:.0f}s")
                time.sleep(wait)
            else:
                raise