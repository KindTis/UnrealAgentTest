from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
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
        "scenario": args.scenario or "default",
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
    client = UnrealTestClient(
        args.base_url,
        timeout=args.request_timeout,
        retry_attempts=args.retry_attempts,
        retry_backoff=args.retry_backoff,
    )

    try:
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

        session_start = client.start_session(session_id=session_id, run_id=run_id)
        if not bool(session_start.get("accepted", False)):
            raise E2ERunnerError("session_start was not accepted.")
        started_session = True
        session_id = str(session_start.get("session_id", session_id))
        result["session_id"] = session_id
        result["session_start"] = session_start
        result["checks"]["session_start"] = True

        cursor = _safe_sequence(client.get_events(session_id=session_id, limit=1).get("last_sequence"), 0)

        equip_args = {"recipe_id": args.equip_recipe_id}
        if args.equip_recipe_arg:
            equip_args["args"] = _parse_key_value_args(args.equip_recipe_arg)
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
        }
        result["checks"]["equip"] = True

        spatial_before_approach = client.get_spatial_state(session_id=session_id)
        stick_x = _safe_float(spatial_before_approach.get("recommended_left_stick_x"), args.approach_x)
        stick_y = _safe_float(spatial_before_approach.get("recommended_left_stick_y"), args.approach_y)
        approach_args = {
            "stick_id": args.approach_stick_id,
            "x": stick_x,
            "y": stick_y,
            "duration_ms": args.approach_duration_ms,
        }
        try:
            approach_step = _send_command_step(
                client,
                result,
                name="approach",
                command="move_stick",
                session_id=session_id,
                request_args=approach_args,
            )
            spatial_after_approach = client.get_spatial_state(session_id=session_id)
            approach_step["observation"] = {
                "distance_cm": spatial_after_approach.get("distance_cm"),
                "recommended_left_stick_x": spatial_after_approach.get("recommended_left_stick_x"),
                "recommended_left_stick_y": spatial_after_approach.get("recommended_left_stick_y"),
                "target_in_attack_range": spatial_after_approach.get("target_in_attack_range"),
            }
            _send_command_step(
                client,
                result,
                name="approach_release",
                command="release_stick",
                session_id=session_id,
                request_args={"stick_id": args.approach_stick_id},
            )
            result["checks"]["approach"] = True
        except E2ERunnerError:
            latest_step = result["steps"][-1] if result["steps"] else None
            latest_failure = latest_step.get("failure") if isinstance(latest_step, Mapping) else None
            should_tolerate = (
                bool(latest_failure)
                and isinstance(latest_failure, Mapping)
                and not args.strict_approach
                and _should_tolerate_approach_failure(latest_failure)
            )
            if not should_tolerate:
                raise

            assert isinstance(latest_step, dict)
            assert isinstance(latest_failure, Mapping)
            latest_step["status"] = "skipped"
            latest_step["observation"] = {
                "approach_skipped": True,
                "reason": "native_axis_input_not_handled",
            }
            result["notes"].append("approach_step_skipped:native_axis_input_not_handled")

        attack_step = _create_step_record("attack", command="attack", request_args={})
        result["steps"].append(attack_step)
        attack_started_at_monotonic = time.monotonic()
        attempts: list[Dict[str, Any]] = []
        actor_died_event: Optional[Mapping[str, Any]] = None
        final_target_state: Optional[Mapping[str, Any]] = None

        for attempt in range(1, args.attack_max_attempts + 1):
            attempt_started_at = time.monotonic()
            response = client.send_command("attack", session_id=session_id, args={})
            attempt_record: Dict[str, Any] = {
                "attempt": attempt,
                "response": dict(response),
                "duration_seconds": None,
                "target_alive": None,
                "target_health": None,
                "actor_died_event": None,
            }

            if not bool(response.get("accepted", False)):
                attempt_record["failure"] = _make_failure(
                    "attack",
                    str(response.get("error_code", "command_rejected")),
                    str(response.get("error_message", "attack command was rejected.")),
                    details={"error_stage": response.get("error_stage")},
                )
                attempt_record["duration_seconds"] = round(max(0.0, time.monotonic() - attempt_started_at), 3)
                attempts.append(attempt_record)
                failure = attempt_record["failure"]
                _finalize_step_record(
                    attack_step,
                    status="failed",
                    response=response,
                    observation={"attempts": attempts},
                    failure=failure,
                    started_at_monotonic=attack_started_at_monotonic,
                )
                raise E2ERunnerError(f"attack command rejected on attempt {attempt}: {failure['message']}")

            if args.post_attack_settle_seconds > 0.0:
                time.sleep(args.post_attack_settle_seconds)

            final_target_state = client.get_target_state(session_id=session_id)
            actor_died_event, cursor = _read_actor_died_event(client, session_id, cursor)

            target_alive = bool(final_target_state.get("alive", True))
            attempt_record["target_alive"] = target_alive
            attempt_record["target_health"] = final_target_state.get("health")
            attempt_record["actor_died_event"] = dict(actor_died_event) if actor_died_event is not None else None
            attempt_record["duration_seconds"] = round(max(0.0, time.monotonic() - attempt_started_at), 3)
            attempts.append(attempt_record)

            if not target_alive:
                result["success"]["target_alive"] = False
                result["success"]["success_condition"] = "target_state.alive=false"
                break

            if actor_died_event is not None:
                result["success"]["actor_died_event_detected"] = True
                result["success"]["success_condition"] = "actor_died_event"
                break

            if attempt < args.attack_max_attempts and args.attack_interval_seconds > 0.0:
                time.sleep(args.attack_interval_seconds)

        if final_target_state is None:
            final_target_state = client.get_target_state(session_id=session_id)

        result["success"]["target_alive"] = bool(final_target_state.get("alive", True))
        result["success"]["actor_died_event_detected"] = actor_died_event is not None
        result["final_state"]["target_state"] = dict(final_target_state)

        if result["success"]["success_condition"] is None:
            failure = _make_failure(
                "attack",
                "target_survived",
                f"Target was still alive after {args.attack_max_attempts} attack attempts.",
                details={
                    "attempts": args.attack_max_attempts,
                    "target_alive": final_target_state.get("alive"),
                    "target_health": final_target_state.get("health"),
                },
            )
            _finalize_step_record(
                attack_step,
                status="failed",
                observation={"attempts": attempts},
                failure=failure,
                started_at_monotonic=attack_started_at_monotonic,
            )
            raise E2ERunnerError(failure["message"])

        attack_observation: Dict[str, Any] = {"attempts": attempts}
        if actor_died_event is not None:
            attack_observation["actor_died_event"] = dict(actor_died_event)
        _finalize_step_record(
            attack_step,
            status="passed",
            observation=attack_observation,
            started_at_monotonic=attack_started_at_monotonic,
        )
        result["checks"]["attack"] = True

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

        result["ended_at_utc"] = utc_now_iso()
        result["duration_seconds"] = round(max(0.0, time.monotonic() - started_at_monotonic), 3)
        _write_json(report_path, result)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the equip-approach-attack-kill E2E scenario.")
    parser.add_argument("--base-url", default="http://127.0.0.1:31001", help="Remote API base URL.")
    parser.add_argument("--session-id", default=None, help="Optional explicit session id.")
    parser.add_argument("--run-id", default=None, help="Optional explicit run id.")
    parser.add_argument("--request-timeout", type=float, default=5.0, help="HTTP/WS request timeout seconds.")
    parser.add_argument("--retry-attempts", type=int, default=2, help="HTTP retry attempts.")
    parser.add_argument("--retry-backoff", type=float, default=0.25, help="HTTP retry backoff seconds.")
    parser.add_argument("--health-timeout", type=float, default=90.0, help="Health wait timeout seconds.")
    parser.add_argument("--poll-interval", type=float, default=0.25, help="Polling interval seconds.")

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
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    summary = run_e2e(args)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0 if summary.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
