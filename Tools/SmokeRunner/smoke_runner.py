from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
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
)
from Tools.UnrealTestClient.unreal_test_client import (  # noqa: E402
    UnrealTestClient,
    UnrealTestClientError,
)


class SmokeRunnerError(RuntimeError):
    """Raised when smoke validation fails."""


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


def _wait_until_healthy(client: UnrealTestClient, timeout: float, poll_interval: float) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            return client.connect()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(max(0.05, poll_interval))
    raise SmokeRunnerError(f"Health check timeout after {timeout} seconds.") from last_error


def _schedule_command(
    client: UnrealTestClient,
    session_id: str,
    *,
    delay_seconds: float,
    command_name: str,
    payload_tag: str,
) -> tuple[threading.Thread, Dict[str, Any]]:
    holder: Dict[str, Any] = {"ok": False}

    def _run() -> None:
        try:
            time.sleep(max(0.0, delay_seconds))
            args: Dict[str, Any]
            if command_name == "execute_recipe":
                args = {"recipe_id": payload_tag, "args": {"tag": payload_tag}}
            else:
                args = {"tag": payload_tag}
            response = client.send_command(
                command_name,
                session_id=session_id,
                args=args,
            )
            holder["ok"] = True
            holder["response"] = response
        except Exception as exc:  # noqa: BLE001
            holder["ok"] = False
            holder["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=_run, name=f"smoke-command-{payload_tag}", daemon=True)
    worker.start()
    return worker, holder


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


class _HttpDisabledClient(UnrealTestClient):
    def get_events(self, **kwargs: Any) -> Dict[str, Any]:  # type: ignore[override]
        raise UnrealTestClientError("HTTP polling disabled for websocket path verification.")


class _NoWebSocketClient(UnrealTestClient):
    def _get_websocket_endpoint(self) -> None:  # type: ignore[override]
        return None


def _start_unreal_if_requested(args: argparse.Namespace, run_id: str, session_id: str) -> Optional[_LaunchContext]:
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

    artifacts_root = args.artifacts_root.expanduser().resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)
    log_path = artifacts_root / f"smoke-{run_id}.log"
    log_stream = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        command["argv"],
        cwd=command["working_directory"],
        stdout=log_stream,
        stderr=subprocess.STDOUT,
    )
    return _LaunchContext(process=process, log_path=log_path, log_stream=log_stream)


def run_smoke(args: argparse.Namespace) -> Dict[str, Any]:
    run_id = args.run_id or generate_run_id(prefix="smoke")
    session_id = args.session_id or generate_session_id(run_id, 1, prefix="session")
    launch_ctx: Optional[_LaunchContext] = None
    started_session = False

    client = UnrealTestClient(
        args.base_url,
        timeout=args.request_timeout,
        retry_attempts=args.retry_attempts,
        retry_backoff=args.retry_backoff,
    )

    result: Dict[str, Any] = {
        "ok": False,
        "run_id": run_id,
        "session_id": session_id,
        "base_url": args.base_url,
        "launch": {"enabled": bool(args.launch)},
        "checks": {},
        "notes": [],
    }

    try:
        launch_ctx = _start_unreal_if_requested(args, run_id, session_id)
        if launch_ctx is not None:
            result["launch"]["pid"] = launch_ctx.process.pid
            result["launch"]["log_path"] = str(launch_ctx.log_path)

        health = _wait_until_healthy(client, timeout=args.health_timeout, poll_interval=args.poll_interval)
        result["checks"]["health"] = True
        result["health"] = health

        capabilities = client.get_capabilities()
        result["checks"]["capabilities"] = True
        result["capabilities"] = {
            "version": capabilities.get("version"),
            "events_websocket_url": capabilities.get("events_websocket_url"),
            "events_websocket_port": capabilities.get("events_websocket_port"),
        }

        ws_url = capabilities.get("events_websocket_url")
        if not isinstance(ws_url, str) or not ws_url:
            raise SmokeRunnerError("capabilities.events_websocket_url is missing.")
        result["checks"]["websocket_capability"] = True

        session_start = client.start_session(session_id=session_id, run_id=run_id)
        started_session = bool(session_start.get("accepted", False))
        if not started_session:
            raise SmokeRunnerError("session_start was not accepted.")
        session_id = str(session_start.get("session_id", session_id))
        result["session_start"] = session_start
        result["session_id"] = session_id
        result["checks"]["session_start"] = True

        player_state = client.get_player_state(session_id=session_id)
        target_state = client.get_target_state(session_id=session_id)
        spatial_state = client.get_spatial_state(session_id=session_id)
        result["checks"]["state_endpoints"] = True
        result["state_sample"] = {
            "player_actor_id": player_state.get("actor_id"),
            "target_actor_id": target_state.get("actor_id"),
            "distance_cm": spatial_state.get("distance_cm"),
        }

        events_snapshot = client.get_events(session_id=session_id, limit=1)
        cursor = _safe_sequence(events_snapshot.get("last_sequence"), 0)
        result["checks"]["events_http"] = True

        ws_only_client = _HttpDisabledClient(
            args.base_url,
            timeout=args.request_timeout,
            retry_attempts=args.retry_attempts,
            retry_backoff=args.retry_backoff,
            session_id=session_id,
        )
        ws_only_client._capabilities_cache = dict(capabilities)  # type: ignore[attr-defined]

        ws_thread, ws_holder = _schedule_command(
            client,
            session_id,
            delay_seconds=0.2,
            command_name="execute_recipe",
            payload_tag="ws",
        )
        ws_event = ws_only_client.wait_for_event(
            session_id=session_id,
            event_type="command_step_started",
            after_sequence=cursor,
            timeout=args.event_timeout,
            poll_interval=args.poll_interval,
        )
        ws_thread.join(timeout=args.event_timeout + 1.0)
        if not ws_holder.get("ok", False):
            raise SmokeRunnerError(f"WS trigger command failed: {ws_holder.get('error', 'unknown')}")
        result["checks"]["events_websocket_live"] = True
        result["ws_event"] = ws_event

        cursor = max(cursor, _safe_sequence(ws_event.get("sequence_id"), cursor))
        fallback_client = _NoWebSocketClient(
            args.base_url,
            timeout=args.request_timeout,
            retry_attempts=args.retry_attempts,
            retry_backoff=args.retry_backoff,
            session_id=session_id,
        )
        fallback_client._capabilities_cache = dict(capabilities)  # type: ignore[attr-defined]

        fallback_thread, fallback_holder = _schedule_command(
            client,
            session_id,
            delay_seconds=0.2,
            command_name="execute_recipe",
            payload_tag="http_fallback",
        )
        fallback_event = fallback_client.wait_for_event(
            session_id=session_id,
            event_type="command_step_started",
            after_sequence=cursor,
            timeout=args.event_timeout,
            poll_interval=args.poll_interval,
        )
        fallback_thread.join(timeout=args.event_timeout + 1.0)
        if not fallback_holder.get("ok", False):
            raise SmokeRunnerError(f"Fallback trigger command failed: {fallback_holder.get('error', 'unknown')}")
        result["checks"]["events_http_fallback"] = True
        result["fallback_event"] = fallback_event

        stop_response = client.stop_session(session_id=session_id)
        result["session_stop"] = stop_response
        result["checks"]["session_stop"] = bool(stop_response.get("accepted", False))
        started_session = False

        result["ok"] = True
        return result
    finally:
        if started_session:
            try:
                client.stop_session(session_id=session_id)
            except Exception:  # noqa: BLE001
                result["notes"].append("session_stop_cleanup_failed")

        if launch_ctx is not None:
            if args.keep_process:
                result["notes"].append("launched_process_kept_alive")
            else:
                try:
                    termination = _terminate_process(launch_ctx.process, grace_seconds=args.terminate_grace_seconds)
                    result["launch"]["termination"] = termination
                except Exception as exc:  # noqa: BLE001
                    result["launch"]["termination_error"] = f"{type(exc).__name__}: {exc}"
            try:
                launch_ctx.log_stream.close()
            except Exception:  # noqa: BLE001
                pass


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run smoke validation against UnrealAgentTest Remote API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:31001", help="Remote API base URL.")
    parser.add_argument("--session-id", default=None, help="Optional explicit session id.")
    parser.add_argument("--run-id", default=None, help="Optional explicit run id.")
    parser.add_argument("--request-timeout", type=float, default=5.0, help="HTTP/WS request timeout seconds.")
    parser.add_argument("--retry-attempts", type=int, default=2, help="HTTP retry attempts.")
    parser.add_argument("--retry-backoff", type=float, default=0.25, help="HTTP retry backoff seconds.")
    parser.add_argument("--health-timeout", type=float, default=90.0, help="Health wait timeout seconds.")
    parser.add_argument("--event-timeout", type=float, default=8.0, help="Event wait timeout seconds.")
    parser.add_argument("--poll-interval", type=float, default=0.25, help="Polling interval seconds.")

    parser.add_argument("--launch", action="store_true", help="Launch UnrealEditor with -TestMode before smoke checks.")
    parser.add_argument("--unreal-executable", default=DEFAULT_UNREAL_EXECUTABLE, help="Path to UnrealEditor executable.")
    parser.add_argument("--uproject", default=DEFAULT_UPROJECT, help="Path to .uproject file.")
    parser.add_argument("--port", type=int, default=None, help="Port override used when --launch is enabled.")
    parser.add_argument("--scenario", default=None, help="Optional scenario argument passed to Unreal.")
    parser.add_argument("--extra-arg", action="append", default=[], help="Extra argument for Unreal process.")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path.cwd() / "Artifacts" / "SmokeRunner",
        help="Artifacts root directory for smoke logs.",
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
    try:
        summary = run_smoke(args)
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        return 0 if summary.get("ok", False) else 1
    except Exception as exc:  # noqa: BLE001
        error = {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }
        sys.stdout.write(json.dumps(error, ensure_ascii=False, indent=2) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
