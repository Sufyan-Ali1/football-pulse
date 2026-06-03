"""
Rotating Groq client.

Reads up to 5 API keys from settings (GROQ_API_KEY, GROQ_API_KEY_2 ... GROQ_API_KEY_5).

Key selection strategy:
  - Each request starts on a RANDOM key (spreads load evenly across all keys)
  - On 429 RateLimitError: skip that key, try another random available key
  - On 400 organization_restricted: mark that key dead for this session, skip it
  - Retries until all available keys are exhausted, then raises
"""
import logging
import os
import random
import time

from openai import OpenAI, RateLimitError, BadRequestError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.groq.com/openai/v1"
_RESTRICTED_COOLDOWN = 2 * 60 * 60   # 2 hours in seconds


def _load_keys() -> list[str]:
    keys = []
    primary = os.environ.get("GROQ_API_KEY", "")
    if primary:
        keys.append(primary)
    for i in range(2, 6):
        k = os.environ.get(f"GROQ_API_KEY_{i}", "")
        if k:
            keys.append(k)
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
                    logger.warning("Groq key %d hit rate limit — trying another", idx + 1)
                    time.sleep(0.5)
                except BadRequestError as e:
                    if "organization_restricted" in str(e):
                        until = time.monotonic() + _RESTRICTED_COOLDOWN
                        self._parent._restricted[idx] = until
                        logger.warning(
                            "Groq key %d restricted — cooling down for 2h, trying another",
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
