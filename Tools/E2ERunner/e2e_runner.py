from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Tools.ParallelRunner.parallel_runner import (  # noqa: E402
    DEFAULT_UNREAL_EXECUTABLE,
    DEFAULT_UPROJECT,
    build_unreal_command,
    generate_run_id,
    generate_session_id,
    utc_now_iso,
)
from Tools.E2ERunner.scenario_schema import (  # noqa: E402
    SUPPORTED_DEFEAT_INTENT,
    SUPPORTED_MOVEMENT_INTENT,
    SUPPORTED_WORKFLOW_INTENT,
    TERMINATION_MODES,
    validate_scenario,
)
from Tools.UnrealTestClient.unreal_test_client import (  # noqa: E402
    UnrealTestClient,
    UnrealTestClientError,
)


class E2ERunnerError(RuntimeError):
    """Raised when the end-to-end scenario cannot be completed."""


@dataclass
class _LaunchContext:
    process: subprocess.Popen[Any]
    log_path: Path
    log_stream: Any


def _extract_port_from_base_url(base_url: str) -> int:
    parsed = urlsplit(base_url)
    if parsed.port is not None:
        return int(parsed.port)
    if parsed.scheme == "https":
        return 443
    return 80


def _safe_sequence(value: Any, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return fallback
    return fallback


def _make_failure(stage: str, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    failure: Dict[str, Any] = {
        "stage": stage,
        "code": code,
        "message": message,
    }
    if details:
        failure["details"] = dict(details)
    return failure


def _safe_float(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return fallback
    return fallback


def _parse_key_value_args(values: list[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise E2ERunnerError(f"Invalid --equip-recipe-arg value: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise E2ERunnerError(f"Invalid --equip-recipe-arg value: {item}")
        parsed[key] = value
    return parsed


def _terminate_process(process: subprocess.Popen[Any], grace_seconds: float) -> str:
    if process.poll() is not None:
        return "already-exited"
    try:
        process.terminate()
        process.wait(timeout=max(0.1, grace_seconds))
        return "terminate"
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=max(0.1, grace_seconds))
        return "kill"


def _wait_until_healthy(client: UnrealTestClient, timeout: float, poll_interval: float) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            return client.connect()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(max(0.05, poll_interval))
    raise E2ERunnerError(f"Health check timeout after {timeout} seconds.") from last_error


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _start_unreal_if_requested(
    args: argparse.Namespace,
    *,
    run_id: str,
    session_id: str,
    run_dir: Path,
) -> Optional[_LaunchContext]:
    if not args.launch:
        return None

    target_port = args.port if args.port is not None else _extract_port_from_base_url(args.base_url)
    command = build_unreal_command(
        unreal_executable=args.unreal_executable,
        uproject=args.uproject,
        session_id=session_id,
        port=target_port,
        run_id=run_id,
        scenario=args.scenario,
        extra_args=args.extra_arg,
    )

    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "unreal.log"
    log_stream = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        command["argv"],
        cwd=command["working_directory"],
        stdout=log_stream,
        stderr=subprocess.STDOUT,
    )
    return _LaunchContext(process=process, log_path=log_path, log_stream=log_stream)


def _create_step_record(name: str, *, command: str, request_args: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "name": name,
        "command": command,
        "request_args": dict(request_args),
        "status": "running",
        "started_at_utc": utc_now_iso(),
        "ended_at_utc": None,
        "duration_seconds": None,
        "response": None,
        "observation": {},
        "failure": None,
    }


def _finalize_step_record(
    step: Dict[str, Any],
    *,
    status: str,
    response: Optional[Mapping[str, Any]] = None,
    observation: Optional[Mapping[str, Any]] = None,
    failure: Optional[Mapping[str, Any]] = None,
    started_at_monotonic: Optional[float] = None,
) -> None:
    step["status"] = status
    step["ended_at_utc"] = utc_now_iso()
    if started_at_monotonic is not None:
        step["duration_seconds"] = round(max(0.0, time.monotonic() - started_at_monotonic), 3)
    if response is not None:
        step["response"] = dict(response)
    if observation is not None:
        step["observation"] = dict(observation)
    if failure is not None:
        step["failure"] = dict(failure)


def _send_command_step(
    client: UnrealTestClient,
    result: Dict[str, Any],
    *,
    name: str,
    command: str,
    session_id: str,
    request_args: Mapping[str, Any],
) -> Dict[str, Any]:
    step = _create_step_record(name, command=command, request_args=request_args)
    result["steps"].append(step)
    started_at_monotonic = time.monotonic()

    try:
        response = client.send_command(command, session_id=session_id, args=request_args)
    except UnrealTestClientError as exc:
        failure = _make_failure(name, "transport_error", str(exc))
        _finalize_step_record(
            step,
            status="failed",
            failure=failure,
            started_at_monotonic=started_at_monotonic,
        )
        raise E2ERunnerError(f"{name} command transport failed: {exc}") from exc

    if not bool(response.get("accepted", False)):
        error_code = str(response.get("error_code", "command_rejected"))
        failure = _make_failure(
            name,
            error_code,
            str(response.get("error_message", f"{name} command was rejected.")),
            details={
                "error_stage": response.get("error_stage"),
                "command": response.get("command"),
            },
        )
        _finalize_step_record(
            step,
            status="failed",
            response=response,
            failure=failure,
            started_at_monotonic=started_at_monotonic,
        )
        raise E2ERunnerError(f"{name} command rejected: {failure['message']}")

    _finalize_step_record(
        step,
        status="passed",
        response=response,
        started_at_monotonic=started_at_monotonic,
    )
    return step


def _read_actor_died_event(client: UnrealTestClient, session_id: str, after_sequence: int) -> tuple[Optional[Mapping[str, Any]], int]:
    events_payload = client.get_events(
        session_id=session_id,
        type_filter="actor_died",
        after_sequence=after_sequence if after_sequence > 0 else None,
    )
    last_sequence = _safe_sequence(events_payload.get("last_sequence"), after_sequence)
    events = events_payload.get("events", [])
    if isinstance(events, list):
        for event in events:
            if isinstance(event, Mapping) and str(event.get("type", "")) == "actor_died":
                return event, last_sequence
    return None, last_sequence


def _should_tolerate_approach_failure(failure: Mapping[str, Any]) -> bool:
    code = str(failure.get("code", "")).strip().lower()
    message = str(failure.get("message", "")).strip().lower()
    if code == "input_execution_failed" and "native axis input" in message:
        return True
    return False


def _safe_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return fallback
    return fallback


def _resolve_path_value(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for raw_token in path.split("."):
        token = raw_token.strip()
        if not token:
            return None
        if not isinstance(current, Mapping):
            return None
        current = current.get(token)
    return current


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _evaluate_condition(condition: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[bool, Dict[str, Any]]:
    state_name = str(condition.get("state", "")).strip()
    path = str(condition.get("path", "")).strip()
    op = str(condition.get("op", "")).strip().lower()
    expected = condition.get("value")
    state_payload_raw = context.get(state_name)
    state_payload = state_payload_raw if isinstance(state_payload_raw, Mapping) else {}
    actual = _resolve_path_value(state_payload, path)
    details = {
        "state": state_name,
        "path": path,
        "op": op,
        "expected": expected,
        "actual": actual,
    }

    if op == "eq":
        return actual == expected, details
    if op == "ne":
        return actual != expected, details

    actual_number = _to_number(actual)
    expected_number = _to_number(expected)
    if actual_number is None or expected_number is None:
        return False, details
    if op == "lt":
        return actual_number < expected_number, details
    if op == "lte":
        return actual_number <= expected_number, details
    if op == "gt":
        return actual_number > expected_number, details
    if op == "gte":
        return actual_number >= expected_number, details
    return False, details


def _load_scenario_definition(args: argparse.Namespace, *, run_dir: Path) -> tuple[Dict[str, Any], str]:
    if bool(args.scenario_json) == bool(args.scenario_file):
        raise E2ERunnerError("Provide exactly one of --scenario-json or --scenario-file.")

    source = "scenario-json"
    if args.scenario_json:
        try:
            payload = json.loads(args.scenario_json)
        except json.JSONDecodeError as exc:
            raise E2ERunnerError(f"Invalid --scenario-json payload: {exc}") from exc
        if not isinstance(payload, dict):
            raise E2ERunnerError("--scenario-json must decode to a JSON object.")
        scenario = dict(payload)
    else:
        source = "scenario-file"
        scenario_path = args.scenario_file.expanduser().resolve()
        try:
            raw = scenario_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise E2ERunnerError(f"Failed to read scenario file: {scenario_path}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise E2ERunnerError(f"Invalid scenario file JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise E2ERunnerError("Scenario file must contain a JSON object.")
        scenario = dict(payload)

    termination = scenario.get("termination")
    if isinstance(termination, Mapping):
        scenario["termination"] = dict(termination)
    else:
        scenario["termination"] = {}
    if args.termination_mode:
        scenario["termination"]["mode"] = args.termination_mode

    errors = validate_scenario(scenario)
    if errors:
        raise E2ERunnerError(f"Scenario validation failed: {'; '.join(errors)}")

    run_dir.mkdir(parents=True, exist_ok=True)
    validated_path = run_dir / "scenario.validated.json"
    _write_json(validated_path, scenario)
    return scenario, source


def _send_command(
    client: UnrealTestClient,
    *,
    session_id: str,
    command: str,
    request_args: Mapping[str, Any],
) -> Mapping[str, Any]:
    response = client.send_command(command, session_id=session_id, args=request_args)
    if isinstance(response, Mapping):
        return response
    raise E2ERunnerError(f"{command} command response is not a JSON object.")


def _run_movement_jump_sequence(
    client: UnrealTestClient,
    result: Dict[str, Any],
    *,
    session_id: str,
    scenario_definition: Mapping[str, Any],
    poll_interval: float,
) -> None:
    sequence = scenario_definition.get("sequence", {})
    success_criteria = scenario_definition.get("success_criteria", {})
    failure_criteria = scenario_definition.get("failure_criteria", {})
    if not isinstance(sequence, Mapping):
        raise E2ERunnerError("scenario.sequence must be an object.")

    timeout_seconds = _safe_float(
        success_criteria.get("timeout_seconds") if isinstance(success_criteria, Mapping) else None,
        15.0,
    )
    input_failure_limit = _safe_int(
        failure_criteria.get("input_failure_limit") if isinstance(failure_criteria, Mapping) else None,
        3,
    )
    camera_lock_stick_id = str(sequence.get("camera_lock_stick_id", "right_stick")).strip() or "right_stick"
    move_stick_id = str(sequence.get("move_stick_id", "left_stick")).strip() or "left_stick"
    jump_button_id = str(sequence.get("jump_button_id", "jump")).strip() or "jump"
    forward_seconds = _safe_float(sequence.get("forward_seconds"), 2.0)
    backward_seconds = _safe_float(sequence.get("backward_seconds"), 2.0)
    move_x = _safe_float(sequence.get("move_x"), 0.0)
    forward_y = _safe_float(sequence.get("forward_y"), 1.0)
    backward_y = _safe_float(sequence.get("backward_y"), -1.0)
    phases_raw = sequence.get("phases")
    phase_plan: list[Dict[str, Any]] = []
    if isinstance(phases_raw, list) and len(phases_raw) > 0:
        for index, phase in enumerate(phases_raw):
            if not isinstance(phase, Mapping):
                continue
            phase_name = str(phase.get("name", f"phase_{index + 1}")).strip() or f"phase_{index + 1}"
            phase_plan.append(
                {
                    "name": phase_name,
                    "move_x": max(-1.0, min(1.0, _safe_float(phase.get("move_x"), 0.0))),
                    "move_y": max(-1.0, min(1.0, _safe_float(phase.get("move_y"), 0.0))),
                    "duration_seconds": max(0.1, _safe_float(phase.get("duration_seconds"), 0.1)),
                    "jump_after": bool(phase.get("jump_after", False)),
                }
            )
    if len(phase_plan) == 0:
        phase_plan = [
            {
                "name": "forward",
                "move_x": max(-1.0, min(1.0, move_x)),
                "move_y": max(-1.0, min(1.0, forward_y)),
                "duration_seconds": max(0.1, forward_seconds),
                "jump_after": True,
            },
            {
                "name": "backward",
                "move_x": max(-1.0, min(1.0, move_x)),
                "move_y": max(-1.0, min(1.0, backward_y)),
                "duration_seconds": max(0.1, backward_seconds),
                "jump_after": False,
            },
        ]
    pulse_interval_seconds = _safe_float(sequence.get("pulse_interval_seconds"), 0.1)
    pulse_interval_seconds = max(0.05, min(1.0, pulse_interval_seconds))
    pulse_duration_ms = max(50, int(round(pulse_interval_seconds * 1000.0)))
    jump_duration_ms = max(50, _safe_int(sequence.get("jump_duration_ms"), 120))
    jump_settle_seconds = max(0.0, _safe_float(sequence.get("jump_settle_seconds"), 0.2))

    step = _create_step_record(
        "movement_jump_sequence",
        command="sequence_execute",
        request_args={
            "camera_lock_stick_id": camera_lock_stick_id,
            "move_stick_id": move_stick_id,
            "jump_button_id": jump_button_id,
            "pulse_interval_seconds": pulse_interval_seconds,
            "phases": phase_plan,
        },
    )
    result["steps"].append(step)
    step_started_at_monotonic = time.monotonic()
    deadline = step_started_at_monotonic + max(1.0, timeout_seconds)
    command_log: list[Dict[str, Any]] = []
    consecutive_input_failures = 0

    observation: Dict[str, Any] = {
        "command_log": command_log,
        "timeout_seconds": timeout_seconds,
        "input_failure_limit": input_failure_limit,
        "sequence": {
            "camera_lock_stick_id": camera_lock_stick_id,
            "move_stick_id": move_stick_id,
            "jump_button_id": jump_button_id,
            "phases": phase_plan,
        },
    }

    def _fail_sequence(
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
        response: Optional[Mapping[str, Any]] = None,
    ) -> None:
        failure = _make_failure("movement_jump_sequence", code, message, details=details)
        _finalize_step_record(
            step,
            status="failed",
            response=response,
            observation=observation,
            failure=failure,
            started_at_monotonic=step_started_at_monotonic,
        )
        raise E2ERunnerError(message)

    def _check_timeout() -> None:
        if time.monotonic() >= deadline:
            _fail_sequence(
                "overall_timeout",
                f"Movement jump sequence exceeded timeout ({timeout_seconds} seconds).",
                details={"timeout_seconds": timeout_seconds},
            )

    def _send_sequence_command(name: str, command: str, request_args: Mapping[str, Any]) -> bool:
        nonlocal consecutive_input_failures
        _check_timeout()
        started_at = time.monotonic()
        response = _send_command(client, session_id=session_id, command=command, request_args=request_args)
        accepted = bool(response.get("accepted", False))
        record: Dict[str, Any] = {
            "name": name,
            "command": command,
            "request_args": dict(request_args),
            "accepted": accepted,
            "error_code": response.get("error_code"),
            "error_message": response.get("error_message"),
            "duration_seconds": round(max(0.0, time.monotonic() - started_at), 3),
        }
        details = response.get("details")
        if isinstance(details, Mapping):
            input_execution = details.get("input_execution")
            if isinstance(input_execution, Mapping):
                if "input_key" in input_execution:
                    record["input_key"] = input_execution.get("input_key")
                if "input_mode" in input_execution:
                    record["input_mode"] = input_execution.get("input_mode")
                if "tap_duration_ms" in input_execution:
                    record["tap_duration_ms"] = input_execution.get("tap_duration_ms")
                if "can_jump_before" in input_execution:
                    record["can_jump_before"] = input_execution.get("can_jump_before")
                if "release_scheduled" in input_execution:
                    record["release_scheduled"] = input_execution.get("release_scheduled")
                if "release_delay_seconds" in input_execution:
                    record["release_delay_seconds"] = input_execution.get("release_delay_seconds")
        command_log.append(record)

        if accepted:
            consecutive_input_failures = 0
            return True

        error_code = str(response.get("error_code", "command_rejected"))
        if error_code == "input_execution_failed":
            consecutive_input_failures += 1
            if consecutive_input_failures < max(1, input_failure_limit):
                return False
            _fail_sequence(
                "input_execution_failed_limit",
                "Sequence failed repeatedly due to input execution errors.",
                details={
                    "input_failure_limit": input_failure_limit,
                    "last_error_message": response.get("error_message"),
                },
                response=response,
            )

        _fail_sequence(
            error_code,
            str(response.get("error_message", f"{name} command was rejected.")),
            details={"error_stage": response.get("error_stage")},
            response=response,
        )

    def _send_with_retry(name: str, command: str, request_args: Mapping[str, Any]) -> None:
        attempts = 0
        max_attempts = max(1, input_failure_limit)
        while attempts < max_attempts:
            attempts += 1
            accepted = _send_sequence_command(f"{name}_attempt_{attempts}", command, request_args)
            if accepted:
                return
            time.sleep(max(0.01, min(pulse_interval_seconds, poll_interval if poll_interval > 0 else pulse_interval_seconds)))
        _fail_sequence(
            "input_execution_failed_limit",
            f"{name} command could not be accepted within failure limits.",
            details={"input_failure_limit": input_failure_limit},
        )

    def _run_move_phase(phase_name: str, duration_seconds: float, axis_x: float, axis_y: float) -> None:
        phase_started = time.monotonic()
        pulse_index = 0
        while (time.monotonic() - phase_started) < duration_seconds:
            pulse_index += 1
            accepted = _send_sequence_command(
                f"{phase_name}_move_{pulse_index}",
                "move_stick",
                {
                    "stick_id": move_stick_id,
                    "x": axis_x,
                    "y": axis_y,
                    "duration_ms": pulse_duration_ms,
                },
            )
            if accepted:
                result["checks"]["approach"] = True
            time.sleep(max(0.01, min(pulse_interval_seconds, poll_interval if poll_interval > 0 else pulse_interval_seconds)))
        _send_sequence_command(
            f"{phase_name}_release",
            "release_stick",
            {"stick_id": move_stick_id},
        )

    _send_with_retry(
        "camera_lock_center",
        "move_stick",
        {"stick_id": camera_lock_stick_id, "x": 0.0, "y": 0.0, "duration_ms": 100},
    )
    _send_with_retry("camera_lock_release", "release_stick", {"stick_id": camera_lock_stick_id})

    for phase_index, phase in enumerate(phase_plan):
        phase_name = str(phase.get("name", f"phase_{phase_index + 1}")).strip() or f"phase_{phase_index + 1}"
        phase_duration = max(0.1, _safe_float(phase.get("duration_seconds"), 0.1))
        phase_x = max(-1.0, min(1.0, _safe_float(phase.get("move_x"), 0.0)))
        phase_y = max(-1.0, min(1.0, _safe_float(phase.get("move_y"), 0.0)))
        _run_move_phase(phase_name, phase_duration, phase_x, phase_y)

        if bool(phase.get("jump_after", False)):
            jump_accepted = _send_sequence_command(
                f"jump_after_{phase_name}",
                "tap_button",
                {"button_id": jump_button_id, "duration_ms": jump_duration_ms},
            )
            if not jump_accepted:
                _send_with_retry(
                    f"jump_after_{phase_name}_retry",
                    "tap_button",
                    {"button_id": jump_button_id, "duration_ms": jump_duration_ms},
                )
            if jump_settle_seconds > 0:
                time.sleep(jump_settle_seconds)

    final_player_state = client.get_player_state(session_id=session_id)
    result["final_state"]["player_state"] = dict(final_player_state)
    result["success"]["success_condition"] = "sequence_completed"
    result["checks"]["scenario_flow"] = True
    _finalize_step_record(
        step,
        status="passed",
        observation=observation,
        started_at_monotonic=step_started_at_monotonic,
    )


def _run_workflow_steps(
    client: UnrealTestClient,
    result: Dict[str, Any],
    *,
    session_id: str,
    scenario_definition: Mapping[str, Any],
    poll_interval: float,
) -> None:
    steps = scenario_definition.get("steps", [])
    success_criteria = scenario_definition.get("success_criteria", {})
    failure_criteria = scenario_definition.get("failure_criteria", {})
    assertions = scenario_definition.get("assertions", [])
    if not isinstance(steps, Sequence):
        raise E2ERunnerError("scenario.steps must be an array.")

    timeout_seconds = _safe_float(
        success_criteria.get("timeout_seconds") if isinstance(success_criteria, Mapping) else None,
        60.0,
    )
    completion_state = str(
        success_criteria.get("completion_state") if isinstance(success_criteria, Mapping) else "steps_completed"
    ).strip() or "steps_completed"
    input_failure_limit = _safe_int(
        failure_criteria.get("input_failure_limit") if isinstance(failure_criteria, Mapping) else None,
        3,
    )

    step = _create_step_record(
        "workflow_steps",
        command="workflow_execute",
        request_args={
            "step_count": len(steps),
            "timeout_seconds": timeout_seconds,
            "input_failure_limit": input_failure_limit,
        },
    )
    result["steps"].append(step)
    step_started_at_monotonic = time.monotonic()
    deadline = step_started_at_monotonic + max(1.0, timeout_seconds)
    command_log: list[Dict[str, Any]] = []
    context: Dict[str, Any] = {
        "player_state": {},
        "target_state": {},
        "spatial_state": {},
        "success": result.get("success", {}),
    }
    observation: Dict[str, Any] = {
        "command_log": command_log,
        "workflow": {
            "step_count": len(steps),
            "timeout_seconds": timeout_seconds,
            "completion_state": completion_state,
        },
        "assertions": [],
    }

    cursor = _safe_sequence(client.get_events(session_id=session_id, limit=1).get("last_sequence"), 0)

    def _fail_workflow(
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
        response: Optional[Mapping[str, Any]] = None,
    ) -> None:
        failure = _make_failure("workflow_steps", code, message, details=details)
        _finalize_step_record(
            step,
            status="failed",
            response=response,
            observation=observation,
            failure=failure,
            started_at_monotonic=step_started_at_monotonic,
        )
        raise E2ERunnerError(message)

    def _check_timeout() -> None:
        if time.monotonic() >= deadline:
            _fail_workflow(
                "overall_timeout",
                f"Workflow exceeded timeout ({timeout_seconds} seconds).",
                details={"timeout_seconds": timeout_seconds},
            )

    def _refresh_context() -> None:
        player_state = client.get_player_state(session_id=session_id)
        target_state = client.get_target_state(session_id=session_id)
        spatial_state = client.get_spatial_state(session_id=session_id)
        context["player_state"] = dict(player_state)
        context["target_state"] = dict(target_state)
        context["spatial_state"] = dict(spatial_state)
        context["success"] = dict(result.get("success", {}))
        result["final_state"]["player_state"] = dict(player_state)
        result["final_state"]["target_state"] = dict(target_state)
        result["final_state"]["spatial_state"] = dict(spatial_state)

    def _send_logged_command(name: str, command: str, request_args: Mapping[str, Any]) -> Mapping[str, Any]:
        consecutive_input_failures = 0
        while True:
            _check_timeout()
            started_at = time.monotonic()
            response = _send_command(client, session_id=session_id, command=command, request_args=request_args)
            accepted = bool(response.get("accepted", False))
            record: Dict[str, Any] = {
                "name": name,
                "command": command,
                "request_args": dict(request_args),
                "accepted": accepted,
                "error_code": response.get("error_code"),
                "error_message": response.get("error_message"),
                "duration_seconds": round(max(0.0, time.monotonic() - started_at), 3),
            }
            details = response.get("details")
            if isinstance(details, Mapping):
                input_execution = details.get("input_execution")
                if isinstance(input_execution, Mapping):
                    for key in (
                        "input_key",
                        "input_mode",
                        "tap_duration_ms",
                        "release_scheduled",
                        "release_delay_seconds",
                        "jump_fallback_used",
                    ):
                        if key in input_execution:
                            record[key] = input_execution.get(key)
            command_log.append(record)

            if accepted:
                return response

            error_code = str(response.get("error_code", "command_rejected"))
            if error_code == "input_execution_failed":
                consecutive_input_failures += 1
                if consecutive_input_failures < max(1, input_failure_limit):
                    time.sleep(max(0.02, poll_interval))
                    continue
                _fail_workflow(
                    "input_execution_failed_limit",
                    f"{name} failed repeatedly due to input execution errors.",
                    details={"input_failure_limit": input_failure_limit},
                    response=response,
                )
            _fail_workflow(
                error_code,
                str(response.get("error_message", f"{name} command was rejected.")),
                details={"error_stage": response.get("error_stage")},
                response=response,
            )

    def _run_move_phase(name: str, args: Mapping[str, Any]) -> None:
        stick_id = str(args.get("stick_id", "left_stick")).strip() or "left_stick"
        axis_x = max(-1.0, min(1.0, _safe_float(args.get("x"), 0.0)))
        axis_y = max(-1.0, min(1.0, _safe_float(args.get("y"), 0.0)))
        duration_seconds = max(0.1, _safe_float(args.get("duration_seconds"), 0.1))
        pulse_interval = max(0.05, min(1.0, _safe_float(args.get("pulse_interval_seconds"), 0.1)))
        duration_ms = max(50, _safe_int(args.get("duration_ms"), int(round(pulse_interval * 1000.0))))

        phase_started = time.monotonic()
        pulse_index = 0
        while (time.monotonic() - phase_started) < duration_seconds:
            pulse_index += 1
            _send_logged_command(
                f"{name}_move_{pulse_index}",
                "move_stick",
                {"stick_id": stick_id, "x": axis_x, "y": axis_y, "duration_ms": duration_ms},
            )
            result["checks"]["approach"] = True
            time.sleep(max(0.01, min(pulse_interval, poll_interval if poll_interval > 0 else pulse_interval)))
        _send_logged_command(f"{name}_release", "release_stick", {"stick_id": stick_id})

    def _run_move_to_location(name: str, args: Mapping[str, Any]) -> None:
        target_x = _safe_float(args.get("x"), 0.0)
        target_y = _safe_float(args.get("y"), 0.0)
        tolerance_cm = max(1.0, _safe_float(args.get("tolerance_cm"), 30.0))
        max_seconds = max(0.1, _safe_float(args.get("max_seconds"), 30.0))
        stick_id = str(args.get("stick_id", "left_stick")).strip() or "left_stick"
        pulse_interval = max(0.05, min(1.0, _safe_float(args.get("pulse_interval_seconds"), 0.1)))
        duration_ms = max(50, _safe_int(args.get("duration_ms"), int(round(pulse_interval * 1000.0))))
        phase_deadline = time.monotonic() + max_seconds
        pulse_index = 0

        while True:
            _check_timeout()
            if time.monotonic() >= phase_deadline:
                _send_logged_command(f"{name}_release", "release_stick", {"stick_id": stick_id})
                _fail_workflow(
                    "move_to_location_timeout",
                    f"{name} could not reach target location within {max_seconds} seconds.",
                    details={
                        "target_x": target_x,
                        "target_y": target_y,
                        "tolerance_cm": tolerance_cm,
                    },
                )

            _refresh_context()
            player_state = context.get("player_state", {})
            if not isinstance(player_state, Mapping):
                player_state = {}
            location = player_state.get("location", {})
            if not isinstance(location, Mapping):
                location = {}
            current_x = _safe_float(location.get("x"), 0.0)
            current_y = _safe_float(location.get("y"), 0.0)
            delta_x = target_x - current_x
            delta_y = target_y - current_y
            distance_cm = math.hypot(delta_x, delta_y)
            if distance_cm <= tolerance_cm:
                _send_logged_command(f"{name}_release", "release_stick", {"stick_id": stick_id})
                return

            norm = max(distance_cm, 1e-6)
            stick_y = max(-1.0, min(1.0, delta_x / norm))
            stick_x = max(-1.0, min(1.0, delta_y / norm))
            pulse_index += 1
            _send_logged_command(
                f"{name}_move_to_{pulse_index}",
                "move_stick",
                {"stick_id": stick_id, "x": stick_x, "y": stick_y, "duration_ms": duration_ms},
            )
            result["checks"]["approach"] = True
            time.sleep(max(0.01, min(pulse_interval, poll_interval if poll_interval > 0 else pulse_interval)))

    def _run_defeat_target(name: str, args: Mapping[str, Any]) -> None:
        nonlocal cursor
        attack_max_attempts = max(1, _safe_int(args.get("attack_max_attempts"), 12))
        attack_interval_seconds = max(0.0, _safe_float(args.get("attack_interval_seconds"), 0.15))
        post_attack_settle_seconds = max(0.0, _safe_float(args.get("post_attack_settle_seconds"), 0.1))
        for attack_index in range(attack_max_attempts):
            _check_timeout()
            _send_logged_command(f"{name}_attack_{attack_index + 1}", "attack", dict(args.get("command_args", {})))
            result["checks"]["attack"] = True
            if post_attack_settle_seconds > 0:
                time.sleep(post_attack_settle_seconds)
            _refresh_context()
            target_state = context.get("target_state", {})
            if isinstance(target_state, Mapping) and not bool(target_state.get("alive", True)):
                result["success"]["target_alive"] = False
                result["success"]["success_condition"] = "target_state.alive=false"
                return
            actor_died_event, cursor = _read_actor_died_event(client, session_id, cursor)
            if actor_died_event is not None:
                result["success"]["actor_died_event_detected"] = True
                result["success"]["success_condition"] = "actor_died_event"
                return
            if attack_interval_seconds > 0:
                time.sleep(attack_interval_seconds)
        _fail_workflow(
            "target_survived",
            f"{name} failed: target is still alive after {attack_max_attempts} attack attempts.",
            details={"attack_max_attempts": attack_max_attempts},
        )

    _refresh_context()
    for index, step_definition in enumerate(steps):
        _check_timeout()
        if not isinstance(step_definition, Mapping):
            _fail_workflow("invalid_step", f"Step at index {index} is not an object.")
        step_name = str(step_definition.get("name", f"step_{index + 1}")).strip() or f"step_{index + 1}"
        action = str(step_definition.get("action", "")).strip()

        _refresh_context()
        when = step_definition.get("when")
        if isinstance(when, Mapping):
            passed, details = _evaluate_condition(when, context)
            command_log.append(
                {
                    "name": step_name,
                    "command": action,
                    "accepted": passed,
                    "skipped": not passed,
                    "condition": details,
                }
            )
            if not passed:
                continue

        if action == "command":
            command_name = str(step_definition.get("command", "")).strip()
            if not command_name:
                _fail_workflow("invalid_step", f"{step_name} requires a non-empty command.")
            raw_args = step_definition.get("args", {})
            command_args = dict(raw_args) if isinstance(raw_args, Mapping) else {}
            _send_logged_command(step_name, command_name, command_args)
            if command_name == "move_stick":
                result["checks"]["approach"] = True
            if command_name == "attack":
                result["checks"]["attack"] = True
        elif action == "wait":
            seconds = max(0.0, _safe_float(step_definition.get("seconds"), 0.0))
            time.sleep(seconds)
            command_log.append(
                {
                    "name": step_name,
                    "command": "wait",
                    "accepted": True,
                    "duration_seconds": round(seconds, 3),
                }
            )
        elif action == "move_phase":
            raw_args = step_definition.get("args", {})
            args_map = dict(raw_args) if isinstance(raw_args, Mapping) else {}
            _run_move_phase(step_name, args_map)
        elif action == "move_to_location":
            raw_args = step_definition.get("args", {})
            args_map = dict(raw_args) if isinstance(raw_args, Mapping) else {}
            _run_move_to_location(step_name, args_map)
        elif action == "defeat_target":
            raw_args = step_definition.get("args", {})
            args_map = dict(raw_args) if isinstance(raw_args, Mapping) else {}
            _run_defeat_target(step_name, args_map)
        else:
            _fail_workflow("unsupported_action", f"{step_name} uses unsupported action '{action}'.")

        _refresh_context()

    if isinstance(assertions, Sequence):
        for assertion_index, assertion in enumerate(assertions):
            if not isinstance(assertion, Mapping):
                _fail_workflow("invalid_assertion", f"Assertion at index {assertion_index} is not an object.")
            passed, details = _evaluate_condition(assertion, context)
            assertion_name = str(assertion.get("name", f"assertion_{assertion_index + 1}")).strip() or f"assertion_{assertion_index + 1}"
            assertion_record = {
                "name": assertion_name,
                "passed": passed,
                "details": details,
                "message": assertion.get("message"),
            }
            if isinstance(observation.get("assertions"), list):
                observation["assertions"].append(assertion_record)
            if not passed:
                _fail_workflow(
                    "assertion_failed",
                    str(assertion.get("message", f"{assertion_name} failed.")),
                    details=details,
                )

    result["success"]["success_condition"] = completion_state
    result["checks"]["scenario_flow"] = True
    _finalize_step_record(
        step,
        status="passed",
        observation=observation,
        started_at_monotonic=step_started_at_monotonic,
    )


def run_e2e(args: argparse.Namespace) -> Dict[str, Any]:
    started_at_monotonic = time.monotonic()
    run_id = args.run_id or generate_run_id(prefix="e2e")
    session_id = args.session_id or generate_session_id(run_id, 1, prefix="session")
    artifacts_root = args.artifacts_root.expanduser().resolve()
    run_dir = artifacts_root / "runs" / run_id
    report_path = run_dir / "report.json"
    mode = "launch" if args.launch else "attach"

    result: Dict[str, Any] = {
        "ok": False,
        "run_id": run_id,
        "session_id": session_id,
        "mode": mode,
        "scenario": "default",
        "base_url": args.base_url,
        "started_at_utc": utc_now_iso(),
        "ended_at_utc": None,
        "duration_seconds": None,
        "launch": {"enabled": bool(args.launch), "mode": mode},
        "checks": {
            "health": False,
            "capabilities": False,
            "session_start": False,
            "equip": False,
            "approach": False,
            "attack": False,
            "scenario_flow": False,
            "session_stop": False,
        },
        "artifacts": {
            "root": str(artifacts_root),
            "report_path": str(report_path),
        },
        "artifacts_root": str(artifacts_root),
        "report_path": str(report_path),
        "steps": [],
        "success": {
            "target_alive": None,
            "actor_died_event_detected": False,
            "success_condition": None,
        },
        "failure": None,
        "capabilities": {},
        "final_state": {},
        "notes": [],
    }

    launch_ctx: Optional[_LaunchContext] = None
    started_session = False
    termination_mode = args.termination_mode or "keep_running"
    client = UnrealTestClient(
        args.base_url,
        timeout=args.request_timeout,
        retry_attempts=args.retry_attempts,
        retry_backoff=args.retry_backoff,
    )

    try:
        scenario_definition, scenario_source = _load_scenario_definition(args, run_dir=run_dir)
        scenario_intent = str(scenario_definition.get("intent", args.scenario or "default")).strip()
        result["scenario"] = scenario_intent or "default"
        result["notes"].append(f"scenario_source:{scenario_source}")
        result["notes"].append(f"scenario_validated_path:{run_dir / 'scenario.validated.json'}")

        scenario_termination = scenario_definition.get("termination", {})
        if isinstance(scenario_termination, Mapping):
            candidate_mode = str(scenario_termination.get("mode", args.termination_mode)).strip()
            if candidate_mode in TERMINATION_MODES:
                termination_mode = candidate_mode
        result["notes"].append(f"termination_mode:{termination_mode}")

        success_criteria = scenario_definition.get("success_criteria", {})
        failure_criteria = scenario_definition.get("failure_criteria", {})
        target_selector = scenario_definition.get("target_selector", {})
        overall_timeout_seconds = _safe_float(
            success_criteria.get("timeout_seconds") if isinstance(success_criteria, Mapping) else None,
            args.overall_timeout_seconds,
        )
        target_lost_timeout_seconds = _safe_float(
            failure_criteria.get("target_lost_timeout_seconds") if isinstance(failure_criteria, Mapping) else None,
            args.target_lost_timeout_seconds,
        )
        max_consecutive_input_failures = _safe_int(
            failure_criteria.get("input_failure_limit") if isinstance(failure_criteria, Mapping) else None,
            args.max_consecutive_input_failures,
        )
        front_cone_half_angle_degrees = _safe_float(
            target_selector.get("yaw_degrees") if isinstance(target_selector, Mapping) else None,
            args.front_cone_half_angle_degrees,
        )

        launch_ctx = _start_unreal_if_requested(args, run_id=run_id, session_id=session_id, run_dir=run_dir)
        if launch_ctx is not None:
            result["launch"]["pid"] = launch_ctx.process.pid
            result["launch"]["log_path"] = str(launch_ctx.log_path)
            result["artifacts"]["log_path"] = str(launch_ctx.log_path)

        health = _wait_until_healthy(client, timeout=args.health_timeout, poll_interval=args.poll_interval)
        result["health"] = health
        result["checks"]["health"] = True

        capabilities = client.get_capabilities()
        result["capabilities"] = {
            "version": capabilities.get("version"),
            "events_websocket_url": capabilities.get("events_websocket_url"),
            "events_websocket_port": capabilities.get("events_websocket_port"),
        }
        result["checks"]["capabilities"] = True

        session_start = client.start_session(
            session_id=session_id,
            run_id=run_id,
            options={
                "auto_play_editor": bool(args.auto_play_editor),
                "auto_play_wait_seconds": max(0.0, args.auto_play_wait_seconds),
            },
        )
        if not bool(session_start.get("accepted", False)):
            raise E2ERunnerError("session_start was not accepted.")
        started_session = True
        session_id = str(session_start.get("session_id", session_id))
        result["session_id"] = session_id
        result["session_start"] = session_start
        result["checks"]["session_start"] = True
        auto_play_status_available = ("auto_play_editor_requested" in session_start) or (
            "auto_play_editor_ready" in session_start
        )
        if "auto_play_editor_requested" in session_start:
            result["notes"].append(f"auto_play_editor_requested:{session_start.get('auto_play_editor_requested')}")
        if "auto_play_editor_ready" in session_start:
            result["notes"].append(f"auto_play_editor_ready:{session_start.get('auto_play_editor_ready')}")
        if session_start.get("auto_play_editor_error"):
            result["notes"].append(f"auto_play_editor_error:{session_start.get('auto_play_editor_error')}")
        if args.auto_play_editor and not auto_play_status_available:
            result["notes"].append("auto_play_editor_status_unavailable:server_may_be_stale")
            if args.require_auto_play_editor:
                raise E2ERunnerError(
                    "session_start response does not include auto_play_editor status fields. "
                    "Rebuild UnrealAgentTest module and retry."
                )

        cursor = _safe_sequence(client.get_events(session_id=session_id, limit=1).get("last_sequence"), 0)

        if scenario_intent == SUPPORTED_WORKFLOW_INTENT:
            _run_workflow_steps(
                client,
                result,
                session_id=session_id,
                scenario_definition=scenario_definition,
                poll_interval=args.poll_interval,
            )
            stop_response = client.stop_session(session_id=session_id)
            result["session_stop"] = stop_response
            result["checks"]["session_stop"] = bool(stop_response.get("accepted", False))
            started_session = False
            result["ok"] = True
            return result

        if scenario_intent == SUPPORTED_MOVEMENT_INTENT:
            _run_movement_jump_sequence(
                client,
                result,
                session_id=session_id,
                scenario_definition=scenario_definition,
                poll_interval=args.poll_interval,
            )
            stop_response = client.stop_session(session_id=session_id)
            result["session_stop"] = stop_response
            result["checks"]["session_stop"] = bool(stop_response.get("accepted", False))
            started_session = False
            result["ok"] = True
            return result

        if scenario_intent != SUPPORTED_DEFEAT_INTENT:
            raise E2ERunnerError(
                f"Unsupported scenario intent for current runner flow: {scenario_intent}"
            )

        equip_args = {"recipe_id": args.equip_recipe_id}
        weapon_value = scenario_definition.get("weapon")
        equip_recipe_args: Dict[str, str] = _parse_key_value_args(args.equip_recipe_arg) if args.equip_recipe_arg else {}
        if isinstance(weapon_value, str) and weapon_value.strip() and "weapon" not in equip_recipe_args:
            equip_recipe_args["weapon"] = weapon_value.strip()
        if equip_recipe_args:
            equip_args["args"] = equip_recipe_args
        equip_step = _send_command_step(
            client,
            result,
            name="equip",
            command="execute_recipe",
            session_id=session_id,
            request_args=equip_args,
        )
        player_after_equip = client.get_player_state(session_id=session_id)
        equip_step["observation"] = {
            "equipped_weapon_id": player_after_equip.get("equipped_weapon_id"),
            "current_action": player_after_equip.get("current_action"),
            "scenario_weapon": weapon_value,
        }
        result["checks"]["equip"] = True

        engage_step = _create_step_record(
            "engage",
            command="state_driven_engage",
            request_args={
                "front_cone_half_angle_degrees": front_cone_half_angle_degrees,
                "overall_timeout_seconds": overall_timeout_seconds,
                "target_lost_timeout_seconds": target_lost_timeout_seconds,
                "max_consecutive_input_failures": max_consecutive_input_failures,
                "attack_max_attempts": args.attack_max_attempts,
            },
        )
        result["steps"].append(engage_step)
        engage_started_at_monotonic = time.monotonic()
        engage_deadline = engage_started_at_monotonic + max(1.0, overall_timeout_seconds)
        movement_attempts: list[Dict[str, Any]] = []
        attack_attempts: list[Dict[str, Any]] = []
        consecutive_input_failures = 0
        target_lost_since: Optional[float] = None
        actor_died_event: Optional[Mapping[str, Any]] = None
        final_target_state: Optional[Mapping[str, Any]] = None
        action_cycles = 0
        engage_observation: Dict[str, Any] = {
            "movement_attempts": movement_attempts,
            "attack_attempts": attack_attempts,
            "target_selector": {
                "half_angle_degrees": front_cone_half_angle_degrees,
            },
        }

        def _fail_engage(
            code: str,
            message: str,
            *,
            details: Optional[Mapping[str, Any]] = None,
            response: Optional[Mapping[str, Any]] = None,
        ) -> None:
            failure = _make_failure("engage", code, message, details=details)
            _finalize_step_record(
                engage_step,
                status="failed",
                response=response,
                observation=engage_observation,
                failure=failure,
                started_at_monotonic=engage_started_at_monotonic,
            )
            raise E2ERunnerError(message)

        while True:
            now = time.monotonic()
            if now >= engage_deadline:
                _fail_engage(
                    "overall_timeout",
                    f"Failed to defeat target within {overall_timeout_seconds} seconds.",
                    details={
                        "overall_timeout_seconds": overall_timeout_seconds,
                        "attack_attempts": len(attack_attempts),
                        "movement_attempts": len(movement_attempts),
                    },
                )

            action_cycles += 1
            spatial_state = client.get_spatial_state(session_id=session_id)
            target_state = client.get_target_state(session_id=session_id)
            final_target_state = target_state

            actor_died_event, cursor = _read_actor_died_event(client, session_id, cursor)
            if actor_died_event is not None:
                result["success"]["actor_died_event_detected"] = True
                result["success"]["success_condition"] = "actor_died_event"
                break

            target_alive = bool(target_state.get("alive", True))
            if not target_alive:
                result["success"]["target_alive"] = False
                result["success"]["success_condition"] = "target_state.alive=false"
                break

            target_actor_id = str(spatial_state.get("target_actor_id") or target_state.get("actor_id") or "").strip()
            if not target_actor_id:
                if target_lost_since is None:
                    target_lost_since = now
                elif (now - target_lost_since) >= max(1.0, target_lost_timeout_seconds):
                    _fail_engage(
                        "target_lost_timeout",
                        "Target could not be tracked long enough to continue combat.",
                        details={
                            "target_lost_timeout_seconds": target_lost_timeout_seconds,
                        },
                    )
            else:
                target_lost_since = None

            yaw_delta = abs(_safe_float(spatial_state.get("yaw_delta_degrees"), 9999.0))
            in_front = yaw_delta <= max(1.0, front_cone_half_angle_degrees)
            in_attack_range = bool(spatial_state.get("target_in_attack_range", False))

            if in_front and in_attack_range:
                attack_started_at = time.monotonic()
                attack_response = _send_command(client, session_id=session_id, command="attack", request_args={})
                attack_record: Dict[str, Any] = {
                    "index": len(attack_attempts) + 1,
                    "accepted": bool(attack_response.get("accepted", False)),
                    "duration_seconds": None,
                    "error_code": attack_response.get("error_code"),
                    "error_message": attack_response.get("error_message"),
                }

                if not attack_record["accepted"]:
                    error_code = str(attack_response.get("error_code", "command_rejected"))
                    attack_record["duration_seconds"] = round(max(0.0, time.monotonic() - attack_started_at), 3)
                    attack_attempts.append(attack_record)
                    if error_code == "input_execution_failed":
                        consecutive_input_failures += 1
                        if consecutive_input_failures >= max(1, max_consecutive_input_failures):
                            _fail_engage(
                                "input_execution_failed_limit",
                                "Attack failed repeatedly due to input execution errors.",
                                details={
                                    "max_consecutive_input_failures": max_consecutive_input_failures,
                                    "last_error_message": attack_response.get("error_message"),
                                },
                                response=attack_response,
                            )
                        time.sleep(max(0.05, args.poll_interval))
                        continue

                    _fail_engage(
                        error_code,
                        str(attack_response.get("error_message", "Attack command was rejected.")),
                        details={"error_stage": attack_response.get("error_stage")},
                        response=attack_response,
                    )

                consecutive_input_failures = 0
                result["checks"]["attack"] = True
                if not result["checks"]["approach"]:
                    result["checks"]["approach"] = True

                if args.post_attack_settle_seconds > 0.0:
                    time.sleep(args.post_attack_settle_seconds)

                final_target_state = client.get_target_state(session_id=session_id)
                actor_died_event, cursor = _read_actor_died_event(client, session_id, cursor)

                attack_record["duration_seconds"] = round(max(0.0, time.monotonic() - attack_started_at), 3)
                attack_record["target_alive"] = bool(final_target_state.get("alive", True))
                attack_record["target_health"] = final_target_state.get("health")
                attack_record["actor_died_event"] = dict(actor_died_event) if actor_died_event is not None else None
                attack_attempts.append(attack_record)

                if actor_died_event is not None:
                    result["success"]["actor_died_event_detected"] = True
                    result["success"]["success_condition"] = "actor_died_event"
                    break
                if not bool(final_target_state.get("alive", True)):
                    result["success"]["target_alive"] = False
                    result["success"]["success_condition"] = "target_state.alive=false"
                    break

                if len(attack_attempts) >= max(1, args.attack_max_attempts):
                    _fail_engage(
                        "target_survived",
                        f"Target was still alive after {args.attack_max_attempts} attack attempts.",
                        details={
                            "attack_attempts": len(attack_attempts),
                            "target_health": final_target_state.get("health"),
                        },
                    )

                if args.attack_interval_seconds > 0.0:
                    time.sleep(args.attack_interval_seconds)
                continue

            stick_x = _safe_float(spatial_state.get("recommended_left_stick_x"), args.approach_x)
            stick_y = _safe_float(spatial_state.get("recommended_left_stick_y"), args.approach_y)
            move_request_args = {
                "stick_id": args.approach_stick_id,
                "x": stick_x,
                "y": stick_y,
                "duration_ms": args.approach_duration_ms,
            }
            move_started_at = time.monotonic()
            move_response = _send_command(client, session_id=session_id, command="move_stick", request_args=move_request_args)
            movement_record: Dict[str, Any] = {
                "index": len(movement_attempts) + 1,
                "request_args": move_request_args,
                "accepted": bool(move_response.get("accepted", False)),
                "duration_seconds": None,
                "error_code": move_response.get("error_code"),
                "error_message": move_response.get("error_message"),
                "yaw_delta_degrees": spatial_state.get("yaw_delta_degrees"),
                "target_in_attack_range": spatial_state.get("target_in_attack_range"),
            }

            if not movement_record["accepted"]:
                error_code = str(move_response.get("error_code", "command_rejected"))
                movement_record["duration_seconds"] = round(max(0.0, time.monotonic() - move_started_at), 3)
                movement_attempts.append(movement_record)
                failure_info = _make_failure(
                    "approach",
                    error_code,
                    str(move_response.get("error_message", "move_stick command was rejected.")),
                )
                tolerate = (not args.strict_approach) and _should_tolerate_approach_failure(failure_info)
                if tolerate:
                    consecutive_input_failures += 1
                    if consecutive_input_failures >= max(1, max_consecutive_input_failures):
                        _fail_engage(
                            "input_execution_failed_limit",
                            "Approach failed repeatedly due to axis input execution errors.",
                            details={
                                "max_consecutive_input_failures": max_consecutive_input_failures,
                                "last_error_message": move_response.get("error_message"),
                            },
                            response=move_response,
                        )
                    time.sleep(max(0.05, args.poll_interval))
                    continue

                _fail_engage(
                    error_code,
                    str(move_response.get("error_message", "move_stick command was rejected.")),
                    details={"error_stage": move_response.get("error_stage")},
                    response=move_response,
                )

            release_response = _send_command(
                client,
                session_id=session_id,
                command="release_stick",
                request_args={"stick_id": args.approach_stick_id},
            )
            movement_record["release_accepted"] = bool(release_response.get("accepted", False))
            movement_record["duration_seconds"] = round(max(0.0, time.monotonic() - move_started_at), 3)
            movement_attempts.append(movement_record)
            consecutive_input_failures = 0
            result["checks"]["approach"] = True
            time.sleep(max(0.05, args.poll_interval))

        if final_target_state is None:
            final_target_state = client.get_target_state(session_id=session_id)
        result["success"]["target_alive"] = bool(final_target_state.get("alive", True))
        result["success"]["actor_died_event_detected"] = actor_died_event is not None
        result["final_state"]["target_state"] = dict(final_target_state)

        engage_observation["action_cycles"] = action_cycles
        engage_observation["consecutive_input_failures"] = consecutive_input_failures
        if actor_died_event is not None:
            engage_observation["actor_died_event"] = dict(actor_died_event)
        _finalize_step_record(
            engage_step,
            status="passed",
            observation=engage_observation,
            started_at_monotonic=engage_started_at_monotonic,
        )
        result["checks"]["scenario_flow"] = True

        stop_response = client.stop_session(session_id=session_id)
        result["session_stop"] = stop_response
        result["checks"]["session_stop"] = bool(stop_response.get("accepted", False))
        started_session = False
        result["ok"] = True
        return result
    except Exception as exc:  # noqa: BLE001
        if result["failure"] is None:
            for step in reversed(result["steps"]):
                failure = step.get("failure")
                if isinstance(failure, Mapping):
                    result["failure"] = dict(failure)
                    break
            if result["failure"] is None:
                result["failure"] = _make_failure(
                    "runner",
                    type(exc).__name__,
                    str(exc),
                )
        return result
    finally:
        if started_session:
            try:
                cleanup_response = client.stop_session(session_id=session_id)
                result["session_stop_cleanup"] = cleanup_response
            except Exception as exc:  # noqa: BLE001
                result["notes"].append(f"session_stop_cleanup_failed:{type(exc).__name__}:{exc}")

        if launch_ctx is not None:
            if args.keep_process:
                result["notes"].append("launched_process_kept_alive:override")
            elif (not bool(result.get("ok", False))) and args.keep_process_on_failure:
                result["notes"].append("launched_process_kept_alive:run_failed")
            elif termination_mode == "keep_running":
                result["notes"].append("launched_process_kept_alive")
            else:
                try:
                    result["launch"]["termination"] = _terminate_process(
                        launch_ctx.process,
                        grace_seconds=args.terminate_grace_seconds,
                    )
                except Exception as exc:  # noqa: BLE001
                    result["launch"]["termination_error"] = f"{type(exc).__name__}: {exc}"
            try:
                launch_ctx.log_stream.close()
            except Exception:  # noqa: BLE001
                pass
        elif termination_mode != "keep_running":
            result["notes"].append(f"termination_mode_not_applied_in_attach:{termination_mode}")

        result["ended_at_utc"] = utc_now_iso()
        result["duration_seconds"] = round(max(0.0, time.monotonic() - started_at_monotonic), 3)
        _write_json(report_path, result)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run validated E2E scenarios against Unreal Test Remote API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:31001", help="Remote API base URL.")
    parser.add_argument("--session-id", default=None, help="Optional explicit session id.")
    parser.add_argument("--run-id", default=None, help="Optional explicit run id.")
    parser.add_argument("--request-timeout", type=float, default=5.0, help="HTTP/WS request timeout seconds.")
    parser.add_argument("--retry-attempts", type=int, default=2, help="HTTP retry attempts.")
    parser.add_argument("--retry-backoff", type=float, default=0.25, help="HTTP retry backoff seconds.")
    parser.add_argument("--health-timeout", type=float, default=90.0, help="Health wait timeout seconds.")
    parser.add_argument("--poll-interval", type=float, default=0.25, help="Polling interval seconds.")
    parser.add_argument(
        "--auto-play-editor",
        dest="auto_play_editor",
        action="store_true",
        default=True,
        help="Request editor PIE auto-start on session_start when needed.",
    )
    parser.add_argument(
        "--no-auto-play-editor",
        dest="auto_play_editor",
        action="store_false",
        help="Disable editor PIE auto-start request on session_start.",
    )
    parser.add_argument(
        "--auto-play-wait-seconds",
        type=float,
        default=15.0,
        help="Maximum wait for editor PIE auto-start readiness on session_start.",
    )
    parser.add_argument(
        "--require-auto-play-editor",
        action="store_true",
        help=(
            "Fail fast when session_start does not expose auto_play_editor status fields. "
            "Use this to enforce rebuilt server binaries."
        ),
    )
    parser.add_argument(
        "--scenario-json",
        default="",
        help="실행할 시나리오 JSON 문자열.",
    )
    parser.add_argument(
        "--scenario-file",
        type=Path,
        default=None,
        help="실행할 시나리오 JSON 파일 경로.",
    )
    parser.add_argument(
        "--termination-mode",
        default=None,
        choices=sorted(TERMINATION_MODES),
        help="테스트 종료 시 프로세스 종료 정책(생략 시 시나리오 값 사용, 기본 keep_running).",
    )
    parser.add_argument(
        "--front-cone-half-angle-degrees",
        type=float,
        default=45.0,
        help="정면 판정 반각(도).",
    )
    parser.add_argument(
        "--overall-timeout-seconds",
        type=float,
        default=90.0,
        help="시나리오 전체 타임아웃(초).",
    )
    parser.add_argument(
        "--target-lost-timeout-seconds",
        type=float,
        default=10.0,
        help="타겟 상실 허용 시간(초).",
    )
    parser.add_argument(
        "--max-consecutive-input-failures",
        type=int,
        default=3,
        help="연속 input_execution_failed 허용 횟수.",
    )

    parser.add_argument("--equip-recipe-id", default="equip", help="Recipe id used for the equip step.")
    parser.add_argument(
        "--equip-recipe-arg",
        action="append",
        default=[],
        help="Optional recipe arg in key=value format. Can be specified multiple times.",
    )
    parser.add_argument("--approach-stick-id", default="left_stick", help="Stick id used for the approach step.")
    parser.add_argument("--approach-x", type=float, default=0.0, help="Fallback approach X when spatial state does not provide one.")
    parser.add_argument("--approach-y", type=float, default=1.0, help="Fallback approach Y when spatial state does not provide one.")
    parser.add_argument("--approach-duration-ms", type=int, default=250, help="Stick hold duration for the approach step.")
    parser.add_argument(
        "--strict-approach",
        action="store_true",
        help="Fail immediately when approach(move_stick) is rejected instead of tolerating known axis-input unsupported cases.",
    )
    parser.add_argument("--attack-max-attempts", type=int, default=12, help="Maximum attack attempts before failing.")
    parser.add_argument(
        "--attack-interval-seconds",
        type=float,
        default=0.15,
        help="Delay between attack attempts after the first one.",
    )
    parser.add_argument(
        "--post-attack-settle-seconds",
        type=float,
        default=0.1,
        help="Wait time after each attack before checking state/events.",
    )

    parser.add_argument("--launch", action="store_true", help="Launch UnrealEditor with -TestMode before the E2E run.")
    parser.add_argument("--unreal-executable", default=DEFAULT_UNREAL_EXECUTABLE, help="Path to UnrealEditor executable.")
    parser.add_argument("--uproject", default=DEFAULT_UPROJECT, help="Path to .uproject file.")
    parser.add_argument("--port", type=int, default=None, help="Port override used when --launch is enabled.")
    parser.add_argument("--scenario", default=None, help="Optional scenario argument passed to Unreal.")
    parser.add_argument("--extra-arg", action="append", default=[], help="Extra argument for Unreal process.")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path.cwd() / "Artifacts" / "E2ERunner",
        help="Artifacts root directory for E2E reports/logs.",
    )
    parser.add_argument(
        "--terminate-grace-seconds",
        type=float,
        default=5.0,
        help="Grace seconds before kill fallback when terminating launched Unreal process.",
    )
    parser.add_argument("--keep-process", action="store_true", help="Do not terminate launched Unreal process.")
    parser.add_argument(
        "--keep-process-on-failure",
        dest="keep_process_on_failure",
        action="store_true",
        default=True,
        help="Keep launched Unreal process alive when run fails (default: enabled).",
    )
    parser.add_argument(
        "--no-keep-process-on-failure",
        dest="keep_process_on_failure",
        action="store_false",
        help="Terminate launched Unreal process on failure according to termination_mode.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    summary = run_e2e(args)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0 if summary.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
