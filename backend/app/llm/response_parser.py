from __future__ import annotations

import json
import logging
from typing import Any

from app.schemas.schemas import LLMAction, VALID_ACTION_TYPES

logger = logging.getLogger(__name__)


class ResponseParser:
    """Validates and parses raw LLM responses into structured actions."""

    MAX_RETRIES = 3

    def validate_and_parse(self, raw_response: str) -> list[dict[str, Any]]:
        """Validate JSON structure and return list of validated action dicts.

        Retries up to MAX_RETRIES times on invalid response by trying to extract
        a JSON array from the text.
        """
        last_errors: list[str] = []

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                parsed = self._extract_json(raw_response)

                if not isinstance(parsed, dict):
                    raise ValueError(
                        "Expected a JSON object with 'actions' key at root, "
                        f"got {type(parsed).__name__}"
                    )

                actions_raw = parsed.get("actions", [])
                if not isinstance(actions_raw, list):
                    raise ValueError(
                        f"'actions' must be an array, got {type(actions_raw).__name__}"
                    )

                validated_actions: list[dict[str, Any]] = []
                for i, action_dict in enumerate(actions_raw):
                    validated = self._validate_action(action_dict, action_index=i)
                    validated_actions.append(validated)

                if len(validated_actions) > len(actions_raw):
                    logger.warning(
                        "Some actions were corrected during validation. "
                        "Original: %d, Validated: %d",
                        len(actions_raw),
                        len(validated_actions),
                    )

                return validated_actions

            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                error_msg = str(exc)
                last_errors.append(error_msg)
                logger.warning(
                    "Response parsing failed (attempt %d/%d): %s",
                    attempt,
                    self.MAX_RETRIES,
                    error_msg,
                )

                # Attempt recovery on last iteration
                if attempt == self.MAX_RETRIES:
                    recovered = self._try_recovery(raw_response, last_errors)
                    if recovered is not None:
                        return recovered

        raise ValueError(
            f"Unable to parse LLM response after {self.MAX_RETRIES} attempts. "
            f"Errors: {'; '.join(last_errors)}"
        )

    def validate_from_dict(self, parsed: dict[str, Any]) -> list[dict[str, Any]]:
        """Validate actions from an already-parsed dict (bypasses JSON extraction)."""
        actions_raw = parsed.get("actions", [])
        if not isinstance(actions_raw, list):
            raise ValueError(
                f"'actions' must be an array, got {type(actions_raw).__name__}"
            )

        validated_actions: list[dict[str, Any]] = []
        for i, action_dict in enumerate(actions_raw):
            validated = self._validate_action(action_dict, action_index=i)
            validated_actions.append(validated)

        logger.info(
            "Validated %d actions from pre-parsed dict", len(validated_actions)
        )
        return validated_actions

    def _extract_json(self, text: str) -> Any:
        """Try to extract a JSON object from text that may contain markdown or other noise."""
        stripped = text.strip()

        # Direct parse attempt
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # Try to strip markdown code blocks
        if "```" in stripped:
            start = stripped.find("```")
            # Find the language marker end
            start = stripped.find("\n", start)
            if start == -1:
                start = 0
            else:
                start += 1
            end = stripped.rfind("```")
            inner = stripped[start:end].strip()
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass

        # Try to find JSON object by brace matching
        brace_start = stripped.find("{")
        if brace_start != -1:
            brace_end = stripped.rfind("}")
            if brace_end > brace_start:
                candidate = stripped[brace_start : brace_end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

        raise ValueError("Could not extract valid JSON from response")

    def _validate_action(self, action: dict[str, Any], action_index: int = 0) -> dict[str, Any]:
        """Validate a single action dict and return a normalised version."""
        action_type = action.get("action_type", "")
        if action_type not in VALID_ACTION_TYPES:
            raise ValueError(
                f"Invalid action_type '{action_type}' at index {action_index}. "
                f"Must be one of: {', '.join(sorted(VALID_ACTION_TYPES))}"
            )

        # Check for negative numeric values
        for key in ("current_value", "new_value", "step_percent", "budget_change_percent"):
            val = action.get(key)
            if val is not None and val < 0:
                logger.warning(
                    "Action %d (%s): %s cannot be negative (%s), setting to 0",
                    action_index,
                    action_type,
                    key,
                    val,
                )
                action[key] = max(val, 0)

        # Validate step_percent max 20%
        step = action.get("step_percent")
        if step is not None and step > 20:
            logger.warning(
                "Action %d (%s): step_percent %.1f exceeds 20%%, capping",
                action_index,
                action_type,
                step,
            )
            action["step_percent"] = 20.0

        # Validate budget_change_percent max 30%
        budget_pct = action.get("budget_change_percent")
        if budget_pct is not None and budget_pct > 30:
            logger.warning(
                "Action %d (%s): budget_change_percent %.1f%% exceeds 30%%, capping",
                action_index,
                action_type,
                budget_pct,
            )
            action["budget_change_percent"] = 30.0

        # Ensure reasoning exists
        if not action.get("reasoning"):
            action["reasoning"] = f"Auto-generated reasoning for {action_type}"

        return action

    def _try_recovery(
        self, raw_response: str, _errors: list[str]
    ) -> list[dict[str, Any]] | None:
        """Last-ditch effort to salvage actions from a broken response."""
        try:
            parsed = self._extract_json(raw_response)
            if isinstance(parsed, list):
                valid = []
                for i, item in enumerate(parsed):
                    if isinstance(item, dict):
                        try:
                            valid.append(self._validate_action(dict(item), action_index=i))
                        except ValueError:
                            logger.warning("Recovery: skipping invalid action at index %d", i)
                return valid
            if isinstance(parsed, dict) and "actions" in parsed and isinstance(parsed["actions"], list):
                valid = []
                for i, item in enumerate(parsed["actions"]):
                    if isinstance(item, dict):
                        try:
                            valid.append(self._validate_action(dict(item), action_index=i))
                        except ValueError:
                            pass
                return valid
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return None
