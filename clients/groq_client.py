"""
Rotating Groq client.

Reads up to 5 API keys from settings (GROQ_API_KEY, GROQ_API_KEY_2 ... GROQ_API_KEY_5).
When a request hits a 429 rate-limit error, it automatically switches to the next
key and retries — no manual intervention needed.
"""
import logging
import os
import time

from openai import OpenAI, RateLimitError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.groq.com/openai/v1"


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
    Exposes .chat.completions.create() with automatic key rotation on 429.
    """

    def __init__(self) -> None:
        self._keys = _load_keys()
        if not self._keys:
            raise RuntimeError("No GROQ_API_KEY found in environment")
        self._index = 0
        self._clients = [OpenAI(api_key=k, base_url=_BASE_URL) for k in self._keys]
        logger.info("RotatingGroqClient: %d key(s) loaded", len(self._keys))

    def _current(self) -> OpenAI:
        return self._clients[self._index]

    def _rotate(self) -> bool:
        next_index = (self._index + 1) % len(self._keys)
        if next_index == self._index:
            return False
        logger.warning(
            "Groq key %d hit rate limit — rotating to key %d",
            self._index + 1, next_index + 1,
        )
        self._index = next_index
        return True

    class _CompletionsProxy:
        def __init__(self, parent: "RotatingGroqClient") -> None:
            self._parent = parent

        def create(self, **kwargs):
            attempts = len(self._parent._keys)
            last_error = None
            for _ in range(attempts):
                try:
                    return self._parent._current().chat.completions.create(**kwargs)
                except RateLimitError as e:
                    last_error = e
                    rotated = self._parent._rotate()
                    if not rotated:
                        break
                    time.sleep(1)
            raise last_error

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
