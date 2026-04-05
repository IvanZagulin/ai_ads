"""Tests for LLM module: prompt building, response parsing (valid, invalid, partial), error handling."""
from __future__ import annotations

import json
import pytest

from app.llm.prompt_builder import PromptBuilder
from app.llm.response_parser import ResponseParser
from app.schemas.schemas import VALID_ACTION_TYPES


# ---------------------------------------------------------------------------
# PromptBuilder tests
# ---------------------------------------------------------------------------
class TestPromptBuilder:
    @pytest.fixture
    def builder(self) -> PromptBuilder:
        return PromptBuilder()

    def test_basic_prompt_contains_required_sections(self, builder: PromptBuilder) -> None:
        prompt = builder.build_analysis_prompt(
            campaign_data={"name": "Test", "platform": "wildberries"},
        )
        assert "CAMPAIGN DATA" in prompt
        assert "RESPONSE FORMAT" in prompt
        assert "CONSTRAINTS" in prompt
        assert "Test" in prompt

    def test_prompt_includes_rules(self, builder: PromptBuilder) -> None:
        rules = [
            {
                "rule_name": "CTR threshold",
                "rule_description": "Lower bids on CTR < 0.5%",
                "rule_params_json": {"min_ctr": 0.5},
            }
        ]
        prompt = builder.build_analysis_prompt(
            campaign_data={"name": "Test"},
            rules=rules,
        )
        assert "OPTIMIZATION RULES" in prompt
        assert "CTR threshold" in prompt
        assert "min_ctr" in prompt

    def test_prompt_includes_history(self, builder: PromptBuilder) -> None:
        history = [
            {
                "action_type": "raise_bid",
                "parameters": {"keyword_id": 1, "change_pct": 5},
                "result": "Improved CTR by 15%",
            }
        ]
        prompt = builder.build_analysis_prompt(
            campaign_data={"name": "Test"},
            history=history,
        )
        assert "DECISION HISTORY" in prompt
        assert "raise_bid" in prompt
        assert "Improved CTR" in prompt

    def test_prompt_for_ozon_warnings(self, builder: PromptBuilder) -> None:
        prompt = builder.build_analysis_prompt(
            campaign_data={"name": "Ozon Campaign"},
            platform="ozon",
        )
        assert "Only Wildberries supports minus-words" in prompt

    def test_prompt_system_instruction(self, builder: PromptBuilder) -> None:
        assert "expert advertising campaign analyst" in builder.SYSTEM_INSTRUCTION.lower()


# ---------------------------------------------------------------------------
# ResponseParser tests
# ---------------------------------------------------------------------------
class TestResponseParser:
    @pytest.fixture
    def parser(self) -> ResponseParser:
        return ResponseParser()

    def test_valid_json_response(self, parser: ResponseParser) -> None:
        raw = json.dumps(
            {
                "actions": [
                    {
                        "action_type": "raise_bid",
                        "reasoning": "High CTR, low position",
                        "keyword_id": 1,
                        "current_value": 10.0,
                        "new_value": 11.0,
                        "step_percent": 10.0,
                    }
                ]
            }
        )
        actions = parser.validate_and_parse(raw)
        assert len(actions) == 1
        assert actions[0]["action_type"] == "raise_bid"
        assert "reasoning" in actions[0]

    def test_valid_json_with_multiple_actions(self, parser: ResponseParser) -> None:
        raw = json.dumps({
            "actions": [
                {
                    "action_type": "raise_bid",
                    "reasoning": "Good keyword",
                    "current_value": 10.0,
                    "new_value": 11.0,
                },
                {
                    "action_type": "minus_word",
                    "reasoning": "Irrelevant traffic",
                    "campaign_id": 1,
                    "minus_text": "-бесплатно",
                },
            ]
        })
        actions = parser.validate_and_parse(raw)
        assert len(actions) == 2
        assert actions[0]["action_type"] == "raise_bid"
        assert actions[1]["action_type"] == "minus_word"

    def test_json_with_markdown_code_blocks(self, parser: ResponseParser) -> None:
        raw = '```json\n{"actions": [{"action_type": "lower_bid", "reasoning": "bad ctr"}]}\n```'
        actions = parser.validate_and_parse(raw)
        assert len(actions) == 1
        assert actions[0]["action_type"] == "lower_bid"

    def test_json_with_markdown_no_language(self, parser: ResponseParser) -> None:
        raw = '```\n{"actions": [{"action_type": "increase_budget", "reasoning": "high roas"}]}\n```'
        actions = parser.validate_and_parse(raw)
        assert len(actions) == 1
        assert actions[0]["action_type"] == "increase_budget"

    def test_partial_json_from_braces(self, parser: ResponseParser) -> None:
        """When response has extra text, parser finds JSON by brace matching."""
        raw = "Here is the analysis:\n\n{'actions': [{'action_type': 'raise_bid', 'reasoning': 'good'}]}"
        # Single quotes need to be handled
        raw_double = raw.replace("'", '"')
        actions = parser.validate_and_parse(raw_double)
        assert len(actions) == 1

    def test_invalid_action_type_raises_error(self, parser: ResponseParser) -> None:
        raw = json.dumps({
            "actions": [
                {"action_type": "delete_campaign", "reasoning": "bad"}
            ]
        })
        with pytest.raises(ValueError, match="Invalid action_type"):
            parser.validate_and_parse(raw)

    def test_missing_action_type_raises_error(self, parser: ResponseParser) -> None:
        raw = json.dumps({"actions": [{"reasoning": "no type"}]})
        with pytest.raises(ValueError, match="Invalid action_type"):
            parser.validate_and_parse(raw)

    def test_negative_value_is_clamped(self, parser: ResponseParser) -> None:
        raw = json.dumps({
            "actions": [
                {
                    "action_type": "raise_bid",
                    "reasoning": "test",
                    "current_value": 10.0,
                    "new_value": -5.0,
                    "step_percent": -10.0,
                }
            ]
        })
        actions = parser.validate_and_parse(raw)
        assert actions[0]["new_value"] == 0
        assert actions[0]["step_percent"] == 0

    def test_step_percent_capped_at_20(self, parser: ResponseParser) -> None:
        raw = json.dumps({
            "actions": [
                {
                    "action_type": "raise_bid",
                    "reasoning": "test",
                    "current_value": 10.0,
                    "new_value": 50.0,
                    "step_percent": 50.0,
                }
            ]
        })
        actions = parser.validate_and_parse(raw)
        assert actions[0]["step_percent"] == 20.0

    def test_budget_change_capped_at_30(self, parser: ResponseParser) -> None:
        raw = json.dumps({
            "actions": [
                {
                    "action_type": "increase_budget",
                    "reasoning": "test",
                    "budget_change_percent": 50.0,
                    "current_value": 100.0,
                    "new_value": 150.0,
                }
            ]
        })
        actions = parser.validate_and_parse(raw)
        assert actions[0]["budget_change_percent"] == 30.0

    def test_empty_actions_list(self, parser: ResponseParser) -> None:
        raw = json.dumps({"actions": []})
        actions = parser.validate_and_parse(raw)
        assert actions == []

    def test_top_level_must_be_object(self, parser: ResponseParser) -> None:
        """Root must be an object with 'actions' key, not a bare array."""
        raw = json.dumps([{"action_type": "raise_bid", "reasoning": "test"}])
        with pytest.raises(ValueError, match="Expected a JSON object"):
            parser.validate_and_parse(raw)

    def test_all_valid_action_types_are_recognized(self, parser: ResponseParser) -> None:
        """All defined action types in VALID_ACTION_TYPES should be accepted."""
        for action_type in VALID_ACTION_TYPES:
            raw = json.dumps({
                "actions": [
                    {"action_type": action_type, "reasoning": "test"}
                ]
            })
            actions = parser.validate_and_parse(raw)
            assert len(actions) == 1
            assert actions[0]["action_type"] == action_type

    def test_auto_added_reasoning(self, parser: ResponseParser) -> None:
        raw = json.dumps({
            "actions": [{"action_type": "raise_bid"}]
        })
        actions = parser.validate_and_parse(raw)
        assert "reasoning" in actions[0]
        assert len(actions[0]["reasoning"]) > 0
