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
from uuid import uuid4

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
    SUPPORTED_VISION_NAVIGATION_INTENT,
    SUPPORTED_WORKFLOW_INTENT,
    TERMINATION_MODES,
    validate_scenario,
)
from Tools.UnrealTestClient.unreal_test_client import (  # noqa: E402
    UnrealTestClient,
    UnrealTestClientError,
)


VISION_NAVIGATION_ALLOWED_ACTIONS = ("move_stick", "release_stick", "tap_button", "wait", "camera_yaw")
VISION_NAVIGATION_ALLOWED_STATUSES = ("continue", "success", "failure")
VISION_NAVIGATION_ALLOWED_SUCCESS_MODES = ("position", "visual", "hybrid")
VISION_NAVIGATION_DEFAULT_CAPTURE_HEIGHT = 360
VISION_NAVIGATION_DEFAULT_CAPTURE_JPEG_QUALITY = 60
VISION_NAVIGATION_DEFAULT_CAPTURE_PRESERVE_ASPECT_RATIO = True
VISION_NAVIGATION_DEFAULT_DECIDE_WAIT_TIMEOUT_SECONDS = 30.0
VISION_NAVIGATION_DEFAULT_DECIDE_RETRY_COUNT = 1
MOVEMENT_DECIDER_DEFAULT_DECIDE_WAIT_TIMEOUT_SECONDS = 30.0
MOVEMENT_DECIDER_DEFAULT_DECIDE_RETRY_COUNT = 1
MOVEMENT_DECIDER_DEFAULT_DECIDE_POLL_INTERVAL_SECONDS = 0.1


class E2ERunnerError(RuntimeError):
    """Raised when the end-to-end scenario cannot be completed."""


@dataclass
class _LaunchContext:
    process: subprocess.Popen[Any]
    log_path: Path
    log_stream: Any
    command_line: str


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
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _start_unreal_if_requested(
    args: argparse.Namespace,
    *,
    run_id: str,
    session_id: str,
    run_dir: Path,
) -> Optional[_LaunchContext]:
    if not args.launch:
        return None

    launch_mode = str(args.launch_mode).strip().lower()
    launch_extra_args = list(args.extra_arg)
    if launch_mode == "game":
        has_game_flag = any(str(arg).strip().lower() == "-game" for arg in launch_extra_args)
        if not has_game_flag:
            launch_extra_args.append("-game")

    target_port = args.port if args.port is not None else _extract_port_from_base_url(args.base_url)
    command = build_unreal_command(
        unreal_executable=args.unreal_executable,
        uproject=args.uproject,
        session_id=session_id,
        port=target_port,
        run_id=run_id,
        scenario=args.scenario,
        extra_args=launch_extra_args,
    )
    if launch_mode == "game":
        argv = command.get("argv", [])
        if not any(str(arg).strip().lower() == "-game" for arg in argv):
            raise E2ERunnerError("launch_mode=game requires '-game' flag in Unreal launch argv.")

    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "unreal.log"
    log_stream = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        command["argv"],
        cwd=command["working_directory"],
        stdout=log_stream,
        stderr=subprocess.STDOUT,
    )
    return _LaunchContext(
        process=process,
        log_path=log_path,
        log_stream=log_stream,
        command_line=str(command.get("command_line", "")),
    )


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


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


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


def _build_vision_navigation_bridge_paths(run_dir: Path, session_id: str) -> Dict[str, Path]:
    bridge_dir = run_dir / "bridge" / session_id
    return {
        "bridge_dir": bridge_dir,
        "observe_path": bridge_dir / "observe.json",
        "decide_path": bridge_dir / "decide.json",
        "lock_path": bridge_dir / "bridge.lock",
    }


def _write_vision_navigation_bridge_lock(
    lock_path: Path,
    *,
    run_id: str,
    session_id: str,
    iteration: int,
    status: str,
    details: Optional[Mapping[str, Any]] = None,
) -> None:
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "iteration": iteration,
        "status": status,
        "updated_at_utc": utc_now_iso(),
    }
    if details:
        payload["details"] = dict(details)
    _write_json(lock_path, payload)


def _extract_vision_navigation_position_target(goal: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    position_target = goal.get("position_target")
    if position_target is None:
        return None

    if isinstance(position_target, Mapping):
        x_value = _to_number(position_target.get("x"))
        y_value = _to_number(position_target.get("y"))
        tolerance_cm = _safe_float(position_target.get("tolerance_cm"), 50.0)
        if x_value is None or y_value is None:
            return None
        return {
            "x": x_value,
            "y": y_value,
            "tolerance_cm": max(0.1, tolerance_cm),
        }

    if isinstance(position_target, Sequence) and not isinstance(position_target, (str, bytes)):
        if len(position_target) < 2:
            return None
        x_value = _to_number(position_target[0])
        y_value = _to_number(position_target[1])
        tolerance_cm = 50.0
        if len(position_target) >= 3:
            tolerance_candidate = _to_number(position_target[2])
            if tolerance_candidate is not None:
                tolerance_cm = tolerance_candidate
        if x_value is None or y_value is None:
            return None
        return {
            "x": x_value,
            "y": y_value,
            "tolerance_cm": max(0.1, tolerance_cm),
        }

    return None


def _request_vision_navigation_capture(
    client: UnrealTestClient,
    *,
    session_id: str,
    capture_timeout_seconds: float,
    capture_config: Mapping[str, Any],
) -> Mapping[str, Any]:
    request_args = {
        "session_id": session_id,
        "height": _safe_int(capture_config.get("height"), VISION_NAVIGATION_DEFAULT_CAPTURE_HEIGHT),
        "preserve_aspect_ratio": bool(
            capture_config.get(
                "preserve_aspect_ratio",
                VISION_NAVIGATION_DEFAULT_CAPTURE_PRESERVE_ASPECT_RATIO,
            )
        ),
        "jpeg_quality": _safe_int(capture_config.get("jpeg_quality"), VISION_NAVIGATION_DEFAULT_CAPTURE_JPEG_QUALITY),
    }

    screenshot_callable = getattr(client, "get_screenshot", None)
    if callable(screenshot_callable):
        try:
            response = screenshot_callable(**request_args)
        except TypeError:
            request_args_no_session = dict(request_args)
            request_args_no_session.pop("session_id", None)
            response = screenshot_callable(**request_args_no_session)
        if isinstance(response, Mapping):
            return response
        raise E2ERunnerError("get_screenshot response is not a JSON object.")

    capture_client = UnrealTestClient(
        client.base_url,
        timeout=max(0.5, capture_timeout_seconds),
        retry_attempts=0,
        retry_backoff=0.0,
        session_id=session_id,
    )
    query = {
        "session_id": session_id,
        "height": str(request_args["height"]),
        "preserve_aspect_ratio": "true" if request_args["preserve_aspect_ratio"] else "false",
        "jpeg_quality": str(request_args["jpeg_quality"]),
    }
    response = capture_client._request("GET", "/capture/screenshot", query=query)
    if isinstance(response, Mapping):
        return response
    raise E2ERunnerError("capture screenshot response is not a JSON object.")


def _summarize_vision_navigation_capture_response(response: Mapping[str, Any]) -> Dict[str, Any]:
    viewport_state = response.get("viewport_state")
    if not isinstance(viewport_state, Mapping):
        viewport_state = {}

    image_field_name = None
    image_value = None
    for candidate in ("image_base64", "jpeg_base64", "base64_jpeg", "image", "jpeg"):
        candidate_value = response.get(candidate)
        if isinstance(candidate_value, str) and candidate_value:
            image_field_name = candidate
            image_value = candidate_value
            break

    summary: Dict[str, Any] = {
        "captured_session_id": response.get("captured_session_id"),
        "image_field": image_field_name,
        "image_base64": image_value,
        "viewport_state": dict(viewport_state),
        "image_meta": {
            "width": response.get("width"),
            "height": response.get("height"),
            "content_type": response.get("content_type") or response.get("mime_type"),
            "jpeg_quality": response.get("jpeg_quality"),
            "preserve_aspect_ratio": response.get("preserve_aspect_ratio"),
        },
        "response_keys": sorted(str(key) for key in response.keys()),
    }
    if image_value is not None:
        summary["image_meta"]["image_characters"] = len(image_value)
    for key in ("capture_source", "is_minimized", "is_occluded", "is_focused", "viewport_width", "viewport_height"):
        if key in viewport_state:
            summary["image_meta"][key] = viewport_state.get(key)
    error_code = response.get("error_code")
    if error_code is None:
        error_code = response.get("error")
    if isinstance(error_code, str) and error_code.strip():
        summary["error_code"] = error_code

    error_message = response.get("error_message")
    if error_message is None:
        error_message = response.get("message")
    if isinstance(error_message, str) and error_message.strip():
        summary["error_message"] = error_message
    return summary


def _classify_vision_navigation_capture_failure(response: Mapping[str, Any]) -> Optional[str]:
    error_code = response.get("error_code")
    if error_code is None:
        error_code = response.get("error")
    error_code = str(error_code or "").strip().lower()
    if error_code in {"viewport_minimized", "viewport_occluded", "capture_timeout", "capture_unavailable"}:
        return error_code

    image_fields = ("image_base64", "jpeg_base64", "base64_jpeg", "image", "jpeg")
    has_image_payload = any(
        isinstance(response.get(field), str) and str(response.get(field)).strip()
        for field in image_fields
    )

    viewport_state = response.get("viewport_state")
    if isinstance(viewport_state, Mapping):
        capture_source = str(viewport_state.get("capture_source", "")).strip().lower()
        viewport_source = capture_source in {"game_viewport", "pie_viewport"}
        if bool(viewport_state.get("is_minimized", False)) and (viewport_source or not has_image_payload):
            return "viewport_minimized"
        if bool(viewport_state.get("is_occluded", False)) and (viewport_source or not has_image_payload):
            return "viewport_occluded"

    if not has_image_payload:
        return "capture_unavailable"
    return None


def _is_valid_vector_payload(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    x_value = payload.get("x")
    y_value = payload.get("y")
    z_value = payload.get("z")
    if not _is_number(x_value) or not _is_number(y_value):
        return False
    if z_value is not None and not _is_number(z_value):
        return False
    return True


def _wait_for_session_ready(
    client: UnrealTestClient,
    *,
    session_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    require_capture_ready: bool,
    capture_timeout_seconds: float,
    stable_capture_count: int,
    capture_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    started_at_monotonic = time.monotonic()
    deadline = started_at_monotonic + max(0.1, timeout_seconds)
    poll_interval = max(0.05, poll_interval_seconds)
    stable_capture_target = max(1, stable_capture_count)

    summary: Dict[str, Any] = {
        "ready": False,
        "started_at_utc": utc_now_iso(),
        "ready_at_utc": None,
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval,
        "require_capture_ready": bool(require_capture_ready),
        "capture_timeout_seconds": capture_timeout_seconds,
        "stable_capture_count": stable_capture_target,
        "attempts": 0,
        "stable_capture_hits": 0,
        "last_player_ready": False,
        "last_spatial_ready": False,
        "last_capture_ready": (not require_capture_ready),
        "last_capture_failure_code": None,
        "last_capture_error": None,
        "last_viewport_state": {},
        "elapsed_seconds": None,
    }

    capture_client = UnrealTestClient(
        client.base_url,
        timeout=max(0.5, capture_timeout_seconds),
        retry_attempts=0,
        retry_backoff=0.0,
        session_id=session_id,
    )
    capture_request_config = dict(capture_config) if isinstance(capture_config, Mapping) else {}

    while time.monotonic() < deadline:
        summary["attempts"] = int(summary["attempts"]) + 1

        player_ready = False
        spatial_ready = False
        capture_ready = not require_capture_ready
        capture_failure_code: Optional[str] = None
        capture_error: Optional[str] = None
        viewport_state: Dict[str, Any] = {}

        try:
            player_state = client.get_player_state(session_id=session_id)
            if isinstance(player_state, Mapping):
                actor_id = str(player_state.get("actor_id") or "").strip()
                player_location = player_state.get("location")
                player_ready = bool(actor_id) and _is_valid_vector_payload(player_location)
        except Exception as exc:  # noqa: BLE001
            player_ready = False
            capture_error = f"player_state:{type(exc).__name__}:{exc}"

        try:
            spatial_state = client.get_spatial_state(session_id=session_id)
            if isinstance(spatial_state, Mapping):
                spatial_actor_id = str(spatial_state.get("player_actor_id") or "").strip()
                spatial_location = spatial_state.get("player_location")
                spatial_ready = bool(spatial_actor_id) and _is_valid_vector_payload(spatial_location)
        except Exception as exc:  # noqa: BLE001
            spatial_ready = False
            if capture_error is None:
                capture_error = f"spatial_state:{type(exc).__name__}:{exc}"

        if require_capture_ready:
            try:
                capture_response = _request_vision_navigation_capture(
                    capture_client,
                    session_id=session_id,
                    capture_timeout_seconds=capture_timeout_seconds,
                    capture_config=capture_request_config,
                )
                if isinstance(capture_response, Mapping):
                    raw_viewport_state = capture_response.get("viewport_state")
                    if isinstance(raw_viewport_state, Mapping):
                        viewport_state = dict(raw_viewport_state)
                    capture_failure_code = _classify_vision_navigation_capture_failure(capture_response)
                    if capture_failure_code is None:
                        summary["stable_capture_hits"] = int(summary["stable_capture_hits"]) + 1
                        capture_ready = int(summary["stable_capture_hits"]) >= stable_capture_target
                    else:
                        summary["stable_capture_hits"] = 0
                        capture_ready = False
                else:
                    capture_failure_code = "capture_unavailable"
                    summary["stable_capture_hits"] = 0
                    capture_ready = False
            except Exception as exc:  # noqa: BLE001
                lowered = str(exc).lower()
                if "timeout" in lowered or "timed out" in lowered:
                    capture_failure_code = "capture_timeout"
                else:
                    capture_failure_code = "capture_unavailable"
                capture_error = f"capture:{type(exc).__name__}:{exc}"
                summary["stable_capture_hits"] = 0
                capture_ready = False

        summary["last_player_ready"] = player_ready
        summary["last_spatial_ready"] = spatial_ready
        summary["last_capture_ready"] = capture_ready
        summary["last_capture_failure_code"] = capture_failure_code
        summary["last_capture_error"] = capture_error
        summary["last_viewport_state"] = dict(viewport_state)

        if player_ready and spatial_ready and capture_ready:
            summary["ready"] = True
            summary["ready_at_utc"] = utc_now_iso()
            summary["elapsed_seconds"] = round(max(0.0, time.monotonic() - started_at_monotonic), 3)
            return summary

        time.sleep(poll_interval)

    summary["ready"] = False
    summary["elapsed_seconds"] = round(max(0.0, time.monotonic() - started_at_monotonic), 3)
    return summary


def _validate_vision_navigation_decision(
    decision: Mapping[str, Any],
    *,
    run_id: str,
    session_id: str,
    iteration: int,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(decision, Mapping):
        return ["decide.json must be a JSON object"]

    if decision.get("schema_version", 1) != 1:
        errors.append("decide.json.schema_version must be 1")
    if decision.get("run_id") != run_id:
        errors.append("decide.json.run_id must match the current run_id")
    if decision.get("session_id") != session_id:
        errors.append("decide.json.session_id must match the current session_id")
    if decision.get("iteration") != iteration:
        errors.append("decide.json.iteration must match the current iteration")

    status = decision.get("status")
    if status not in VISION_NAVIGATION_ALLOWED_STATUSES:
        errors.append(
            f"decide.json.status must be one of {', '.join(VISION_NAVIGATION_ALLOWED_STATUSES)}"
        )

    if "success" in decision and not isinstance(decision.get("success"), bool):
        errors.append("decide.json.success must be a boolean when provided")

    if "success_mode" in decision and decision.get("success_mode") not in VISION_NAVIGATION_ALLOWED_SUCCESS_MODES:
        errors.append(
            f"decide.json.success_mode must be one of {', '.join(VISION_NAVIGATION_ALLOWED_SUCCESS_MODES)}"
        )

    if "reason" in decision and (not isinstance(decision.get("reason"), str) or not str(decision.get("reason")).strip()):
        errors.append("decide.json.reason must be a non-empty string when provided")

    actions = decision.get("actions")
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
        errors.append("decide.json.actions must be an array")
        return errors

    for index, action in enumerate(actions):
        scope = f"decide.json.actions[{index}]"
        if not isinstance(action, Mapping):
            errors.append(f"{scope} must be an object")
            continue

        action_name = str(action.get("action", "")).strip()
        if action_name not in VISION_NAVIGATION_ALLOWED_ACTIONS:
            errors.append(f"{scope}.action must be one of {', '.join(VISION_NAVIGATION_ALLOWED_ACTIONS)}")
            continue

        args = action.get("args", {})
        if args is not None and not isinstance(args, Mapping):
            errors.append(f"{scope}.args must be an object when provided")
            continue

        args_map = dict(args) if isinstance(args, Mapping) else {}
        if action_name == "move_stick":
            for key in ("stick_id", "x", "y"):
                if key not in args_map:
                    errors.append(f"{scope}.args.{key} is required")
            if "stick_id" in args_map and (not isinstance(args_map.get("stick_id"), str) or not str(args_map.get("stick_id")).strip()):
                errors.append(f"{scope}.args.stick_id must be a non-empty string")
            for key in ("x", "y"):
                if key in args_map and not _is_number(args_map.get(key)):
                    errors.append(f"{scope}.args.{key} must be a number")
            if "duration_ms" in args_map and (not isinstance(args_map.get("duration_ms"), int) or isinstance(args_map.get("duration_ms"), bool)):
                errors.append(f"{scope}.args.duration_ms must be an integer when provided")
        elif action_name == "release_stick":
            if "stick_id" not in args_map:
                errors.append(f"{scope}.args.stick_id is required")
            elif not isinstance(args_map.get("stick_id"), str) or not str(args_map.get("stick_id")).strip():
                errors.append(f"{scope}.args.stick_id must be a non-empty string")
        elif action_name == "tap_button":
            if "button_id" not in args_map:
                errors.append(f"{scope}.args.button_id is required")
            elif not isinstance(args_map.get("button_id"), str) or not str(args_map.get("button_id")).strip():
                errors.append(f"{scope}.args.button_id must be a non-empty string")
            if "duration_ms" in args_map and (not isinstance(args_map.get("duration_ms"), int) or isinstance(args_map.get("duration_ms"), bool)):
                errors.append(f"{scope}.args.duration_ms must be an integer when provided")
        elif action_name == "wait":
            if "seconds" not in args_map:
                errors.append(f"{scope}.args.seconds is required")
            elif not _is_number(args_map.get("seconds")):
                errors.append(f"{scope}.args.seconds must be a number")
            elif float(args_map.get("seconds")) < 0.0:
                errors.append(f"{scope}.args.seconds must be >= 0")
        elif action_name == "camera_yaw":
            if "degrees" not in args_map and "delta_degrees" not in args_map:
                errors.append(f"{scope}.args.degrees or {scope}.args.delta_degrees is required")
            if "degrees" in args_map and not _is_number(args_map.get("degrees")):
                errors.append(f"{scope}.args.degrees must be a number")
            if "delta_degrees" in args_map and not _is_number(args_map.get("delta_degrees")):
                errors.append(f"{scope}.args.delta_degrees must be a number")
            if "duration_ms" in args_map and (not isinstance(args_map.get("duration_ms"), int) or isinstance(args_map.get("duration_ms"), bool)):
                errors.append(f"{scope}.args.duration_ms must be an integer when provided")

    return errors


def _validate_movement_decider_decision(
    decision: Mapping[str, Any],
    *,
    run_id: str,
    session_id: str,
    iteration: int,
) -> list[str]:
    errors = _validate_vision_navigation_decision(
        decision,
        run_id=run_id,
        session_id=session_id,
        iteration=iteration,
    )
    filtered_errors = [
        error
        for error in errors
        if not error.startswith("decide.json.success_mode")
    ]
    if "phase_completed" in decision and not isinstance(decision.get("phase_completed"), bool):
        filtered_errors.append("decide.json.phase_completed must be a boolean when provided")
    return filtered_errors


def _normalize_vision_navigation_action(action: Mapping[str, Any]) -> Dict[str, Any]:
    action_name = str(action.get("action", "")).strip()
    args = action.get("args", {})
    args_map = dict(args) if isinstance(args, Mapping) else {}

    if action_name == "move_stick":
        normalized = {
            "stick_id": str(args_map.get("stick_id", "")).strip(),
            "x": _safe_float(args_map.get("x"), 0.0),
            "y": _safe_float(args_map.get("y"), 0.0),
        }
        if "duration_ms" in args_map:
            normalized["duration_ms"] = _safe_int(args_map.get("duration_ms"), 120)
        return normalized

    if action_name == "release_stick":
        return {"stick_id": str(args_map.get("stick_id", "")).strip()}

    if action_name == "tap_button":
        normalized = {
            "button_id": str(args_map.get("button_id", "")).strip(),
        }
        if "duration_ms" in args_map:
            normalized["duration_ms"] = _safe_int(args_map.get("duration_ms"), 120)
        return normalized

    if action_name == "wait":
        return {"seconds": max(0.0, _safe_float(args_map.get("seconds"), 0.0))}

    if action_name == "camera_yaw":
        degrees_value = args_map.get("degrees")
        if degrees_value is None:
            degrees_value = args_map.get("delta_degrees")
        normalized = {"degrees": _safe_float(degrees_value, 0.0)}
        if "duration_ms" in args_map:
            normalized["duration_ms"] = _safe_int(args_map.get("duration_ms"), 120)
        return normalized

    raise E2ERunnerError(f"Unsupported vision_navigation action: {action_name}")


def _evaluate_vision_navigation_success(
    *,
    success_mode: str,
    decision: Mapping[str, Any],
    player_state: Mapping[str, Any],
    goal_position_target: Optional[Mapping[str, Any]],
    viewport_state: Mapping[str, Any],
) -> tuple[bool, Dict[str, Any], str]:
    safety_ok = not bool(viewport_state.get("is_minimized", False)) and not bool(viewport_state.get("is_occluded", False))
    decision_success = bool(decision.get("success", False)) or str(decision.get("status", "")).strip().lower() == "success"

    result: Dict[str, Any] = {
        "success_mode": success_mode,
        "safety_ok": safety_ok,
        "decision_success": decision_success,
        "player_location": None,
        "goal_position_target": dict(goal_position_target) if isinstance(goal_position_target, Mapping) else None,
        "position_distance_cm": None,
        "position_reached": False,
        "visual_ready": False,
    }

    location = player_state.get("location")
    if isinstance(location, Mapping):
        result["player_location"] = {
            "x": _safe_float(location.get("x"), 0.0),
            "y": _safe_float(location.get("y"), 0.0),
            "z": _safe_float(location.get("z"), 0.0),
        }

    if isinstance(goal_position_target, Mapping):
        target_x = _safe_float(goal_position_target.get("x"), 0.0)
        target_y = _safe_float(goal_position_target.get("y"), 0.0)
        tolerance_cm = max(0.1, _safe_float(goal_position_target.get("tolerance_cm"), 50.0))
        if isinstance(location, Mapping):
            current_x = _safe_float(location.get("x"), 0.0)
            current_y = _safe_float(location.get("y"), 0.0)
            distance_cm = math.hypot(target_x - current_x, target_y - current_y)
            result["position_distance_cm"] = round(distance_cm, 3)
            result["position_reached"] = distance_cm <= tolerance_cm
        if result["position_reached"]:
            return True, result, "position_goal_reached"

    if success_mode == "position":
        return False, result, "position_pending"

    result["visual_ready"] = decision_success and safety_ok
    if success_mode == "visual":
        if result["visual_ready"]:
            return True, result, "visual_goal_reached"
        return False, result, "visual_pending"

    if success_mode == "hybrid":
        if result["visual_ready"]:
            return True, result, "hybrid_goal_reached"
        return False, result, "hybrid_pending"

    return False, result, "unknown_success_mode"


def _run_vision_navigation(
    client: UnrealTestClient,
    result: Dict[str, Any],
    *,
    run_id: str,
    run_dir: Path,
    session_id: str,
    scenario_definition: Mapping[str, Any],
    poll_interval: float,
    request_timeout: float,
) -> None:
    goal = scenario_definition.get("goal", {})
    success_criteria = scenario_definition.get("success_criteria", {})
    failure_criteria = scenario_definition.get("failure_criteria", {})
    loop_config = scenario_definition.get("loop", {})
    capture_config = scenario_definition.get("capture", {})
    decision_bridge = scenario_definition.get("decision_bridge", {})
    decision_policy = scenario_definition.get("decision_policy", {})
    if not all(
        isinstance(item, Mapping)
        for item in (
            goal,
            success_criteria,
            failure_criteria,
            loop_config,
            capture_config,
            decision_bridge,
            decision_policy,
        )
    ):
        raise E2ERunnerError("vision_navigation scenario fields must be objects.")

    timeout_seconds = _safe_float(success_criteria.get("timeout_seconds"), 240.0)
    success_mode = str(success_criteria.get("success_mode", "visual")).strip() or "visual"
    max_iterations = _safe_int(loop_config.get("max_iterations"), 120)
    observe_interval_seconds = max(0.05, _safe_float(loop_config.get("observe_interval_seconds"), max(poll_interval, 0.25)))
    capture_timeout_seconds = max(0.5, _safe_float(loop_config.get("capture_timeout_seconds"), 2.0))
    action_timeout_seconds = max(0.0, _safe_float(loop_config.get("action_timeout_seconds"), 3.0))
    input_failure_limit = _safe_int(failure_criteria.get("input_failure_limit"), 3)
    capture_failure_limit = _safe_int(failure_criteria.get("capture_failure_limit"), 1)
    decide_wait_timeout_seconds = max(1.0, _safe_float(decision_bridge.get("decide_wait_timeout_seconds"), VISION_NAVIGATION_DEFAULT_DECIDE_WAIT_TIMEOUT_SECONDS))
    decide_retry_count = max(0, _safe_int(decision_bridge.get("decide_retry_count"), VISION_NAVIGATION_DEFAULT_DECIDE_RETRY_COUNT))
    capture_height = _safe_int(capture_config.get("height"), VISION_NAVIGATION_DEFAULT_CAPTURE_HEIGHT)
    capture_jpeg_quality = _safe_int(capture_config.get("jpeg_quality"), VISION_NAVIGATION_DEFAULT_CAPTURE_JPEG_QUALITY)
    capture_preserve_aspect_ratio = bool(capture_config.get("preserve_aspect_ratio", VISION_NAVIGATION_DEFAULT_CAPTURE_PRESERVE_ASPECT_RATIO))
    goal_position_target = _extract_vision_navigation_position_target(goal)

    bridge_paths = _build_vision_navigation_bridge_paths(run_dir, session_id)
    bridge_dir = bridge_paths["bridge_dir"]
    observe_path = bridge_paths["observe_path"]
    decide_path = bridge_paths["decide_path"]
    lock_path = bridge_paths["lock_path"]
    bridge_dir.mkdir(parents=True, exist_ok=True)
    decide_path.unlink(missing_ok=True)

    step = _create_step_record(
        "vision_navigation",
        command="observe_decide_act_loop",
        request_args={
            "timeout_seconds": timeout_seconds,
            "success_mode": success_mode,
            "max_iterations": max_iterations,
            "observe_interval_seconds": observe_interval_seconds,
            "capture_timeout_seconds": capture_timeout_seconds,
            "action_timeout_seconds": action_timeout_seconds,
            "input_failure_limit": input_failure_limit,
            "capture_failure_limit": capture_failure_limit,
            "decide_wait_timeout_seconds": decide_wait_timeout_seconds,
            "decide_retry_count": decide_retry_count,
        },
    )
    result["steps"].append(step)
    step_started_at_monotonic = time.monotonic()
    deadline = step_started_at_monotonic + max(1.0, timeout_seconds)
    decision_poll_interval = max(0.05, min(observe_interval_seconds, poll_interval if poll_interval > 0 else observe_interval_seconds, 0.5))
    capture_client = UnrealTestClient(
        client.base_url,
        timeout=max(0.5, capture_timeout_seconds),
        retry_attempts=0,
        retry_backoff=0.0,
        session_id=session_id,
    )
    iterations: list[Dict[str, Any]] = []
    result["vision_navigation"] = {
        "intent": SUPPORTED_VISION_NAVIGATION_INTENT,
        "goal": {"description": goal.get("description"), "visual_target": goal.get("visual_target"), "position_target": dict(goal_position_target) if goal_position_target is not None else None},
        "success_mode": success_mode,
        "loop": {"max_iterations": max_iterations, "observe_interval_seconds": observe_interval_seconds, "capture_timeout_seconds": capture_timeout_seconds, "action_timeout_seconds": action_timeout_seconds},
        "capture": {"height": capture_height, "preserve_aspect_ratio": capture_preserve_aspect_ratio, "jpeg_quality": capture_jpeg_quality},
        "decision_bridge": {"mode": "file", "decide_wait_timeout_seconds": decide_wait_timeout_seconds, "decide_retry_count": decide_retry_count, "observe_path": str(observe_path), "decide_path": str(decide_path), "lock_path": str(lock_path)},
        "decision_policy": dict(decision_policy),
        "iterations": iterations,
        "final_observation": None,
        "final_decision": None,
        "success_evaluation": None,
    }
    result["notes"].append(f"vision_navigation_bridge_dir:{bridge_dir}")
    result["notes"].append(f"vision_navigation_success_mode:{success_mode}")
    if goal_position_target is not None:
        result["notes"].append("vision_navigation_position_target:" + json.dumps(goal_position_target, ensure_ascii=False, separators=(",", ":")))

    consecutive_input_failures = 0
    capture_failure_seen = 0

    def _fail(code: str, message: str, *, details: Optional[Mapping[str, Any]] = None, response: Optional[Mapping[str, Any]] = None, record: Optional[Dict[str, Any]] = None) -> None:
        failure = _make_failure("vision_navigation", code, message, details=details)
        if record is not None:
            record["failure"] = dict(failure)
            record["ended_at_utc"] = utc_now_iso()
            if record.get("started_at_monotonic") is not None:
                record["duration_seconds"] = round(max(0.0, time.monotonic() - float(record["started_at_monotonic"])), 3)
            record.pop("started_at_monotonic", None)
        _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=_safe_int(record.get("iteration") if record else 0, 0), status="failed", details={"code": code, "message": message})
        _finalize_step_record(step, status="failed", response=response, observation=result["vision_navigation"], failure=failure, started_at_monotonic=step_started_at_monotonic)
        raise E2ERunnerError(message)

    def _retry_capture_failure(
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
        response: Optional[Mapping[str, Any]] = None,
        record: Optional[Dict[str, Any]] = None,
    ) -> None:
        nonlocal capture_failure_seen
        capture_failure_seen += 1
        if capture_failure_seen >= capture_failure_limit:
            _fail(code, message, details=details, response=response, record=record)

        failure = _make_failure("vision_navigation", code, message, details=details)
        if record is not None:
            record["failure"] = dict(failure)
            record["status"] = "retryable_failure"
            record["ended_at_utc"] = utc_now_iso()
            if record.get("started_at_monotonic") is not None:
                record["duration_seconds"] = round(max(0.0, time.monotonic() - float(record["started_at_monotonic"])), 3)
            record.pop("started_at_monotonic", None)

        _write_vision_navigation_bridge_lock(
            lock_path,
            run_id=run_id,
            session_id=session_id,
            iteration=_safe_int(record.get("iteration") if record else 0, 0),
            status="retry_pending",
            details={
                "reason": code,
                "capture_failure_seen": capture_failure_seen,
                "capture_failure_limit": capture_failure_limit,
            },
        )
        time.sleep(observe_interval_seconds)

    def _timeout_check() -> None:
        if time.monotonic() >= deadline:
            _fail("overall_timeout", f"Vision navigation exceeded timeout ({timeout_seconds} seconds).", details={"timeout_seconds": timeout_seconds})

    def _wait_for_decision(iteration: int) -> Mapping[str, Any]:
        validation_failures = 0
        decision_deadline = time.monotonic() + decide_wait_timeout_seconds
        while time.monotonic() < decision_deadline:
            _timeout_check()
            if not decide_path.exists():
                time.sleep(decision_poll_interval)
                continue
            try:
                decision_payload = json.loads(decide_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                validation_failures += 1
                if validation_failures > decide_retry_count:
                    _fail("decision_validation_failed", "Vision decision validation failed.", details={"iteration": iteration, "error": f"{type(exc).__name__}: {exc}"})
                time.sleep(decision_poll_interval)
                continue
            if not isinstance(decision_payload, Mapping):
                validation_failures += 1
                if validation_failures > decide_retry_count:
                    _fail("decision_validation_failed", "Vision decision validation failed.", details={"iteration": iteration, "error": "decide.json must be a JSON object"})
                time.sleep(decision_poll_interval)
                continue
            validation_errors = _validate_vision_navigation_decision(decision_payload, run_id=run_id, session_id=session_id, iteration=iteration)
            if validation_errors:
                validation_failures += 1
                if validation_failures > decide_retry_count:
                    _fail("decision_validation_failed", "Vision decision validation failed.", details={"iteration": iteration, "errors": validation_errors})
                time.sleep(decision_poll_interval)
                continue
            return dict(decision_payload)
        _fail("decision_timeout", f"Timed out waiting for decide.json after {decide_wait_timeout_seconds} seconds.", details={"iteration": iteration, "timeout_seconds": decide_wait_timeout_seconds})

    iteration = 0
    while True:
        _timeout_check()
        if iteration >= max_iterations:
            _fail("max_iterations_reached", f"Vision navigation reached max_iterations ({max_iterations}) without success.", details={"max_iterations": max_iterations})
        iteration += 1
        decide_path.unlink(missing_ok=True)
        record: Dict[str, Any] = {"iteration": iteration, "started_at_utc": utc_now_iso(), "started_at_monotonic": time.monotonic(), "status": "running", "observation": None, "decision": None, "actions": [], "success_evaluation": None, "failure": None}
        iterations.append(record)
        _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=iteration, status="observing")

        try:
            player_state = client.get_player_state(session_id=session_id)
            spatial_state = client.get_spatial_state(session_id=session_id)
        except UnrealTestClientError as exc:
            _fail("state_query_failed", f"Failed to read vision navigation state: {exc}", details={"iteration": iteration}, record=record)

        try:
            capture_response = _request_vision_navigation_capture(capture_client, session_id=session_id, capture_timeout_seconds=capture_timeout_seconds, capture_config={"height": capture_height, "preserve_aspect_ratio": capture_preserve_aspect_ratio, "jpeg_quality": capture_jpeg_quality})
        except UnrealTestClientError as exc:
            lowered = str(exc).lower()
            code = "capture_timeout" if ("timeout" in lowered or "timed out" in lowered) else "capture_unavailable"
            _retry_capture_failure(code, f"Viewport capture failed: {exc}", details={"iteration": iteration, "capture_failure_seen": capture_failure_seen + 1}, record=record)
            continue
        except Exception as exc:  # noqa: BLE001
            _retry_capture_failure("capture_unavailable", f"Viewport capture failed: {exc}", details={"iteration": iteration, "capture_failure_seen": capture_failure_seen + 1}, record=record)
            continue

        if not isinstance(capture_response, Mapping):
            _retry_capture_failure("capture_unavailable", "Viewport capture response was not a JSON object.", details={"iteration": iteration, "capture_failure_seen": capture_failure_seen + 1}, record=record)
            continue

        capture_failure_code = _classify_vision_navigation_capture_failure(capture_response)
        if capture_failure_code is not None:
            if capture_failure_code in {"viewport_minimized", "viewport_occluded"}:
                _fail(
                    capture_failure_code,
                    f"Viewport capture failed with {capture_failure_code}.",
                    details={"iteration": iteration, "capture_failure_seen": capture_failure_seen},
                    response=capture_response,
                    record=record,
                )
            _retry_capture_failure(
                capture_failure_code,
                f"Viewport capture failed with {capture_failure_code}.",
                details={"iteration": iteration, "capture_failure_seen": capture_failure_seen + 1},
                response=capture_response,
                record=record,
            )
            continue

        capture_failure_seen = 0

        capture_summary = _summarize_vision_navigation_capture_response(capture_response)
        viewport_state = capture_summary.get("viewport_state", {})
        if not isinstance(viewport_state, Mapping):
            viewport_state = {}
        observe_payload = {
            "schema_version": 1,
            "kind": "vision_navigation_observe",
            "run_id": run_id,
            "session_id": session_id,
            "iteration": iteration,
            "captured_at_utc": utc_now_iso(),
            "intent": SUPPORTED_VISION_NAVIGATION_INTENT,
            "goal": result["vision_navigation"]["goal"],
            "success_criteria": {"timeout_seconds": timeout_seconds, "completion_state": "goal_reached", "success_mode": success_mode},
            "failure_criteria": {"input_failure_limit": input_failure_limit, "capture_failure_limit": capture_failure_limit},
            "loop": result["vision_navigation"]["loop"],
            "capture": result["vision_navigation"]["capture"],
            "decision_bridge": result["vision_navigation"]["decision_bridge"],
            "decision_policy": result["vision_navigation"]["decision_policy"],
            "observation": {"player_state": dict(player_state), "spatial_state": dict(spatial_state), "capture": dict(capture_summary), "position_target": dict(goal_position_target) if goal_position_target is not None else None},
        }
        record["observation"] = dict(observe_payload["observation"])
        _write_json(observe_path, observe_payload)
        _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=iteration, status="waiting_for_decision")

        position_ready, position_eval, position_condition = _evaluate_vision_navigation_success(success_mode=success_mode, decision={"success": False, "status": "continue"}, player_state=player_state, goal_position_target=goal_position_target, viewport_state=viewport_state)
        if position_ready:
            decision_payload = {"schema_version": 1, "run_id": run_id, "session_id": session_id, "iteration": iteration, "status": "success", "success": True, "success_mode": "position", "success_condition": position_condition, "reason": "position target reached before decision phase", "actions": []}
            record["decision"] = dict(decision_payload)
            record["success_evaluation"] = dict(position_eval)
            record["status"] = "passed"
            record["ended_at_utc"] = utc_now_iso()
            record["duration_seconds"] = round(max(0.0, time.monotonic() - float(record["started_at_monotonic"])), 3)
            record.pop("started_at_monotonic", None)
            result["success"]["success_condition"] = position_condition
            result["success"]["target_alive"] = None
            result["final_state"]["player_state"] = dict(player_state)
            result["final_state"]["spatial_state"] = dict(spatial_state)
            result["final_state"]["vision_navigation"] = {"goal_position_target": dict(goal_position_target) if goal_position_target is not None else None, "viewport_state": dict(viewport_state), "success_mode": success_mode, "success_condition": position_condition}
            result["vision_navigation"]["final_observation"] = dict(observe_payload["observation"])
            result["vision_navigation"]["final_decision"] = dict(decision_payload)
            result["vision_navigation"]["success_evaluation"] = dict(position_eval)
            result["checks"]["vision_navigation"] = True
            result["checks"]["scenario_flow"] = True
            _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=iteration, status="completed", details={"success_condition": position_condition, "outcome": "position"})
            _finalize_step_record(step, status="passed", observation=result["vision_navigation"], started_at_monotonic=step_started_at_monotonic)
            return

        decision_payload = _wait_for_decision(iteration)
        record["decision"] = dict(decision_payload)
        _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=iteration, status="decision_ready", details={"status": decision_payload.get("status"), "success": decision_payload.get("success")})
        if str(decision_payload.get("status", "")).strip().lower() == "failure":
            _fail("decision_failure", str(decision_payload.get("reason", "Vision decision reported failure.")), details={"iteration": iteration, "decision": decision_payload}, record=record)

        actions = decision_payload.get("actions", [])
        if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
            _fail("decision_validation_failed", "Vision decision actions must be an array.", details={"iteration": iteration}, record=record)

        retry_iteration = False
        for action_index, action in enumerate(actions):
            action_name = str(action.get("action", "")).strip()
            normalized_args = _normalize_vision_navigation_action(action)
            action_record: Dict[str, Any] = {
                "index": action_index + 1,
                "action": action_name,
                "request_args": dict(normalized_args),
                "accepted": None,
                "duration_seconds": None,
                "error_code": None,
                "error_message": None,
                "trace_id": None,
                "implementation_status": None,
            }
            record["actions"].append(action_record)
            _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=iteration, status="acting", details={"action_index": action_index + 1, "action": action_name})

            if action_name == "wait":
                started_action = time.monotonic()
                time.sleep(max(0.0, _safe_float(normalized_args.get("seconds"), 0.0)))
                action_record["accepted"] = True
                action_record["duration_seconds"] = round(max(0.0, time.monotonic() - started_action), 3)
                if action_timeout_seconds > 0.0 and action_record["duration_seconds"] > action_timeout_seconds:
                    _fail("action_timeout_exceeded", f"Wait action exceeded action_timeout_seconds ({action_timeout_seconds}).", details={"iteration": iteration, "action_index": action_index + 1, "duration_seconds": action_record["duration_seconds"]}, record=record)
                continue

            started_action = time.monotonic()
            response = _send_command(client, session_id=session_id, command=action_name, request_args=normalized_args)
            action_record["accepted"] = bool(response.get("accepted", False))
            action_record["duration_seconds"] = round(max(0.0, time.monotonic() - started_action), 3)
            action_record["error_code"] = response.get("error_code")
            action_record["error_message"] = response.get("error_message")
            action_record["trace_id"] = response.get("trace_id")
            action_record["implementation_status"] = response.get("implementation_status")
            response_details = response.get("details")
            if isinstance(response_details, Mapping):
                action_record["response_details"] = dict(response_details)
            if action_timeout_seconds > 0.0 and action_record["duration_seconds"] > action_timeout_seconds:
                _fail("action_timeout_exceeded", f"{action_name} exceeded action_timeout_seconds ({action_timeout_seconds}).", details={"iteration": iteration, "action_index": action_index + 1, "duration_seconds": action_record["duration_seconds"]}, response=response, record=record)
            if not action_record["accepted"]:
                error_code = str(response.get("error_code", "command_rejected"))
                if error_code == "input_execution_failed":
                    consecutive_input_failures += 1
                    if consecutive_input_failures >= input_failure_limit:
                        _fail("input_execution_failed_limit", "Vision navigation failed repeatedly due to input execution errors.", details={"iteration": iteration, "input_failure_limit": input_failure_limit, "last_error_message": response.get("error_message")}, response=response, record=record)
                    record["failure"] = {"code": error_code, "message": str(response.get("error_message", f"{action_name} command was rejected.")), "retryable": True}
                    retry_iteration = True
                    break
                _fail(error_code, str(response.get("error_message", f"{action_name} command was rejected.")), details={"iteration": iteration, "action_index": action_index + 1, "error_stage": response.get("error_stage")}, response=response, record=record)
            consecutive_input_failures = 0

        if retry_iteration:
            record["status"] = "retryable_failure"
            record["ended_at_utc"] = utc_now_iso()
            record["duration_seconds"] = round(max(0.0, time.monotonic() - float(record["started_at_monotonic"])), 3)
            record.pop("started_at_monotonic", None)
            _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=iteration, status="retry_pending", details={"reason": "input_execution_failed", "consecutive_input_failures": consecutive_input_failures})
            time.sleep(observe_interval_seconds)
            continue

        try:
            final_player_state = client.get_player_state(session_id=session_id)
            final_spatial_state = client.get_spatial_state(session_id=session_id)
        except UnrealTestClientError as exc:
            _fail("state_query_failed", f"Failed to read navigation state after actions: {exc}", details={"iteration": iteration}, record=record)

        position_ready, success_eval, success_condition = _evaluate_vision_navigation_success(success_mode=success_mode, decision=decision_payload, player_state=final_player_state, goal_position_target=goal_position_target, viewport_state=viewport_state)
        record["success_evaluation"] = dict(success_eval)
        result["final_state"]["player_state"] = dict(final_player_state)
        result["final_state"]["spatial_state"] = dict(final_spatial_state)
        result["final_state"]["vision_navigation"] = {"goal_position_target": dict(goal_position_target) if goal_position_target is not None else None, "viewport_state": dict(viewport_state), "success_mode": success_mode, "success_condition": success_condition}

        if position_ready:
            record["status"] = "passed"
            record["ended_at_utc"] = utc_now_iso()
            record["duration_seconds"] = round(max(0.0, time.monotonic() - float(record["started_at_monotonic"])), 3)
            record.pop("started_at_monotonic", None)
            result["success"]["success_condition"] = success_condition
            result["success"]["target_alive"] = None
            result["vision_navigation"]["final_observation"] = dict(observe_payload["observation"])
            result["vision_navigation"]["final_decision"] = dict(decision_payload)
            result["vision_navigation"]["success_evaluation"] = dict(success_eval)
            result["checks"]["vision_navigation"] = True
            result["checks"]["scenario_flow"] = True
            _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=iteration, status="completed", details={"success_condition": success_condition, "outcome": "success"})
            _finalize_step_record(step, status="passed", observation=result["vision_navigation"], started_at_monotonic=step_started_at_monotonic)
            result["notes"].append(f"vision_navigation_success_condition:{success_condition}")
            return

        record["status"] = "running"
        record["ended_at_utc"] = utc_now_iso()
        record["duration_seconds"] = round(max(0.0, time.monotonic() - float(record["started_at_monotonic"])), 3)
        record.pop("started_at_monotonic", None)
        _write_vision_navigation_bridge_lock(lock_path, run_id=run_id, session_id=session_id, iteration=iteration, status="continue", details={"success_mode": success_mode, "position_reached": success_eval.get("position_reached"), "visual_ready": success_eval.get("visual_ready")})
        time.sleep(observe_interval_seconds)

    _fail("goal_not_reached", "Vision navigation did not reach the goal condition.", details={"max_iterations": max_iterations})


def _run_movement_jump_sequence(
    client: UnrealTestClient,
    result: Dict[str, Any],
    *,
    run_id: str,
    run_dir: Path,
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
    decision_mode = str(sequence.get("decision_mode", "sequential")).strip().lower() or "sequential"
    decision_bridge_raw = sequence.get("decision_bridge", {})
    decision_bridge = dict(decision_bridge_raw) if isinstance(decision_bridge_raw, Mapping) else {}

    step = _create_step_record(
        "movement_jump_sequence",
        command="sequence_execute",
        request_args={
            "camera_lock_stick_id": camera_lock_stick_id,
            "move_stick_id": move_stick_id,
            "jump_button_id": jump_button_id,
            "decision_mode": decision_mode,
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
            "decision_mode": decision_mode,
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

    if decision_mode == "decider":
        bridge_paths = _build_vision_navigation_bridge_paths(run_dir, session_id)
        bridge_dir = bridge_paths["bridge_dir"]
        observe_path = bridge_paths["observe_path"]
        decide_path = bridge_paths["decide_path"]
        lock_path = bridge_paths["lock_path"]
        bridge_dir.mkdir(parents=True, exist_ok=True)

        decide_wait_timeout_seconds = max(
            1.0,
            _safe_float(
                decision_bridge.get("decide_wait_timeout_seconds"),
                MOVEMENT_DECIDER_DEFAULT_DECIDE_WAIT_TIMEOUT_SECONDS,
            ),
        )
        decide_retry_count = max(
            0,
            _safe_int(
                decision_bridge.get("decide_retry_count"),
                MOVEMENT_DECIDER_DEFAULT_DECIDE_RETRY_COUNT,
            ),
        )
        decide_poll_interval_seconds = max(
            0.02,
            _safe_float(
                decision_bridge.get("decide_poll_interval_seconds"),
                MOVEMENT_DECIDER_DEFAULT_DECIDE_POLL_INTERVAL_SECONDS,
            ),
        )

        observation["bridge"] = {
            "mode": "file",
            "observe_path": str(observe_path),
            "decide_path": str(decide_path),
            "lock_path": str(lock_path),
            "decide_wait_timeout_seconds": decide_wait_timeout_seconds,
            "decide_retry_count": decide_retry_count,
            "decide_poll_interval_seconds": decide_poll_interval_seconds,
        }
        result["notes"].append(f"movement_decider_bridge_dir:{bridge_dir}")
        _write_vision_navigation_bridge_lock(
            lock_path,
            run_id=run_id,
            session_id=session_id,
            iteration=0,
            status="initialized",
            details={"intent": SUPPORTED_MOVEMENT_INTENT},
        )

        def _wait_for_decision(iteration: int) -> Mapping[str, Any]:
            validation_failures = 0
            decision_deadline = time.monotonic() + decide_wait_timeout_seconds
            while time.monotonic() < decision_deadline:
                _check_timeout()
                if not decide_path.exists():
                    time.sleep(decide_poll_interval_seconds)
                    continue
                try:
                    decision_payload = json.loads(decide_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    validation_failures += 1
                    if validation_failures > decide_retry_count:
                        _fail_sequence(
                            "decision_validation_failed",
                            "Movement decider decision payload is invalid.",
                            details={"iteration": iteration},
                        )
                    time.sleep(decide_poll_interval_seconds)
                    continue
                if not isinstance(decision_payload, Mapping):
                    validation_failures += 1
                    if validation_failures > decide_retry_count:
                        _fail_sequence(
                            "decision_validation_failed",
                            "Movement decider decision payload must be an object.",
                            details={"iteration": iteration},
                        )
                    time.sleep(decide_poll_interval_seconds)
                    continue
                validation_errors = _validate_movement_decider_decision(
                    decision_payload,
                    run_id=run_id,
                    session_id=session_id,
                    iteration=iteration,
                )
                if validation_errors:
                    validation_failures += 1
                    if validation_failures > decide_retry_count:
                        _fail_sequence(
                            "decision_validation_failed",
                            "Movement decider decision validation failed.",
                            details={"iteration": iteration, "errors": validation_errors},
                        )
                    time.sleep(decide_poll_interval_seconds)
                    continue
                return dict(decision_payload)
            _fail_sequence(
                "decision_timeout",
                f"Timed out waiting for decide.json after {decide_wait_timeout_seconds} seconds.",
                details={"iteration": iteration},
            )

        _send_with_retry(
            "camera_lock_center",
            "move_stick",
            {"stick_id": camera_lock_stick_id, "x": 0.0, "y": 0.0, "duration_ms": 100},
        )
        _send_with_retry("camera_lock_release", "release_stick", {"stick_id": camera_lock_stick_id})

        for phase_index, phase in enumerate(phase_plan):
            _check_timeout()
            iteration = phase_index + 1
            decide_path.unlink(missing_ok=True)

            phase_name = str(phase.get("name", f"phase_{iteration}")).strip() or f"phase_{iteration}"
            try:
                player_state = client.get_player_state(session_id=session_id)
                spatial_state = client.get_spatial_state(session_id=session_id)
            except UnrealTestClientError as exc:
                _fail_sequence(
                    "state_query_failed",
                    f"Failed to read state before decision: {exc}",
                    details={"iteration": iteration, "phase_name": phase_name},
                )

            observe_payload: Dict[str, Any] = {
                "schema_version": 1,
                "kind": "movement_jump_observe",
                "run_id": run_id,
                "session_id": session_id,
                "iteration": iteration,
                "captured_at_utc": utc_now_iso(),
                "intent": SUPPORTED_MOVEMENT_INTENT,
                "sequence": {
                    "phase_count": len(phase_plan),
                    "phase_index": phase_index,
                    "phase_name": phase_name,
                    "phase": dict(phase),
                    "camera_lock_stick_id": camera_lock_stick_id,
                    "move_stick_id": move_stick_id,
                    "jump_button_id": jump_button_id,
                    "jump_duration_ms": jump_duration_ms,
                    "jump_settle_seconds": jump_settle_seconds,
                    "pulse_interval_seconds": pulse_interval_seconds,
                },
                "success_criteria": {
                    "timeout_seconds": timeout_seconds,
                    "completion_state": "sequence_completed",
                },
                "failure_criteria": {
                    "input_failure_limit": input_failure_limit,
                },
                "decision_bridge": dict(observation.get("bridge", {})),
                "observation": {
                    "player_state": dict(player_state) if isinstance(player_state, Mapping) else {},
                    "spatial_state": dict(spatial_state) if isinstance(spatial_state, Mapping) else {},
                    "command_log_size": len(command_log),
                },
            }
            _write_json(observe_path, observe_payload)
            _write_vision_navigation_bridge_lock(
                lock_path,
                run_id=run_id,
                session_id=session_id,
                iteration=iteration,
                status="waiting_for_decision",
                details={"phase_name": phase_name},
            )

            decision_payload = _wait_for_decision(iteration)
            decision_status = str(decision_payload.get("status", "")).strip().lower()
            if decision_status == "failure":
                _fail_sequence(
                    "decision_failure",
                    str(
                        decision_payload.get(
                            "reason",
                            f"Movement decider reported failure at {phase_name}.",
                        )
                    ),
                    details={"iteration": iteration, "phase_name": phase_name},
                )

            actions = decision_payload.get("actions", [])
            if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
                _fail_sequence(
                    "decision_validation_failed",
                    "Movement decider actions must be an array.",
                    details={"iteration": iteration},
                )

            for action_index, action in enumerate(actions):
                action_name = str(action.get("action", "")).strip()
                normalized_args = _normalize_vision_navigation_action(action)
                action_log_name = (
                    f"decider_phase_{iteration}_{phase_name}_{action_name}_{action_index + 1}"
                )
                _write_vision_navigation_bridge_lock(
                    lock_path,
                    run_id=run_id,
                    session_id=session_id,
                    iteration=iteration,
                    status="acting",
                    details={"phase_name": phase_name, "action_index": action_index + 1, "action": action_name},
                )

                if action_name == "wait":
                    wait_seconds = max(0.0, _safe_float(normalized_args.get("seconds"), 0.0))
                    time.sleep(wait_seconds)
                    command_log.append(
                        {
                            "name": action_log_name,
                            "command": "wait",
                            "request_args": {"seconds": wait_seconds},
                            "accepted": True,
                            "duration_seconds": round(wait_seconds, 3),
                        }
                    )
                    continue

                _send_with_retry(action_log_name, action_name, normalized_args)
                if action_name == "move_stick":
                    result["checks"]["approach"] = True

            _write_vision_navigation_bridge_lock(
                lock_path,
                run_id=run_id,
                session_id=session_id,
                iteration=iteration,
                status="phase_completed",
                details={"phase_name": phase_name, "decision_status": decision_status},
            )
            if decision_status == "success" or bool(decision_payload.get("success", False)):
                break

        final_player_state = client.get_player_state(session_id=session_id)
        result["final_state"]["player_state"] = dict(final_player_state)
        result["success"]["success_condition"] = "sequence_completed"
        result["checks"]["scenario_flow"] = True
        _write_vision_navigation_bridge_lock(
            lock_path,
            run_id=run_id,
            session_id=session_id,
            iteration=len(phase_plan),
            status="completed",
            details={"success_condition": "sequence_completed"},
        )
        _finalize_step_record(
            step,
            status="passed",
            observation=observation,
            started_at_monotonic=step_started_at_monotonic,
        )
        return

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

    launch_mode = str(args.launch_mode).strip().lower()
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
        "launch": {
            "enabled": bool(args.launch),
            "mode": mode,
            "launch_mode": launch_mode if bool(args.launch) else None,
        },
        "checks": {
            "health": False,
            "capabilities": False,
            "session_start": False,
            "session_ready": False,
            "equip": False,
            "approach": False,
            "attack": False,
            "vision_navigation": False,
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
            result["launch"]["command_line"] = launch_ctx.command_line
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

        effective_auto_play_editor = bool(args.auto_play_editor)
        if bool(args.launch) and launch_mode == "game":
            if effective_auto_play_editor:
                result["notes"].append("auto_play_editor_forced:false:launch_mode_game")
            effective_auto_play_editor = False

        session_start = client.start_session(
            session_id=session_id,
            run_id=run_id,
            options={
                "auto_play_editor": effective_auto_play_editor,
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
        if effective_auto_play_editor and not auto_play_status_available:
            result["notes"].append("auto_play_editor_status_unavailable:server_may_be_stale")
            if args.require_auto_play_editor:
                raise E2ERunnerError(
                    "session_start response does not include auto_play_editor status fields. "
                    "Rebuild UnrealAgentTest module and retry."
                )

        session_ready_config = scenario_definition.get("session_ready", {})
        if not isinstance(session_ready_config, Mapping):
            session_ready_config = {}
        session_ready_enabled = bool(session_ready_config.get("enabled", args.session_ready_gate))
        session_ready_timeout_seconds = max(
            0.1,
            _safe_float(session_ready_config.get("timeout_seconds"), args.session_ready_timeout_seconds),
        )
        session_ready_poll_interval_seconds = max(
            0.05,
            _safe_float(
                session_ready_config.get("poll_interval_seconds"),
                args.session_ready_poll_interval_seconds,
            ),
        )
        session_ready_capture_timeout_seconds = max(
            0.5,
            _safe_float(
                session_ready_config.get("capture_timeout_seconds"),
                args.session_ready_capture_timeout_seconds,
            ),
        )
        session_ready_stable_capture_count = max(
            1,
            _safe_int(
                session_ready_config.get("stable_capture_count"),
                args.session_ready_stable_capture_count,
            ),
        )
        session_ready_require_capture = bool(
            session_ready_config.get(
                "require_capture",
                scenario_intent == SUPPORTED_VISION_NAVIGATION_INTENT,
            )
        )
        capture_config_for_ready = scenario_definition.get("capture", {})
        if not isinstance(capture_config_for_ready, Mapping):
            capture_config_for_ready = {}

        if session_ready_enabled:
            session_ready_summary = _wait_for_session_ready(
                client,
                session_id=session_id,
                timeout_seconds=session_ready_timeout_seconds,
                poll_interval_seconds=session_ready_poll_interval_seconds,
                require_capture_ready=session_ready_require_capture,
                capture_timeout_seconds=session_ready_capture_timeout_seconds,
                stable_capture_count=session_ready_stable_capture_count,
                capture_config=capture_config_for_ready,
            )
            result["session_ready"] = session_ready_summary
            if bool(session_ready_summary.get("ready", False)):
                result["checks"]["session_ready"] = True
                result["notes"].append(
                    "session_ready_gate_passed:"
                    + json.dumps(
                        {
                            "elapsed_seconds": session_ready_summary.get("elapsed_seconds"),
                            "attempts": session_ready_summary.get("attempts"),
                            "stable_capture_hits": session_ready_summary.get("stable_capture_hits"),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            else:
                raise E2ERunnerError(
                    "Session ready gate timed out before world/player/capture became ready."
                )
        else:
            result["checks"]["session_ready"] = True
            result["session_ready"] = {
                "ready": True,
                "enabled": False,
                "reason": "disabled_by_configuration",
            }
            result["notes"].append("session_ready_gate_disabled")

        cursor = _safe_sequence(client.get_events(session_id=session_id, limit=1).get("last_sequence"), 0)

        if scenario_intent == SUPPORTED_VISION_NAVIGATION_INTENT:
            _run_vision_navigation(
                client,
                result,
                run_id=run_id,
                run_dir=run_dir,
                session_id=session_id,
                scenario_definition=scenario_definition,
                poll_interval=args.poll_interval,
                request_timeout=args.request_timeout,
            )
            stop_response = client.stop_session(session_id=session_id)
            result["session_stop"] = stop_response
            result["checks"]["session_stop"] = bool(stop_response.get("accepted", False))
            started_session = False
            result["ok"] = True
            return result

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
                run_id=run_id,
                run_dir=run_dir,
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
        "--session-ready-gate",
        dest="session_ready_gate",
        action="store_true",
        default=True,
        help="Wait for player/world readiness before starting scenario execution (default: enabled).",
    )
    parser.add_argument(
        "--no-session-ready-gate",
        dest="session_ready_gate",
        action="store_false",
        help="Disable session readiness gate.",
    )
    parser.add_argument(
        "--session-ready-timeout-seconds",
        type=float,
        default=20.0,
        help="Timeout for session readiness gate.",
    )
    parser.add_argument(
        "--session-ready-poll-interval-seconds",
        type=float,
        default=0.25,
        help="Polling interval for session readiness gate.",
    )
    parser.add_argument(
        "--session-ready-capture-timeout-seconds",
        type=float,
        default=2.0,
        help="Capture timeout used by session readiness gate when capture readiness is required.",
    )
    parser.add_argument(
        "--session-ready-stable-capture-count",
        type=int,
        default=2,
        help="Required number of consecutive successful captures for session readiness.",
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
    parser.add_argument(
        "--launch-mode",
        choices=("game", "editor"),
        default="game",
        help="Launch mode when --launch is enabled (default: game).",
    )
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
