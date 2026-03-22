from __future__ import annotations

from typing import Any, Mapping, Sequence

TERMINATION_MODES = ("keep_running", "close_game", "close_editor")
SUPPORTED_DEFEAT_INTENT = "defeat_monster"
SUPPORTED_MOVEMENT_INTENT = "movement_jump_sequence"
SUPPORTED_INTENTS = (SUPPORTED_DEFEAT_INTENT, SUPPORTED_MOVEMENT_INTENT)
SUPPORTED_SELECTOR_TYPE = "forward_cone"
SUPPORTED_TARGET_KIND = "monster"
SUPPORTED_MOVEMENT_COMPLETION_STATE = "sequence_completed"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_common_fields(scenario: Mapping[str, Any], errors: list[str]) -> None:
    if scenario.get("schema_version") != 1:
        errors.append("scenario.schema_version must be 1")

    if not isinstance(scenario.get("source_text"), str) or not str(scenario.get("source_text")).strip():
        errors.append("scenario.source_text must be a non-empty string")

    if scenario.get("language") not in {"ko", "en", "mixed", "unknown"}:
        errors.append("scenario.language must be one of ko, en, mixed, unknown")

    intent = scenario.get("intent")
    if intent not in SUPPORTED_INTENTS:
        errors.append(f"scenario.intent must be one of {', '.join(SUPPORTED_INTENTS)}")

    termination = scenario.get("termination")
    if isinstance(termination, Mapping):
        if "mode" not in termination:
            errors.append("scenario.termination.mode is required")
        elif termination.get("mode") not in TERMINATION_MODES:
            errors.append("scenario.termination.mode must be keep_running, close_game, or close_editor")
    else:
        errors.append("scenario.termination must be an object")


def _validate_defeat_monster_scenario(scenario: Mapping[str, Any], errors: list[str]) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    require_keys(
        scenario,
        ("weapon", "target_selector", "success_criteria", "failure_criteria"),
        "scenario",
    )

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
        if not _is_number(yaw_degrees):
            errors.append("scenario.target_selector.yaw_degrees must be a number")
        elif not (0 < float(yaw_degrees) <= 180):
            errors.append("scenario.target_selector.yaw_degrees must be in (0, 180]")
    else:
        errors.append("scenario.target_selector must be an object")

    success_criteria = scenario.get("success_criteria")
    if isinstance(success_criteria, Mapping):
        require_keys(success_criteria, ("timeout_seconds", "target_state"), "scenario.success_criteria")
        timeout_seconds = success_criteria.get("timeout_seconds")
        if not _is_number(timeout_seconds):
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
        if not _is_number(target_lost_timeout_seconds):
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


def _validate_movement_jump_sequence_scenario(scenario: Mapping[str, Any], errors: list[str]) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    require_keys(
        scenario,
        ("sequence", "success_criteria", "failure_criteria"),
        "scenario",
    )

    sequence = scenario.get("sequence")
    if isinstance(sequence, Mapping):
        require_keys(
            sequence,
            ("camera_lock_stick_id", "move_stick_id", "forward_seconds", "backward_seconds", "jump_button_id"),
            "scenario.sequence",
        )

        for field in ("camera_lock_stick_id", "move_stick_id", "jump_button_id"):
            value = sequence.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"scenario.sequence.{field} must be a non-empty string")

        forward_seconds = sequence.get("forward_seconds")
        if not _is_number(forward_seconds):
            errors.append("scenario.sequence.forward_seconds must be a number")
        elif not (0.1 <= float(forward_seconds) <= 30):
            errors.append("scenario.sequence.forward_seconds must be in [0.1, 30]")

        backward_seconds = sequence.get("backward_seconds")
        if not _is_number(backward_seconds):
            errors.append("scenario.sequence.backward_seconds must be a number")
        elif not (0.1 <= float(backward_seconds) <= 30):
            errors.append("scenario.sequence.backward_seconds must be in [0.1, 30]")

        for axis_field in ("move_x", "forward_y", "backward_y"):
            axis_value = sequence.get(axis_field, 0.0 if axis_field == "move_x" else (1.0 if axis_field == "forward_y" else -1.0))
            if not _is_number(axis_value):
                errors.append(f"scenario.sequence.{axis_field} must be a number")
            elif not (-1.0 <= float(axis_value) <= 1.0):
                errors.append(f"scenario.sequence.{axis_field} must be in [-1, 1]")

        pulse_interval_seconds = sequence.get("pulse_interval_seconds", 0.1)
        if not _is_number(pulse_interval_seconds):
            errors.append("scenario.sequence.pulse_interval_seconds must be a number")
        elif not (0.05 <= float(pulse_interval_seconds) <= 1.0):
            errors.append("scenario.sequence.pulse_interval_seconds must be in [0.05, 1.0]")

        jump_duration_ms = sequence.get("jump_duration_ms", 120)
        if not _is_number(jump_duration_ms):
            errors.append("scenario.sequence.jump_duration_ms must be a number")
        elif not (50 <= float(jump_duration_ms) <= 3000):
            errors.append("scenario.sequence.jump_duration_ms must be in [50, 3000]")

        jump_settle_seconds = sequence.get("jump_settle_seconds", 0.2)
        if not _is_number(jump_settle_seconds):
            errors.append("scenario.sequence.jump_settle_seconds must be a number")
        elif not (0.0 <= float(jump_settle_seconds) <= 5.0):
            errors.append("scenario.sequence.jump_settle_seconds must be in [0.0, 5.0]")
    else:
        errors.append("scenario.sequence must be an object")

    success_criteria = scenario.get("success_criteria")
    if isinstance(success_criteria, Mapping):
        require_keys(success_criteria, ("timeout_seconds", "completion_state"), "scenario.success_criteria")
        timeout_seconds = success_criteria.get("timeout_seconds")
        if not _is_number(timeout_seconds):
            errors.append("scenario.success_criteria.timeout_seconds must be a number")
        elif not (1 <= float(timeout_seconds) <= 3600):
            errors.append("scenario.success_criteria.timeout_seconds must be in [1, 3600]")
        if success_criteria.get("completion_state") != SUPPORTED_MOVEMENT_COMPLETION_STATE:
            errors.append(
                f"scenario.success_criteria.completion_state must be {SUPPORTED_MOVEMENT_COMPLETION_STATE}"
            )
    else:
        errors.append("scenario.success_criteria must be an object")

    failure_criteria = scenario.get("failure_criteria")
    if isinstance(failure_criteria, Mapping):
        require_keys(failure_criteria, ("input_failure_limit",), "scenario.failure_criteria")
        input_failure_limit = failure_criteria.get("input_failure_limit")
        if not isinstance(input_failure_limit, int) or isinstance(input_failure_limit, bool):
            errors.append("scenario.failure_criteria.input_failure_limit must be an integer")
        elif not (1 <= input_failure_limit <= 10):
            errors.append("scenario.failure_criteria.input_failure_limit must be in [1, 10]")
    else:
        errors.append("scenario.failure_criteria must be an object")


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
            "success_criteria",
            "failure_criteria",
            "termination",
        ),
        "scenario",
    )
    _validate_common_fields(scenario, errors)

    intent = scenario.get("intent")
    if intent == SUPPORTED_DEFEAT_INTENT:
        _validate_defeat_monster_scenario(scenario, errors)
    elif intent == SUPPORTED_MOVEMENT_INTENT:
        _validate_movement_jump_sequence_scenario(scenario, errors)

    return errors
