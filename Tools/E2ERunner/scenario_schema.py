from __future__ import annotations

from typing import Any, Mapping, Sequence

TERMINATION_MODES = ("keep_running", "close_game", "close_editor")
SUPPORTED_INTENT = "defeat_monster"
SUPPORTED_SELECTOR_TYPE = "forward_cone"
SUPPORTED_TARGET_KIND = "monster"


def validate_scenario(scenario: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    if not isinstance(scenario, Mapping):
        return ["scenario must be a mapping"]

    require_keys(
        scenario,
        (
            "schema_version",
            "source_text",
            "language",
            "intent",
            "weapon",
            "target_selector",
            "success_criteria",
            "failure_criteria",
            "termination",
        ),
        "scenario",
    )

    if scenario.get("schema_version") != 1:
        errors.append("scenario.schema_version must be 1")

    if not isinstance(scenario.get("source_text"), str) or not str(scenario.get("source_text")).strip():
        errors.append("scenario.source_text must be a non-empty string")

    if scenario.get("language") not in {"ko", "en", "mixed", "unknown"}:
        errors.append("scenario.language must be one of ko, en, mixed, unknown")

    if scenario.get("intent") != SUPPORTED_INTENT:
        errors.append(f"scenario.intent must be {SUPPORTED_INTENT}")

    if not isinstance(scenario.get("weapon"), str) or not str(scenario.get("weapon")).strip():
        errors.append("scenario.weapon must be a non-empty string")

    target_selector = scenario.get("target_selector")
    if isinstance(target_selector, Mapping):
        require_keys(
            target_selector,
            ("type", "relative_to", "yaw_degrees", "target_kind"),
            "scenario.target_selector",
        )
        if target_selector.get("type") != SUPPORTED_SELECTOR_TYPE:
            errors.append(f"scenario.target_selector.type must be {SUPPORTED_SELECTOR_TYPE}")
        if target_selector.get("relative_to") != "player_forward":
            errors.append("scenario.target_selector.relative_to must be player_forward")
        if target_selector.get("target_kind") != SUPPORTED_TARGET_KIND:
            errors.append(f"scenario.target_selector.target_kind must be {SUPPORTED_TARGET_KIND}")
        yaw_degrees = target_selector.get("yaw_degrees")
        if not isinstance(yaw_degrees, (int, float)) or isinstance(yaw_degrees, bool):
            errors.append("scenario.target_selector.yaw_degrees must be a number")
        elif not (0 < float(yaw_degrees) <= 180):
            errors.append("scenario.target_selector.yaw_degrees must be in (0, 180]")
    else:
        errors.append("scenario.target_selector must be an object")

    success_criteria = scenario.get("success_criteria")
    if isinstance(success_criteria, Mapping):
        require_keys(success_criteria, ("timeout_seconds", "target_state"), "scenario.success_criteria")
        timeout_seconds = success_criteria.get("timeout_seconds")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
            errors.append("scenario.success_criteria.timeout_seconds must be a number")
        elif not (1 <= float(timeout_seconds) <= 3600):
            errors.append("scenario.success_criteria.timeout_seconds must be in [1, 3600]")
        if success_criteria.get("target_state") != "defeated":
            errors.append("scenario.success_criteria.target_state must be defeated")
    else:
        errors.append("scenario.success_criteria must be an object")

    failure_criteria = scenario.get("failure_criteria")
    if isinstance(failure_criteria, Mapping):
        require_keys(
            failure_criteria,
            ("target_lost_timeout_seconds", "input_failure_limit"),
            "scenario.failure_criteria",
        )
        target_lost_timeout_seconds = failure_criteria.get("target_lost_timeout_seconds")
        if not isinstance(target_lost_timeout_seconds, (int, float)) or isinstance(target_lost_timeout_seconds, bool):
            errors.append("scenario.failure_criteria.target_lost_timeout_seconds must be a number")
        elif not (1 <= float(target_lost_timeout_seconds) <= 120):
            errors.append("scenario.failure_criteria.target_lost_timeout_seconds must be in [1, 120]")
        input_failure_limit = failure_criteria.get("input_failure_limit")
        if not isinstance(input_failure_limit, int) or isinstance(input_failure_limit, bool):
            errors.append("scenario.failure_criteria.input_failure_limit must be an integer")
        elif not (1 <= input_failure_limit <= 10):
            errors.append("scenario.failure_criteria.input_failure_limit must be in [1, 10]")
    else:
        errors.append("scenario.failure_criteria must be an object")

    termination = scenario.get("termination")
    if isinstance(termination, Mapping):
        require_keys(termination, ("mode",), "scenario.termination")
        if termination.get("mode") not in TERMINATION_MODES:
            errors.append("scenario.termination.mode must be keep_running, close_game, or close_editor")
    else:
        errors.append("scenario.termination must be an object")

    return errors

