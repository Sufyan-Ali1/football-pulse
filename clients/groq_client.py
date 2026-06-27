"""
Rotating Groq client.

Reads API keys from environment (.env-loaded) using:
GROQ_API_KEY plus any numbered variants like GROQ_API_KEY_1, GROQ_API_KEY_2, etc.

Key selection strategy:
  - Each request starts on a random available key
  - On 429 per-minute rate limit: try another key
  - On 429 tokens-per-day exhaustion: cool that key down for the reported wait time
  - On 400 organization_restricted: cool that key down for 2h
  - On 401 invalid auth/api key: cool that key down for 24h
  - Retries until all available keys are exhausted
"""
import logging
import os
import random
import re
import time

from openai import AuthenticationError, BadRequestError, OpenAI, RateLimitError
from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.groq.com/openai/v1"
_RESTRICTED_COOLDOWN = 2 * 60 * 60
_TPD_COOLDOWN_DEFAULT = 2 * 60 * 60
_INVALID_KEY_COOLDOWN = 24 * 60 * 60


def _parse_retry_seconds(message: str) -> float | None:
    m = re.search(r"try again in (\d+)m([\d.]+)s", message)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.search(r"try again in ([\d.]+)s", message)
    if m:
        return float(m.group(1))
    return None


def _load_keys() -> list[str]:
    def _sort_key(name: str) -> tuple[int, int]:
        if name == "GROQ_API_KEY":
            return (0, 0)
        match = re.fullmatch(r"GROQ_API_KEY_(\d+)", name)
        if match:
            return (1, int(match.group(1)))
        return (2, 0)

    keys: list[str] = []
    seen: set[str] = set()
    candidate_names = sorted(
        (
            name
            for name in settings.GROQ_API_KEYS
            if name == "GROQ_API_KEY" or re.fullmatch(r"GROQ_API_KEY_\d+", name)
        ),
        key=_sort_key,
    )
    for name in candidate_names:
        key = settings.GROQ_API_KEYS.get(name, "")
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


class RotatingGroqClient:
    """Drop-in wrapper around Groq's OpenAI-compatible client with key rotation."""

    def __init__(self) -> None:
        self._keys = _load_keys()
        if not self._keys:
            raise RuntimeError("No GROQ_API_KEY found in environment")
        self._clients = [OpenAI(api_key=key, base_url=_BASE_URL) for key in self._keys]
        self._restricted: dict[int, float] = {}
        logger.info("RotatingGroqClient: %d key(s) loaded", len(self._keys))

    def _available(self) -> list[int]:
        now = time.monotonic()
        recovered = [index for index, until in self._restricted.items() if now >= until]
        for index in recovered:
            del self._restricted[index]
            logger.info("Groq key %d restriction lifted - back in rotation", index + 1)
        return [index for index in range(len(self._keys)) if index not in self._restricted]

    class _CompletionsProxy:
        def __init__(self, parent: "RotatingGroqClient") -> None:
            self._parent = parent

        def create(self, **kwargs):
            available = self._parent._available()
            if not available:
                raise RuntimeError("All Groq keys are rate-limited, invalid, or restricted")

            indices = available.copy()
            random.shuffle(indices)

            last_error = None
            for idx in indices:
                try:
                    return self._parent._clients[idx].chat.completions.create(**kwargs)
                except RateLimitError as exc:
                    last_error = exc
                    message = str(exc)
                    if "tokens per day" in message:
                        wait = _parse_retry_seconds(message) or _TPD_COOLDOWN_DEFAULT
                        self._parent._restricted[idx] = time.monotonic() + wait
                        logger.warning(
                            "Groq key %d daily token limit hit - cooling down for %.0fs, trying another",
                            idx + 1,
                            wait,
                        )
                    else:
                        logger.warning("Groq key %d hit rate limit - trying another", idx + 1)
                    time.sleep(0.3)
                except BadRequestError as exc:
                    if "organization_restricted" in str(exc):
                        self._parent._restricted[idx] = time.monotonic() + _RESTRICTED_COOLDOWN
                        logger.warning(
                            "Groq key %d org-restricted - cooling down for 2h, trying another",
                            idx + 1,
                        )
                        last_error = exc
                    else:
                        raise
                except AuthenticationError as exc:
                    self._parent._restricted[idx] = time.monotonic() + _INVALID_KEY_COOLDOWN
                    logger.warning(
                        "Groq key %d invalid/auth failed - cooling down for 24h, trying another",
                        idx + 1,
                    )
                    last_error = exc

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
