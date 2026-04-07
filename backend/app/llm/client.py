from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic, APIError, APIConnectionError, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """LLM client using Anthropic SDK with claudehub.fun proxy."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url or settings.CLAUDE_API_BASE
        self.api_key = api_key or settings.CLAUDE_API_KEY
        self.model = model or settings.CLAUDE_MODEL
        self.max_retries = max_retries

        self._client = AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=0,
        )

    async def analyze(self, prompt: str) -> dict[str, Any]:
        """Send a prompt to the LLM and return parsed JSON response."""
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                message = await self._client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=(
                        "You are an expert advertising campaign manager. "
                        "Always respond with valid JSON only. No markdown, no explanation. "
                        "Return a single JSON object with the key 'actions' containing "
                        "an array of action objects."
                    ),
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                )

                content = message.content[0].text if message.content else ""
                if not content:
                    raise ValueError("LLM returned empty response")

                return json.loads(content)

            except (APIConnectionError, TimeoutError) as exc:
                last_error = exc
                logger.warning(
                    "LLM connection error (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                await self._backoff(attempt)

            except RateLimitError as exc:
                last_error = exc
                logger.warning(
                    "LLM rate limited (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                await self._backoff(attempt)

            except (APIError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "LLM API error (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                await self._backoff(attempt)

        raise RuntimeError(
            f"LLM analysis failed after {self.max_retries} retries. "
            f"Last error: {last_error}"
        )

    async def _backoff(self, attempt: int) -> None:
        import asyncio

        delay = min(2 ** attempt * 2.0, 30.0)
        await asyncio.sleep(delay)
