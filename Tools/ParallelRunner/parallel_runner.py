from __future__ import annotations

import argparse
import ctypes
import json
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_UNREAL_EXECUTABLE = r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe"
DEFAULT_UPROJECT = r"C:\Users\tatis\Repos\ThirdPersonAction\ThirdPersonAction.uproject"
DEFAULT_MAX_CONCURRENT_SESSIONS = 2
DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS = 120.0
DEFAULT_SESSION_TIMEOUT_SECONDS = 180.0
DEFAULT_CPU_PERCENT_LIMIT = 0.0
DEFAULT_MEMORY_AVAILABLE_MB_LIMIT = 0.0


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def generate_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{utc_timestamp()}-{secrets.token_hex(2)}"


def generate_session_id(run_id: str, index: int, prefix: str = "session") -> str:
    return f"{run_id}-{prefix}-{index:02d}"


def allocate_ports(count: int, base_port: int) -> List[int]:
    ports = [base_port + offset for offset in range(count)]
    if ports and ports[-1] > 65535:
        raise ValueError("port range exceeds 65535")
    return ports


def create_artifact_layout(artifacts_root: Path, run_id: str, timestamp: str, session_id: str) -> Dict[str, Path]:
    run_dir = artifacts_root / "runs" / run_id
    timestamp_dir = run_dir / timestamp
    session_dir = timestamp_dir / "sessions" / session_id
    log_dir = session_dir / "logs"
    artifact_dir = session_dir / "artifacts"

    for path in (run_dir, timestamp_dir, session_dir, log_dir, artifact_dir):
        path.mkdir(parents=True, exist_ok=True)

    return {
        "run_dir": run_dir,
        "timestamp_dir": timestamp_dir,
        "session_dir": session_dir,
        "log_dir": log_dir,
        "artifact_dir": artifact_dir,
    }


def _quote_command(argv: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(argv))


def build_unreal_command(
    *,
    unreal_executable: str,
    uproject: str,
    session_id: str,
    port: int,
    run_id: str,
    scenario: Optional[str] = None,
    seed: Optional[int] = None,
    extra_args: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    argv: List[str] = [
        unreal_executable,
        uproject,
        "-NoSplash",
        "-NoSound",
        "-Unattended",
        "-StdOut",
        "-UTF8Output",
        "-log",
        "-TestMode",
        f"-SessionId={session_id}",
        f"-Port={port}",
        f"-RunId={run_id}",
    ]

    if scenario:
        argv.append(f"-Scenario={scenario}")

    if seed is not None:
        argv.append(f"-Seed={seed}")

    if extra_args:
        argv.extend(extra_args)

    return {
        "executable": unreal_executable,
        "uproject": uproject,
        "argv": argv,
        "command_line": _quote_command(argv),
        "working_directory": str(Path(uproject).resolve().parent),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_positive_float(value: Optional[float], *, allow_zero: bool = False) -> Optional[float]:
    if value is None:
        return None
    coerced = float(value)
    if coerced < 0 or (coerced == 0 and not allow_zero):
        raise ValueError("timeout values must be non-negative")
    return coerced


def _coerce_positive_int(value: Optional[int], *, name: str) -> int:
    if value is None:
        raise ValueError(f"{name} must be provided")
    coerced = int(value)
    if coerced <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return coerced


def _initialize_execution_state(session: Dict[str, Any], *, status: str = "planned") -> Dict[str, Any]:
    execution = session["execution"]
    execution.update(
        {
            "pid": None,
            "started": False,
            "started_at_utc": None,
            "wait_started_at_utc": None,
            "queued_at_utc": None,
            "ended_at_utc": None,
            "runtime_seconds": None,
            "exit_code": None,
            "timed_out": False,
            "termination_method": None,
            "status": status,
            "error": None,
        }
    )
    return execution


def _finalize_execution_state(
    execution: Dict[str, Any],
    *,
    status: str,
    process: Optional[subprocess.Popen] = None,
    started_at_monotonic: Optional[float] = None,
    ended_at_utc: Optional[str] = None,
    timed_out: bool = False,
    termination_method: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    execution["status"] = status
    execution["timed_out"] = timed_out
    execution["termination_method"] = termination_method
    execution["ended_at_utc"] = ended_at_utc or utc_now_iso()
    execution["error"] = error
    if process is not None:
        execution["exit_code"] = process.poll()
    if started_at_monotonic is not None:
        execution["runtime_seconds"] = round(max(0.0, time.monotonic() - started_at_monotonic), 3)


def _safe_terminate_process(process: subprocess.Popen, grace_seconds: float) -> str:
    if process.poll() is not None:
        return "already-exited"

    try:
        process.terminate()
    except Exception:
        pass

    try:
        process.wait(timeout=grace_seconds)
        return "terminate"
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except Exception:
            pass
        try:
            process.wait(timeout=max(0.0, grace_seconds))
        except subprocess.TimeoutExpired:
            pass
        return "kill"


def _read_system_times() -> Optional[Dict[str, int]]:
    if sys.platform != "win32":
        return None

    idle_time = ctypes.c_ulonglong()
    kernel_time = ctypes.c_ulonglong()
    user_time = ctypes.c_ulonglong()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        return None
    return {
        "idle": int(idle_time.value),
        "kernel": int(kernel_time.value),
        "user": int(user_time.value),
    }


def _sample_system_cpu_percent(sample_window_seconds: float = 0.05) -> Optional[float]:
    if sys.platform != "win32":
        return None

    start = _read_system_times()
    if start is None:
        return None
    time.sleep(max(0.0, sample_window_seconds))
    end = _read_system_times()
    if end is None:
        return None

    idle_delta = end["idle"] - start["idle"]
    kernel_delta = end["kernel"] - start["kernel"]
    user_delta = end["user"] - start["user"]
    total_delta = kernel_delta + user_delta
    if total_delta <= 0:
        return 0.0
    busy_delta = max(0, total_delta - idle_delta)
    return max(0.0, min(100.0, (busy_delta / total_delta) * 100.0))


def _get_available_memory_mb() -> Optional[float]:
    if sys.platform != "win32":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    memory_status = MEMORYSTATUSEX()
    memory_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status)):
        return None
    return memory_status.ullAvailPhys / (1024.0 * 1024.0)


def _resource_guard_allows(
    *,
    cpu_percent_limit: float,
    memory_available_mb_limit: float,
) -> bool:
    if cpu_percent_limit > 0.0:
        cpu_percent = _sample_system_cpu_percent()
        if cpu_percent is not None and cpu_percent >= cpu_percent_limit:
            return False

    if memory_available_mb_limit > 0.0:
        available_memory_mb = _get_available_memory_mb()
        if available_memory_mb is not None and available_memory_mb < memory_available_mb_limit:
            return False

    return True


def _append_execution_summary(plan: Dict[str, Any]) -> None:
    summary: Dict[str, int] = {}
    for session in plan.get("sessions", []):
        status = str(session.get("execution", {}).get("status", "unknown"))
        summary[status] = summary.get(status, 0) + 1
    plan["execution_summary"] = summary


def run_execution_plan(
    plan: Dict[str, Any],
    *,
    max_concurrent_sessions: int = DEFAULT_MAX_CONCURRENT_SESSIONS,
    queue_wait_timeout_seconds: float = DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS,
    session_timeout_seconds: Optional[float] = DEFAULT_SESSION_TIMEOUT_SECONDS,
    timeout_seconds: Optional[float] = None,
    cpu_percent_limit: float = DEFAULT_CPU_PERCENT_LIMIT,
    memory_available_mb_limit: float = DEFAULT_MEMORY_AVAILABLE_MB_LIMIT,
    terminate_grace_seconds: float = 5.0,
    poll_interval_seconds: float = 0.25,
) -> Dict[str, Any]:
    max_concurrent_sessions = _coerce_positive_int(max_concurrent_sessions, name="max_concurrent_sessions")
    queue_wait_timeout_seconds = _coerce_positive_float(queue_wait_timeout_seconds, allow_zero=True) or 0.0
    if session_timeout_seconds is None:
        session_timeout_seconds = timeout_seconds
    session_timeout_seconds = _coerce_positive_float(session_timeout_seconds, allow_zero=True)
    cpu_percent_limit = _coerce_positive_float(cpu_percent_limit, allow_zero=True) or 0.0
    memory_available_mb_limit = _coerce_positive_float(memory_available_mb_limit, allow_zero=True) or 0.0
    terminate_grace_seconds = _coerce_positive_float(terminate_grace_seconds, allow_zero=True) or 0.0
    poll_interval_seconds = _coerce_positive_float(poll_interval_seconds) or 0.25

    queued_sessions: List[Dict[str, Any]] = []
    for session in plan.get("sessions", []):
        execution = _initialize_execution_state(session, status="queued")
        execution["mode"] = "execute"
        execution["wait_started_at_utc"] = utc_now_iso()
        execution["queued_at_utc"] = execution["wait_started_at_utc"]
        queued_sessions.append(
            {
                "session": session,
                "queued_at_monotonic": time.monotonic(),
            }
        )

    active_sessions: List[Dict[str, Any]] = []
    while queued_sessions or active_sessions:
        now = time.monotonic()
        next_round: List[Dict[str, Any]] = []
        for item in active_sessions:
            session = item["session"]
            process = item["process"]
            execution = session["execution"]
            started_at_monotonic = item["started_at_monotonic"]

            exit_code = process.poll()
            if exit_code is not None:
                _finalize_execution_state(
                    execution,
                    status="completed" if exit_code == 0 else "failed",
                    process=process,
                    started_at_monotonic=started_at_monotonic,
                )
                continue

            timed_out = session_timeout_seconds is not None and (now - started_at_monotonic) >= session_timeout_seconds
            if timed_out:
                termination_method = _safe_terminate_process(process, terminate_grace_seconds)
                _finalize_execution_state(
                    execution,
                    status="timeout",
                    process=process,
                    started_at_monotonic=started_at_monotonic,
                    timed_out=True,
                    termination_method=termination_method,
                )
                continue

            next_round.append(item)

        active_sessions = next_round

        while queued_sessions and len(active_sessions) < max_concurrent_sessions:
            now = time.monotonic()
            queued_item = queued_sessions[0]
            session = queued_item["session"]
            execution = session["execution"]
            queued_at_monotonic = queued_item["queued_at_monotonic"]
            waited_seconds = now - queued_at_monotonic

            if queue_wait_timeout_seconds is not None and waited_seconds >= queue_wait_timeout_seconds:
                _finalize_execution_state(
                    execution,
                    status="queue_timeout",
                    timed_out=True,
                    termination_method="queue_timeout",
                    ended_at_utc=utc_now_iso(),
                    error=f"Exceeded queue wait timeout of {queue_wait_timeout_seconds} seconds",
                )
                queued_sessions.pop(0)
                continue

            if not _resource_guard_allows(
                cpu_percent_limit=cpu_percent_limit,
                memory_available_mb_limit=memory_available_mb_limit,
            ):
                break

            argv = session["command"]["argv"]
            working_directory = session["command"]["working_directory"]
            started_at_monotonic = time.monotonic()

            try:
                process = subprocess.Popen(argv, cwd=working_directory)
            except Exception as exc:
                _finalize_execution_state(
                    execution,
                    status="failed",
                    started_at_monotonic=started_at_monotonic,
                    error=f"{type(exc).__name__}: {exc}",
                )
                queued_sessions.pop(0)
                continue

            execution["pid"] = process.pid
            execution["started"] = True
            execution["status"] = "running"
            execution["started_at_utc"] = utc_now_iso()
            active_sessions.append(
                {
                    "session": session,
                    "process": process,
                    "started_at_monotonic": started_at_monotonic,
                }
            )
            queued_sessions.pop(0)

        if queued_sessions or active_sessions:
            time.sleep(poll_interval_seconds)

    _append_execution_summary(plan)
    return plan


@dataclass
class SessionPlan:
    index: int
    run_id: str
    session_id: str
    port: int
    paths: Dict[str, str]
    command: Dict[str, Any]
    execution: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "port": self.port,
            "paths": self.paths,
            "command": self.command,
            "execution": self.execution,
        }


def build_execution_plan(
    *,
    count: int,
    base_port: int,
    artifacts_root: Path,
    unreal_executable: str,
    uproject: str,
    scenario: Optional[str] = None,
    seed: Optional[int] = None,
    extra_args: Optional[Sequence[str]] = None,
    execute: bool = False,
    max_concurrent_sessions: int = DEFAULT_MAX_CONCURRENT_SESSIONS,
    queue_wait_timeout_seconds: float = DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS,
    session_timeout_seconds: float = DEFAULT_SESSION_TIMEOUT_SECONDS,
    cpu_percent_limit: float = DEFAULT_CPU_PERCENT_LIMIT,
    memory_available_mb_limit: float = DEFAULT_MEMORY_AVAILABLE_MB_LIMIT,
) -> Dict[str, Any]:
    if count <= 0:
        raise ValueError("count must be greater than zero")
    if base_port <= 0 or base_port > 65535:
        raise ValueError("base_port must be in the range 1..65535")
    if base_port + count - 1 > 65535:
        raise ValueError("base_port and count exceed the valid port range")
    max_concurrent_sessions = _coerce_positive_int(max_concurrent_sessions, name="max_concurrent_sessions")
    queue_wait_timeout_seconds = _coerce_positive_float(queue_wait_timeout_seconds, allow_zero=True) or 0.0
    session_timeout_seconds = _coerce_positive_float(session_timeout_seconds, allow_zero=True) or 0.0
    cpu_percent_limit = _coerce_positive_float(cpu_percent_limit, allow_zero=True) or 0.0
    memory_available_mb_limit = _coerce_positive_float(memory_available_mb_limit, allow_zero=True) or 0.0

    run_id = generate_run_id()
    timestamp = utc_timestamp()
    ports = allocate_ports(count, base_port)

    artifacts_root = artifacts_root.expanduser().resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)

    sessions: List[SessionPlan] = []
    for index, port in enumerate(ports, start=1):
        session_id = generate_session_id(run_id, index)
        layout = create_artifact_layout(artifacts_root, run_id, timestamp, session_id)
        command = build_unreal_command(
            unreal_executable=unreal_executable,
            uproject=uproject,
            session_id=session_id,
            port=port,
            run_id=run_id,
            scenario=scenario,
            seed=seed,
            extra_args=extra_args,
        )
        execution = {
            "mode": "execute" if execute else "plan-only",
            "pid": None,
            "started": False,
        }
        sessions.append(
            SessionPlan(
                index=index,
                run_id=run_id,
                session_id=session_id,
                port=port,
                paths={key: str(value) for key, value in layout.items()},
                command=command,
                execution=execution,
            )
        )

    return {
        "generated_at_utc": timestamp,
        "plan_mode": "execute" if execute else "plan-only",
        "run_id": run_id,
        "count": count,
        "base_port": base_port,
        "artifacts_root": str(artifacts_root),
        "uproject": str(Path(uproject).resolve()),
        "unreal_executable": str(Path(unreal_executable)),
        "policy": {
            "max_concurrent_sessions": max_concurrent_sessions,
            "queue_wait_timeout_seconds": queue_wait_timeout_seconds,
            "session_timeout_seconds": session_timeout_seconds,
            "cpu_percent_limit": cpu_percent_limit,
            "memory_available_mb_limit": memory_available_mb_limit,
        },
        "sessions": [session.to_dict() for session in sessions],
    }


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan multi-session Unreal execution runs.")
    parser.add_argument("--count", type=int, required=True, help="Number of sessions to plan.")
    parser.add_argument("--base-port", type=int, required=True, help="First port to allocate.")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path.cwd() / "Artifacts" / "ParallelRunner",
        help="Root directory for run/session artifacts.",
    )
    parser.add_argument(
        "--unreal-executable",
        default=DEFAULT_UNREAL_EXECUTABLE,
        help="Path to UnrealEditor.exe or equivalent launcher.",
    )
    parser.add_argument(
        "--uproject",
        default=DEFAULT_UPROJECT,
        help="Path to the Unreal project .uproject file.",
    )
    parser.add_argument("--scenario", default=None, help="Optional scenario identifier passed to Unreal.")
    parser.add_argument("--seed", type=int, default=None, help="Optional deterministic seed.")
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Extra Unreal command line argument. Can be repeated.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Launch the generated commands instead of plan-only output.",
    )
    parser.add_argument(
        "--max-concurrent-sessions",
        type=int,
        default=DEFAULT_MAX_CONCURRENT_SESSIONS,
        help="Maximum number of sessions to run at the same time in execute mode.",
    )
    parser.add_argument(
        "--queue-wait-timeout-seconds",
        type=float,
        default=DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS,
        help="Maximum time a session may remain queued before it is marked queue_timeout.",
    )
    parser.add_argument(
        "--session-timeout-seconds",
        type=float,
        default=DEFAULT_SESSION_TIMEOUT_SECONDS,
        help="Per-session runtime timeout for execute mode.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        dest="session_timeout_seconds",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--cpu-percent-limit",
        type=float,
        default=DEFAULT_CPU_PERCENT_LIMIT,
        help="Optional CPU usage guard before starting a queued session. Zero disables the guard.",
    )
    parser.add_argument(
        "--memory-available-mb-limit",
        type=float,
        default=DEFAULT_MEMORY_AVAILABLE_MB_LIMIT,
        help="Optional available memory guard before starting a queued session. Zero disables the guard.",
    )
    parser.add_argument(
        "--terminate-grace-seconds",
        type=float,
        default=5.0,
        help="Grace period to wait after terminate() before kill() fallback.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        plan = build_execution_plan(
            count=args.count,
            base_port=args.base_port,
            artifacts_root=args.artifacts_root,
            unreal_executable=args.unreal_executable,
            uproject=args.uproject,
            scenario=args.scenario,
            seed=args.seed,
            extra_args=args.extra_arg,
            execute=args.execute,
            max_concurrent_sessions=args.max_concurrent_sessions,
            queue_wait_timeout_seconds=args.queue_wait_timeout_seconds,
            session_timeout_seconds=args.session_timeout_seconds,
            cpu_percent_limit=args.cpu_percent_limit,
            memory_available_mb_limit=args.memory_available_mb_limit,
        )
        if args.execute:
            plan = run_execution_plan(
                plan,
                max_concurrent_sessions=args.max_concurrent_sessions,
                queue_wait_timeout_seconds=args.queue_wait_timeout_seconds,
                session_timeout_seconds=args.session_timeout_seconds,
                timeout_seconds=args.session_timeout_seconds,
                cpu_percent_limit=args.cpu_percent_limit,
                memory_available_mb_limit=args.memory_available_mb_limit,
                terminate_grace_seconds=args.terminate_grace_seconds,
            )
            plan["plan_mode"] = "execute"
    except Exception as exc:
        error = {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }
        sys.stderr.write(json.dumps(error, ensure_ascii=False, indent=2) + "\n")
        return 1

    sys.stdout.write(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
