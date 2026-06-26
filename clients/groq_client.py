"""
Rotating Groq client.

Reads API keys from environment (GROQ_API_KEY, GROQ_API_KEY_1 ... GROQ_API_KEY_5).

Key selection strategy:
  - Each request starts on a RANDOM key (spreads load evenly across all keys)
  - On 429 per-minute rate limit: skip that key, try another random available key
  - On 429 tokens-per-day exhaustion: mark key unavailable for the reported wait time
  - On 400 organization_restricted: mark that key dead for 2h, skip it
  - Retries until all available keys are exhausted, then raises
"""
import logging
import os
import random
import re
import time

from openai import OpenAI, RateLimitError, BadRequestError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.groq.com/openai/v1"
_RESTRICTED_COOLDOWN = 2 * 60 * 60   # 2 hours
_TPD_COOLDOWN_DEFAULT = 2 * 60 * 60  # fallback if we can't parse the wait time


def _parse_retry_seconds(message: str) -> float | None:
    """Extract wait duration from Groq error messages like 'try again in 40m27.84s'."""
    m = re.search(r"try again in (\d+)m([\d.]+)s", message)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.search(r"try again in ([\d.]+)s", message)
    if m:
        return float(m.group(1))
    return None


def _load_keys() -> list[str]:
    keys = []
    seen = set()
    for name in ["GROQ_API_KEY", "GROQ_API_KEY_1"]:
        key = os.environ.get(name, "")
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    for i in range(2, 6):
        k = os.environ.get(f"GROQ_API_KEY_{i}", "")
        if k and k not in seen:
            keys.append(k)
            seen.add(k)
    return keys


class RotatingGroqClient:
    """
    Drop-in replacement for OpenAI(api_key=..., base_url=groq).
    Picks a random key per request. Skips rate-limited or restricted keys.
    Restricted keys automatically recover after 2 hours.
    """

    def __init__(self) -> None:
        self._keys = _load_keys()
        if not self._keys:
            raise RuntimeError("No GROQ_API_KEY found in environment")
        self._clients    = [OpenAI(api_key=k, base_url=_BASE_URL) for k in self._keys]
        self._restricted: dict[int, float] = {}  # index → time when cooldown expires
        logger.info("RotatingGroqClient: %d key(s) loaded", len(self._keys))

    def _available(self) -> list[int]:
        now = time.monotonic()
        recovered = [i for i, until in self._restricted.items() if now >= until]
        for i in recovered:
            del self._restricted[i]
            logger.info("Groq key %d restriction lifted — back in rotation", i + 1)
        return [i for i in range(len(self._keys)) if i not in self._restricted]

    class _CompletionsProxy:
        def __init__(self, parent: "RotatingGroqClient") -> None:
            self._parent = parent

        def create(self, **kwargs):
            available = self._parent._available()
            if not available:
                raise RuntimeError("All Groq keys are rate-limited or restricted")

            # Shuffle so every request starts on a different random key
            indices = available.copy()
            random.shuffle(indices)

            last_error = None
            for idx in indices:
                try:
                    return self._parent._clients[idx].chat.completions.create(**kwargs)
                except RateLimitError as e:
                    last_error = e
                    msg = str(e)
                    if "tokens per day" in msg:
                        wait = _parse_retry_seconds(msg) or _TPD_COOLDOWN_DEFAULT
                        self._parent._restricted[idx] = time.monotonic() + wait
                        logger.warning(
                            "Groq key %d daily token limit hit — cooling down for %.0fs, trying another",
                            idx + 1, wait,
                        )
                    else:
                        logger.warning("Groq key %d hit rate limit — trying another", idx + 1)
                    time.sleep(0.3)
                except BadRequestError as e:
                    if "organization_restricted" in str(e):
                        self._parent._restricted[idx] = time.monotonic() + _RESTRICTED_COOLDOWN
                        logger.warning(
                            "Groq key %d org-restricted — cooling down for 2h, trying another",
                            idx + 1,
                        )
                        last_error = e
                    else:
                        raise

            raise last_error or RuntimeError("All Groq keys failed")

    class _ChatProxy:
        def __init__(self, parent: "RotatingGroqClient") -> None:
            self.completions = RotatingGroqClient._CompletionsProxy(parent)

    @property
    def chat(self) -> "_ChatProxy":
        return self._ChatProxy(self)


_client: RotatingGroqClient | None = None


def get_groq_client() -> RotatingGroqClient:
    global _client
    if _client is None:
        _client = RotatingGroqClient()
    return _client
