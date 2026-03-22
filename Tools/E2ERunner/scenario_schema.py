from __future__ import annotations

from typing import Any, Mapping, Sequence

TERMINATION_MODES = ("keep_running", "close_game", "close_editor")
SUPPORTED_DEFEAT_INTENT = "defeat_monster"
SUPPORTED_MOVEMENT_INTENT = "movement_jump_sequence"
SUPPORTED_WORKFLOW_INTENT = "workflow_steps"
SUPPORTED_VISION_NAVIGATION_INTENT = "vision_navigation"
SUPPORTED_INTENTS = (
    SUPPORTED_DEFEAT_INTENT,
    SUPPORTED_MOVEMENT_INTENT,
    SUPPORTED_WORKFLOW_INTENT,
    SUPPORTED_VISION_NAVIGATION_INTENT,
)
SUPPORTED_SELECTOR_TYPE = "forward_cone"
SUPPORTED_TARGET_KIND = "monster"
SUPPORTED_MOVEMENT_COMPLETION_STATE = "sequence_completed"
SUPPORTED_MOVEMENT_DECISION_MODES = ("sequential", "decider")
SUPPORTED_MOVEMENT_DECISION_BRIDGE_MODE = "file"
SUPPORTED_WORKFLOW_COMPLETION_STATE = "steps_completed"
SUPPORTED_VISION_NAVIGATION_COMPLETION_STATE = "goal_reached"
SUPPORTED_VISION_NAVIGATION_SUCCESS_MODES = ("position", "visual", "hybrid")
SUPPORTED_VISION_NAVIGATION_DECISION_BRIDGE_MODE = "file"
SUPPORTED_VISION_NAVIGATION_DECISION_POLICY_MODES = ("strict", "advisory")
SUPPORTED_VISION_NAVIGATION_TARGET_MISSING_STRATEGIES = ("llm", "scan_yaw")
SUPPORTED_VISION_NAVIGATION_TARGET_FOUND_STRATEGIES = ("llm", "success_after_wait")
SUPPORTED_CONDITION_STATES = ("player_state", "target_state", "spatial_state", "success")
SUPPORTED_CONDITION_OPERATORS = ("eq", "ne", "lt", "lte", "gt", "gte")
SUPPORTED_WORKFLOW_ACTIONS = ("command", "wait", "move_phase", "move_to_location", "defeat_target")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_string_field(value: Any, errors: list[str], scope: str, *, field_name: str) -> None:
    if value is not None and not _is_non_empty_string(value):
        errors.append(f"{scope}.{field_name} must be a non-empty string when provided")


def _validate_number_range(
    value: Any,
    errors: list[str],
    scope: str,
    *,
    field_name: str,
    minimum: float,
    maximum: float,
) -> None:
    if not _is_number(value):
        errors.append(f"{scope}.{field_name} must be a number")
    elif not (minimum <= float(value) <= maximum):
        errors.append(f"{scope}.{field_name} must be in [{minimum}, {maximum}]")


def _validate_int_range(
    value: Any,
    errors: list[str],
    scope: str,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(f"{scope}.{field_name} must be an integer")
    elif not (minimum <= value <= maximum):
        errors.append(f"{scope}.{field_name} must be in [{minimum}, {maximum}]")


def _validate_alias_number_fields(
    payload: Mapping[str, Any],
    errors: list[str],
    scope: str,
    field_names: Sequence[str],
    *,
    minimum: float,
    maximum: float,
    integer: bool = False,
    required: bool = False,
) -> None:
    present_field_names = [field_name for field_name in field_names if field_name in payload]
    if not present_field_names:
        if required:
            errors.append(f"{scope}.{field_names[0]} is required")
        return

    value = payload[present_field_names[0]]
    for field_name in present_field_names[1:]:
        if payload[field_name] != value:
            errors.append(
                f"{scope}.{field_names[0]} and {scope}.{field_name} must match when both are provided"
            )
            break

    field_name = present_field_names[0]
    if integer:
        _validate_int_range(value, errors, scope, field_name=field_name, minimum=int(minimum), maximum=int(maximum))
    else:
        _validate_number_range(value, errors, scope, field_name=field_name, minimum=minimum, maximum=maximum)


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


def _validate_condition_object(condition: Mapping[str, Any], errors: list[str], scope: str) -> None:
    state = condition.get("state")
    path = condition.get("path")
    op = condition.get("op")
    if state not in SUPPORTED_CONDITION_STATES:
        errors.append(f"{scope}.state must be one of {', '.join(SUPPORTED_CONDITION_STATES)}")
    if not isinstance(path, str) or not path.strip():
        errors.append(f"{scope}.path must be a non-empty string")
    if op not in SUPPORTED_CONDITION_OPERATORS:
        errors.append(f"{scope}.op must be one of {', '.join(SUPPORTED_CONDITION_OPERATORS)}")
    if "value" not in condition:
        errors.append(f"{scope}.value is required")


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
            ("camera_lock_stick_id", "move_stick_id", "jump_button_id"),
            "scenario.sequence",
        )

        for field in ("camera_lock_stick_id", "move_stick_id", "jump_button_id"):
            value = sequence.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"scenario.sequence.{field} must be a non-empty string")

        phases = sequence.get("phases")
        if phases is not None:
            if not isinstance(phases, Sequence) or isinstance(phases, (str, bytes)):
                errors.append("scenario.sequence.phases must be an array when provided")
            elif len(phases) == 0:
                errors.append("scenario.sequence.phases must contain at least one phase")
            elif len(phases) > 20:
                errors.append("scenario.sequence.phases must contain at most 20 phases")
            else:
                for index, phase in enumerate(phases):
                    scope = f"scenario.sequence.phases[{index}]"
                    if not isinstance(phase, Mapping):
                        errors.append(f"{scope} must be an object")
                        continue

                    duration_seconds = phase.get("duration_seconds")
                    if not _is_number(duration_seconds):
                        errors.append(f"{scope}.duration_seconds must be a number")
                    elif not (0.1 <= float(duration_seconds) <= 30):
                        errors.append(f"{scope}.duration_seconds must be in [0.1, 30]")

                    for axis_field in ("move_x", "move_y"):
                        axis_value = phase.get(axis_field)
                        if not _is_number(axis_value):
                            errors.append(f"{scope}.{axis_field} must be a number")
                        elif not (-1.0 <= float(axis_value) <= 1.0):
                            errors.append(f"{scope}.{axis_field} must be in [-1, 1]")

                    jump_after = phase.get("jump_after", False)
                    if not isinstance(jump_after, bool):
                        errors.append(f"{scope}.jump_after must be a boolean")
        else:
            require_keys(
                sequence,
                ("forward_seconds", "backward_seconds"),
                "scenario.sequence",
            )
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

        decision_mode = str(sequence.get("decision_mode", "sequential")).strip().lower()
        if decision_mode not in SUPPORTED_MOVEMENT_DECISION_MODES:
            errors.append(
                "scenario.sequence.decision_mode must be one of "
                + ", ".join(SUPPORTED_MOVEMENT_DECISION_MODES)
            )

        decision_bridge = sequence.get("decision_bridge")
        if decision_bridge is not None:
            if not isinstance(decision_bridge, Mapping):
                errors.append("scenario.sequence.decision_bridge must be an object when provided")
            else:
                bridge_mode = decision_bridge.get("mode", SUPPORTED_MOVEMENT_DECISION_BRIDGE_MODE)
                if bridge_mode != SUPPORTED_MOVEMENT_DECISION_BRIDGE_MODE:
                    errors.append(
                        "scenario.sequence.decision_bridge.mode must be "
                        + SUPPORTED_MOVEMENT_DECISION_BRIDGE_MODE
                    )
                if "decide_wait_timeout_seconds" in decision_bridge:
                    _validate_number_range(
                        decision_bridge.get("decide_wait_timeout_seconds"),
                        errors,
                        "scenario.sequence.decision_bridge",
                        field_name="decide_wait_timeout_seconds",
                        minimum=1.0,
                        maximum=600.0,
                    )
                if "decide_retry_count" in decision_bridge:
                    _validate_int_range(
                        decision_bridge.get("decide_retry_count"),
                        errors,
                        "scenario.sequence.decision_bridge",
                        field_name="decide_retry_count",
                        minimum=0,
                        maximum=20,
                    )
                if "decide_poll_interval_seconds" in decision_bridge:
                    _validate_number_range(
                        decision_bridge.get("decide_poll_interval_seconds"),
                        errors,
                        "scenario.sequence.decision_bridge",
                        field_name="decide_poll_interval_seconds",
                        minimum=0.01,
                        maximum=5.0,
                    )
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


def _validate_workflow_steps_scenario(scenario: Mapping[str, Any], errors: list[str]) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    require_keys(
        scenario,
        ("steps", "success_criteria", "failure_criteria"),
        "scenario",
    )

    steps = scenario.get("steps")
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
        errors.append("scenario.steps must be an array")
    elif len(steps) == 0:
        errors.append("scenario.steps must contain at least one step")
    elif len(steps) > 200:
        errors.append("scenario.steps must contain at most 200 steps")
    else:
        for index, step in enumerate(steps):
            scope = f"scenario.steps[{index}]"
            if not isinstance(step, Mapping):
                errors.append(f"{scope} must be an object")
                continue
            action = step.get("action")
            if action not in SUPPORTED_WORKFLOW_ACTIONS:
                errors.append(f"{scope}.action must be one of {', '.join(SUPPORTED_WORKFLOW_ACTIONS)}")
                continue
            if "name" in step and (not isinstance(step.get("name"), str) or not str(step.get("name")).strip()):
                errors.append(f"{scope}.name must be a non-empty string when provided")

            when = step.get("when")
            if when is not None:
                if not isinstance(when, Mapping):
                    errors.append(f"{scope}.when must be an object")
                else:
                    _validate_condition_object(when, errors, f"{scope}.when")

            if action == "command":
                command = step.get("command")
                if not isinstance(command, str) or not command.strip():
                    errors.append(f"{scope}.command must be a non-empty string")
                args = step.get("args", {})
                if args is not None and not isinstance(args, Mapping):
                    errors.append(f"{scope}.args must be an object when provided")
            elif action == "wait":
                seconds = step.get("seconds")
                if not _is_number(seconds):
                    errors.append(f"{scope}.seconds must be a number")
                elif not (0.0 <= float(seconds) <= 3600):
                    errors.append(f"{scope}.seconds must be in [0.0, 3600]")
            elif action == "move_phase":
                args = step.get("args")
                if not isinstance(args, Mapping):
                    errors.append(f"{scope}.args must be an object")
                    continue
                for axis_field in ("x", "y"):
                    axis_value = args.get(axis_field)
                    if not _is_number(axis_value):
                        errors.append(f"{scope}.args.{axis_field} must be a number")
                    elif not (-1.0 <= float(axis_value) <= 1.0):
                        errors.append(f"{scope}.args.{axis_field} must be in [-1, 1]")
                duration_seconds = args.get("duration_seconds")
                if not _is_number(duration_seconds):
                    errors.append(f"{scope}.args.duration_seconds must be a number")
                elif not (0.1 <= float(duration_seconds) <= 120.0):
                    errors.append(f"{scope}.args.duration_seconds must be in [0.1, 120]")
                stick_id = args.get("stick_id", "left_stick")
                if not isinstance(stick_id, str) or not stick_id.strip():
                    errors.append(f"{scope}.args.stick_id must be a non-empty string when provided")
            elif action == "move_to_location":
                args = step.get("args")
                if not isinstance(args, Mapping):
                    errors.append(f"{scope}.args must be an object")
                    continue
                for coord in ("x", "y"):
                    coord_value = args.get(coord)
                    if not _is_number(coord_value):
                        errors.append(f"{scope}.args.{coord} must be a number")
                tolerance_cm = args.get("tolerance_cm", 30.0)
                if not _is_number(tolerance_cm):
                    errors.append(f"{scope}.args.tolerance_cm must be a number")
                elif not (1.0 <= float(tolerance_cm) <= 10000.0):
                    errors.append(f"{scope}.args.tolerance_cm must be in [1, 10000]")
                max_seconds = args.get("max_seconds", 30.0)
                if not _is_number(max_seconds):
                    errors.append(f"{scope}.args.max_seconds must be a number")
                elif not (0.1 <= float(max_seconds) <= 3600.0):
                    errors.append(f"{scope}.args.max_seconds must be in [0.1, 3600]")
            elif action == "defeat_target":
                args = step.get("args", {})
                if args is not None and not isinstance(args, Mapping):
                    errors.append(f"{scope}.args must be an object when provided")
                    continue
                max_attempts = args.get("attack_max_attempts", 12)
                if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
                    errors.append(f"{scope}.args.attack_max_attempts must be an integer")
                elif not (1 <= max_attempts <= 500):
                    errors.append(f"{scope}.args.attack_max_attempts must be in [1, 500]")

    success_criteria = scenario.get("success_criteria")
    if isinstance(success_criteria, Mapping):
        require_keys(success_criteria, ("timeout_seconds", "completion_state"), "scenario.success_criteria")
        timeout_seconds = success_criteria.get("timeout_seconds")
        if not _is_number(timeout_seconds):
            errors.append("scenario.success_criteria.timeout_seconds must be a number")
        elif not (1 <= float(timeout_seconds) <= 3600):
            errors.append("scenario.success_criteria.timeout_seconds must be in [1, 3600]")
        if success_criteria.get("completion_state") != SUPPORTED_WORKFLOW_COMPLETION_STATE:
            errors.append(
                f"scenario.success_criteria.completion_state must be {SUPPORTED_WORKFLOW_COMPLETION_STATE}"
            )
    else:
        errors.append("scenario.success_criteria must be an object")

    failure_criteria = scenario.get("failure_criteria")
    if isinstance(failure_criteria, Mapping):
        require_keys(failure_criteria, ("input_failure_limit",), "scenario.failure_criteria")
        input_failure_limit = failure_criteria.get("input_failure_limit")
        if not isinstance(input_failure_limit, int) or isinstance(input_failure_limit, bool):
            errors.append("scenario.failure_criteria.input_failure_limit must be an integer")
        elif not (1 <= input_failure_limit <= 50):
            errors.append("scenario.failure_criteria.input_failure_limit must be in [1, 50]")
    else:
        errors.append("scenario.failure_criteria must be an object")

    assertions = scenario.get("assertions")
    if assertions is not None:
        if not isinstance(assertions, Sequence) or isinstance(assertions, (str, bytes)):
            errors.append("scenario.assertions must be an array when provided")
        elif len(assertions) > 200:
            errors.append("scenario.assertions must contain at most 200 items")
        else:
            for index, assertion in enumerate(assertions):
                scope = f"scenario.assertions[{index}]"
                if not isinstance(assertion, Mapping):
                    errors.append(f"{scope} must be an object")
                    continue
                _validate_condition_object(assertion, errors, scope)
                if "message" in assertion and (
                    not isinstance(assertion.get("message"), str) or not str(assertion.get("message")).strip()
                ):
                    errors.append(f"{scope}.message must be a non-empty string when provided")


def _validate_vision_navigation_goal(goal: Mapping[str, Any], errors: list[str]) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    if not isinstance(goal, Mapping):
        errors.append("scenario.goal must be an object")
        return

    description = goal.get("description")
    visual_target = goal.get("visual_target")
    position_target = goal.get("position_target")

    _validate_string_field(description, errors, "scenario.goal", field_name="description")
    _validate_string_field(visual_target, errors, "scenario.goal", field_name="visual_target")

    if position_target is not None:
        if not isinstance(position_target, Mapping):
            errors.append("scenario.goal.position_target must be an object when provided")
        else:
            require_keys(position_target, ("x", "y"), "scenario.goal.position_target")
            _validate_number_range(
                position_target.get("x"),
                errors,
                "scenario.goal.position_target",
                field_name="x",
                minimum=-100000.0,
                maximum=100000.0,
            )
            _validate_number_range(
                position_target.get("y"),
                errors,
                "scenario.goal.position_target",
                field_name="y",
                minimum=-100000.0,
                maximum=100000.0,
            )
            if "z" in position_target:
                z_value = position_target.get("z")
                if z_value is not None:
                    _validate_number_range(
                        z_value,
                        errors,
                        "scenario.goal.position_target",
                        field_name="z",
                        minimum=-100000.0,
                        maximum=100000.0,
                    )
            if "tolerance_cm" in position_target:
                tolerance_cm = position_target.get("tolerance_cm")
                if tolerance_cm is not None:
                    _validate_number_range(
                        tolerance_cm,
                        errors,
                        "scenario.goal.position_target",
                        field_name="tolerance_cm",
                        minimum=0.1,
                        maximum=10000.0,
                    )

    if not any(
        (
            _is_non_empty_string(description),
            _is_non_empty_string(visual_target),
            position_target is not None,
        )
    ):
        errors.append(
            "scenario.goal must define at least one of description, visual_target, or position_target"
        )


def _validate_vision_navigation_success_criteria(
    success_criteria: Mapping[str, Any],
    goal: Mapping[str, Any],
    errors: list[str],
) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    if not isinstance(success_criteria, Mapping):
        errors.append("scenario.success_criteria must be an object")
        return

    require_keys(success_criteria, ("timeout_seconds", "completion_state", "success_mode"), "scenario.success_criteria")

    timeout_seconds = success_criteria.get("timeout_seconds")
    _validate_number_range(
        timeout_seconds,
        errors,
        "scenario.success_criteria",
        field_name="timeout_seconds",
        minimum=1.0,
        maximum=3600.0,
    )

    if success_criteria.get("completion_state") != SUPPORTED_VISION_NAVIGATION_COMPLETION_STATE:
        errors.append(
            "scenario.success_criteria.completion_state must be goal_reached"
        )

    success_mode = success_criteria.get("success_mode")
    if success_mode not in SUPPORTED_VISION_NAVIGATION_SUCCESS_MODES:
        errors.append(
            "scenario.success_criteria.success_mode must be one of position, visual, hybrid"
        )
    else:
        position_target = goal.get("position_target") if isinstance(goal, Mapping) else None
        if success_mode in {"position", "hybrid"}:
            if position_target is None:
                errors.append(
                    f"scenario.goal.position_target is required when scenario.success_criteria.success_mode is {success_mode}"
                )
        elif position_target is not None:
            errors.append(
                "scenario.goal.position_target is only allowed when scenario.success_criteria.success_mode is position or hybrid"
            )


def _validate_vision_navigation_failure_criteria(failure_criteria: Mapping[str, Any], errors: list[str]) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    if not isinstance(failure_criteria, Mapping):
        errors.append("scenario.failure_criteria must be an object")
        return

    require_keys(failure_criteria, ("input_failure_limit",), "scenario.failure_criteria")
    _validate_int_range(
        failure_criteria.get("input_failure_limit"),
        errors,
        "scenario.failure_criteria",
        field_name="input_failure_limit",
        minimum=1,
        maximum=10,
    )

    if "capture_failure_limit" in failure_criteria:
        _validate_int_range(
            failure_criteria.get("capture_failure_limit"),
            errors,
            "scenario.failure_criteria",
            field_name="capture_failure_limit",
            minimum=0,
            maximum=10,
        )

    if "decision_failure_limit" in failure_criteria:
        _validate_int_range(
            failure_criteria.get("decision_failure_limit"),
            errors,
            "scenario.failure_criteria",
            field_name="decision_failure_limit",
            minimum=0,
            maximum=10,
        )


def _validate_vision_navigation_loop(loop: Mapping[str, Any], errors: list[str]) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    if not isinstance(loop, Mapping):
        errors.append("scenario.loop must be an object")
        return

    require_keys(loop, ("max_iterations", "observe_interval_seconds"), "scenario.loop")

    _validate_int_range(
        loop.get("max_iterations"),
        errors,
        "scenario.loop",
        field_name="max_iterations",
        minimum=1,
        maximum=200,
    )
    _validate_number_range(
        loop.get("observe_interval_seconds"),
        errors,
        "scenario.loop",
        field_name="observe_interval_seconds",
        minimum=0.05,
        maximum=5.0,
    )

    _validate_alias_number_fields(
        loop,
        errors,
        "scenario.loop",
        ("capture_timeout_seconds", "observe_timeout_seconds"),
        minimum=0.5,
        maximum=300.0,
        required=True,
    )
    _validate_alias_number_fields(
        loop,
        errors,
        "scenario.loop",
        ("action_timeout_seconds", "act_timeout_seconds"),
        minimum=0.5,
        maximum=300.0,
        required=True,
    )

    if "decision_timeout_seconds" in loop or "decide_timeout_seconds" in loop:
        _validate_alias_number_fields(
            loop,
            errors,
            "scenario.loop",
            ("decision_timeout_seconds", "decide_timeout_seconds"),
            minimum=0.5,
            maximum=300.0,
        )


def _validate_vision_navigation_capture(capture: Mapping[str, Any], errors: list[str]) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    if not isinstance(capture, Mapping):
        errors.append("scenario.capture must be an object")
        return

    require_keys(capture, ("height", "preserve_aspect_ratio", "jpeg_quality"), "scenario.capture")

    _validate_int_range(
        capture.get("height"),
        errors,
        "scenario.capture",
        field_name="height",
        minimum=64,
        maximum=2160,
    )
    preserve_aspect_ratio = capture.get("preserve_aspect_ratio")
    if not isinstance(preserve_aspect_ratio, bool):
        errors.append("scenario.capture.preserve_aspect_ratio must be a boolean")
    _validate_int_range(
        capture.get("jpeg_quality"),
        errors,
        "scenario.capture",
        field_name="jpeg_quality",
        minimum=1,
        maximum=100,
    )


def _validate_vision_navigation_decision_bridge(
    decision_bridge: Mapping[str, Any],
    errors: list[str],
) -> None:
    def require_keys(payload: Mapping[str, Any], keys: Sequence[str], scope: str) -> None:
        for key in keys:
            if key not in payload:
                errors.append(f"{scope}.{key} is required")

    if not isinstance(decision_bridge, Mapping):
        errors.append("scenario.decision_bridge must be an object")
        return

    require_keys(decision_bridge, ("mode",), "scenario.decision_bridge")

    if decision_bridge.get("mode") != SUPPORTED_VISION_NAVIGATION_DECISION_BRIDGE_MODE:
        errors.append("scenario.decision_bridge.mode must be file")

    _validate_alias_number_fields(
        decision_bridge,
        errors,
        "scenario.decision_bridge",
        ("decide_wait_timeout_seconds", "decision_timeout_seconds"),
        minimum=0.5,
        maximum=300.0,
        required=True,
    )
    _validate_alias_number_fields(
        decision_bridge,
        errors,
        "scenario.decision_bridge",
        ("decide_retry_count", "decision_retry_count"),
        minimum=0,
        maximum=10,
        integer=True,
        required=True,
    )


def _validate_vision_navigation_decision_policy(
    decision_policy: Mapping[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(decision_policy, Mapping):
        errors.append("scenario.decision_policy must be an object when provided")
        return

    if "policy_version" in decision_policy:
        _validate_int_range(
            decision_policy.get("policy_version"),
            errors,
            "scenario.decision_policy",
            field_name="policy_version",
            minimum=1,
            maximum=10,
        )

    if "mode" in decision_policy:
        mode = decision_policy.get("mode")
        if mode not in SUPPORTED_VISION_NAVIGATION_DECISION_POLICY_MODES:
            errors.append(
                "scenario.decision_policy.mode must be one of strict, advisory"
            )

    target_missing = decision_policy.get("target_missing")
    if target_missing is not None:
        if not isinstance(target_missing, Mapping):
            errors.append("scenario.decision_policy.target_missing must be an object when provided")
        else:
            strategy = target_missing.get("strategy")
            if strategy is not None and strategy not in SUPPORTED_VISION_NAVIGATION_TARGET_MISSING_STRATEGIES:
                errors.append(
                    "scenario.decision_policy.target_missing.strategy must be one of llm, scan_yaw"
                )
            if "scan_step_degrees" in target_missing:
                _validate_number_range(
                    target_missing.get("scan_step_degrees"),
                    errors,
                    "scenario.decision_policy.target_missing",
                    field_name="scan_step_degrees",
                    minimum=-180.0,
                    maximum=180.0,
                )
            if "scan_duration_ms" in target_missing:
                _validate_int_range(
                    target_missing.get("scan_duration_ms"),
                    errors,
                    "scenario.decision_policy.target_missing",
                    field_name="scan_duration_ms",
                    minimum=10,
                    maximum=5000,
                )
            if "wait_seconds" in target_missing:
                _validate_number_range(
                    target_missing.get("wait_seconds"),
                    errors,
                    "scenario.decision_policy.target_missing",
                    field_name="wait_seconds",
                    minimum=0.0,
                    maximum=30.0,
                )

    target_found = decision_policy.get("target_found")
    if target_found is not None:
        if not isinstance(target_found, Mapping):
            errors.append("scenario.decision_policy.target_found must be an object when provided")
        else:
            strategy = target_found.get("strategy")
            if strategy is not None and strategy not in SUPPORTED_VISION_NAVIGATION_TARGET_FOUND_STRATEGIES:
                errors.append(
                    "scenario.decision_policy.target_found.strategy must be one of llm, success_after_wait"
                )
            if "success_wait_seconds" in target_found:
                _validate_number_range(
                    target_found.get("success_wait_seconds"),
                    errors,
                    "scenario.decision_policy.target_found",
                    field_name="success_wait_seconds",
                    minimum=0.0,
                    maximum=30.0,
                )

    guardrails = decision_policy.get("guardrails")
    if guardrails is not None:
        if not isinstance(guardrails, Mapping):
            errors.append("scenario.decision_policy.guardrails must be an object when provided")
        else:
            if "require_image_observation" in guardrails and not isinstance(
                guardrails.get("require_image_observation"), bool
            ):
                errors.append(
                    "scenario.decision_policy.guardrails.require_image_observation must be a boolean"
                )
            if "max_actions_per_iteration" in guardrails:
                _validate_int_range(
                    guardrails.get("max_actions_per_iteration"),
                    errors,
                    "scenario.decision_policy.guardrails",
                    field_name="max_actions_per_iteration",
                    minimum=1,
                    maximum=10,
                )


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
    elif intent == SUPPORTED_WORKFLOW_INTENT:
        _validate_workflow_steps_scenario(scenario, errors)
    elif intent == SUPPORTED_VISION_NAVIGATION_INTENT:
        goal = scenario.get("goal")
        _validate_vision_navigation_goal(goal, errors)
        _validate_vision_navigation_success_criteria(
            scenario.get("success_criteria"),
            goal if isinstance(goal, Mapping) else {},
            errors,
        )
        _validate_vision_navigation_failure_criteria(scenario.get("failure_criteria"), errors)

        loop = scenario.get("loop")
        _validate_vision_navigation_loop(loop, errors)

        capture = scenario.get("capture")
        if capture is not None:
            _validate_vision_navigation_capture(capture, errors)
        else:
            errors.append("scenario.capture is required")

        decision_bridge = scenario.get("decision_bridge")
        if decision_bridge is not None:
            _validate_vision_navigation_decision_bridge(decision_bridge, errors)
        else:
            errors.append("scenario.decision_bridge is required")

        decision_policy = scenario.get("decision_policy")
        if decision_policy is not None:
            _validate_vision_navigation_decision_policy(decision_policy, errors)

    return errors
