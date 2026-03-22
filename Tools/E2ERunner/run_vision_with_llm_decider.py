from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Tools.ParallelRunner.parallel_runner import generate_run_id, generate_session_id  # noqa: E402


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run vision_navigation with an LLM decider process."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:31001")
    parser.add_argument("--scenario-file", type=Path, required=True)
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--artifacts-root", type=Path, default=REPO_ROOT / "Artifacts" / "E2ERunner")
    parser.add_argument("--extra-arg", action="append", default=[], help="Extra argument forwarded to Unreal process.")

    parser.add_argument("--api-base-url", default="https://api.openai.com/v1")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--decider-poll-interval-seconds", type=float, default=0.2)
    parser.add_argument("--decider-request-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--decider-temperature", type=float, default=0.0)
    parser.add_argument("--decider-max-tokens", type=int, default=280)
    parser.add_argument("--decider-fallback-yaw-degrees", type=float, default=20.0)
    parser.add_argument("--decider-allow-fallback-action", action="store_true")
    parser.add_argument("--decider-start-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--verbose", action="store_true")

    parser.add_argument(
        "runner_passthrough",
        nargs=argparse.REMAINDER,
        help="Additional args forwarded to e2e_runner.py (prefix with --).",
    )
    return parser.parse_args(argv)


def _terminate_process(process: subprocess.Popen[bytes], grace_seconds: float = 3.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=max(0.1, grace_seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=max(0.1, grace_seconds))


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    run_id = args.run_id.strip() or generate_run_id("e2e")
    session_id = args.session_id.strip() or generate_session_id(run_id, 1, prefix="session")
    artifacts_root = args.artifacts_root.expanduser().resolve()
    run_dir = artifacts_root / "runs" / run_id
    bridge_dir = run_dir / "bridge" / session_id
    observe_path = bridge_dir / "observe.json"

    runner_cmd: list[str] = [
        sys.executable,
        str(REPO_ROOT / "Tools" / "E2ERunner" / "e2e_runner.py"),
        "--base-url",
        args.base_url,
        "--scenario-file",
        str(args.scenario_file.expanduser().resolve()),
        "--run-id",
        run_id,
        "--session-id",
        session_id,
    ]
    if args.launch:
        runner_cmd.append("--launch")
    for extra in args.extra_arg:
        runner_cmd.extend(["--extra-arg", extra])
    if args.runner_passthrough:
        passthrough = list(args.runner_passthrough)
        if passthrough and passthrough[0] == "--":
            passthrough = passthrough[1:]
        runner_cmd.extend(passthrough)

    decider_cmd: list[str] = [
        sys.executable,
        str(REPO_ROOT / "Tools" / "E2ERunner" / "bridge_decider_llm.py"),
        "--bridge-dir",
        str(bridge_dir),
        "--api-base-url",
        args.api_base_url,
        "--model",
        args.model,
        "--poll-interval-seconds",
        str(args.decider_poll_interval_seconds),
        "--request-timeout-seconds",
        str(args.decider_request_timeout_seconds),
        "--temperature",
        str(args.decider_temperature),
        "--max-tokens",
        str(args.decider_max_tokens),
        "--fallback-yaw-degrees",
        str(args.decider_fallback_yaw_degrees),
    ]
    if args.api_key.strip():
        decider_cmd.extend(["--api-key", args.api_key.strip()])
    if args.decider_allow_fallback_action:
        decider_cmd.append("--allow-fallback-action")
    if args.verbose:
        decider_cmd.append("--verbose")

    if args.verbose:
        print(f"[run_vision_with_llm_decider] run_id={run_id}")
        print(f"[run_vision_with_llm_decider] session_id={session_id}")
        print(f"[run_vision_with_llm_decider] runner_cmd={' '.join(runner_cmd)}")
        print(f"[run_vision_with_llm_decider] decider_cmd={' '.join(decider_cmd)}")

    runner_proc = subprocess.Popen(  # noqa: S603
        runner_cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    decider_proc: Optional[subprocess.Popen[bytes]] = None

    try:
        deadline = time.monotonic() + max(1.0, float(args.decider_start_timeout_seconds))
        while time.monotonic() < deadline:
            if runner_proc.poll() is not None:
                break
            if observe_path.exists():
                break
            time.sleep(0.1)

        if runner_proc.poll() is None and observe_path.exists():
            env = os.environ.copy()
            if args.api_key.strip():
                env["OPENAI_API_KEY"] = args.api_key.strip()
            decider_proc = subprocess.Popen(  # noqa: S603
                decider_cmd,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
            if args.verbose:
                print("[run_vision_with_llm_decider] decider started.")
        elif args.verbose:
            print("[run_vision_with_llm_decider] decider start skipped (observe.json not ready or runner exited).")

        if runner_proc.stdout is not None:
            for chunk in iter(runner_proc.stdout.readline, b""):
                if not chunk:
                    break
                sys.stdout.write(chunk.decode("utf-8", errors="replace"))
                sys.stdout.flush()
        return runner_proc.wait()
    finally:
        if decider_proc is not None:
            _terminate_process(decider_proc)
        if runner_proc.poll() is None:
            _terminate_process(runner_proc)


if __name__ == "__main__":
    raise SystemExit(main())
