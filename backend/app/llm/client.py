from __future__ import annotations

import json
import logging
import time
from typing import Any

from anthropic import Anthropic

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """LLM client using Anthropic SDK with claudehub.fun proxy.

    Uses sync streaming API because the proxy returns SSE events
    that AsyncAnthropic cannot parse.
    """

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

        self._client = Anthropic(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    async def analyze(self, prompt: str) -> dict[str, Any]:
        """Send a prompt to the LLM and return parsed JSON response."""
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                full_text = ""

                with self._client.messages.stream(
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
                ) as stream:
                    for text in stream.text_stream:
                        full_text += text

                if not full_text:
                    raise ValueError("LLM returned empty response")

                logger.info("LLM response (%d chars): %s", len(full_text), full_text[:300])

                # Try to extract JSON from the response
                try:
                    return json.loads(full_text)
                except json.JSONDecodeError:
                    # Try to find JSON object in the text
                    start = full_text.find("{")
                    end = full_text.rfind("}") + 1
                    if start >= 0 and end > start:
                        return json.loads(full_text[start:end])
                    raise ValueError(
                        f"LLM did not return valid JSON: {full_text[:200]}"
                    )

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM error (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    delay = min(2 ** attempt * 2.0, 30.0)
                    time.sleep(delay)

        raise RuntimeError(
            f"LLM analysis failed after {self.max_retries} retries. "
            f"Last error: {last_error}"
        )
