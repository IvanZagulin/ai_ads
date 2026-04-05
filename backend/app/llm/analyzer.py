from __future__ import annotations

import logging
from typing import Any

from app.llm.client import LLMClient
from app.llm.prompt_builder import PromptBuilder
from app.llm.response_parser import ResponseParser

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    """Full analysis pipeline: build prompt -> call LLM -> parse -> validate -> return actions."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        prompt_builder: PromptBuilder | None = None,
        response_parser: ResponseParser | None = None,
    ) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.response_parser = response_parser or ResponseParser()

    async def analyze_campaign(
        self,
        campaign_data: dict[str, Any],
        rules: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        platform: str = "wildberries",
    ) -> list[dict[str, Any]]:
        """Run the full analysis pipeline for a single campaign.

        Returns a list of validated action dicts ready for execution.
        """
        logger.info(
            "Starting analysis for campaign '%s' on platform '%s'",
            campaign_data.get("name", "unknown"),
            platform,
        )

        prompt = self.prompt_builder.build_analysis_prompt(
            campaign_data=campaign_data,
            rules=rules,
            history=history,
            platform=platform,
        )

        logger.debug("Prompt built (%d chars), sending to LLM", len(prompt))
        raw_response = await self.llm_client.analyze(prompt)
        logger.info("LLM response received (%d chars)", len(str(raw_response)))

        raw_text = str(raw_response)
        actions = self.response_parser.validate_and_parse(raw_text)

        logger.info(
            "Analysis complete: %d validated actions for campaign '%s'",
            len(actions),
            campaign_data.get("name", "unknown"),
        )

        return actions
