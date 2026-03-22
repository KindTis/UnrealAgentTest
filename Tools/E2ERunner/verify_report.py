from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping


DEFAULT_SUCCESS_BY_INTENT = {
    "movement_jump_sequence": "sequence_completed",
    "defeat_monster": "target_state.alive=false",
    "workflow_steps": "steps_completed",
}


def _extract_command_log(report: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    logs: List[Mapping[str, Any]] = []

    top_level = report.get("command_log")
    if isinstance(top_level, list):
        for item in top_level:
            if isinstance(item, Mapping):
                logs.append(item)

    steps = report.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            observation = step.get("observation")
            if not isinstance(observation, Mapping):
                continue
            command_log = observation.get("command_log")
            if not isinstance(command_log, list):
                continue
            for item in command_log:
                if isinstance(item, Mapping):
                    logs.append(item)

    return logs


def _count_jump_taps(command_log: List[Mapping[str, Any]]) -> int:
    count = 0
    for entry in command_log:
        if str(entry.get("command", "")).strip().lower() != "tap_button":
            continue
        args = entry.get("request_args")
        if not isinstance(args, Mapping):
            args = entry.get("args")
        if not isinstance(args, Mapping):
            continue
        if str(args.get("button_id", "")).strip().lower() != "jump":
            continue
        if bool(entry.get("accepted", False)):
            count += 1
    return count


def _count_rejected_commands(command_log: List[Mapping[str, Any]]) -> int:
    rejected = 0
    for entry in command_log:
        accepted = entry.get("accepted")
        if isinstance(accepted, bool) and not accepted:
            rejected += 1
    return rejected


def verify_report(
    report: Mapping[str, Any],
    *,
    expect_ok: bool,
    expect_intent: str | None,
    expect_success_condition: str | None,
    require_jump_count: int | None,
) -> Dict[str, Any]:
    failures: List[str] = []
    checks: Dict[str, Any] = {}

    ok = bool(report.get("ok", False))
    checks["ok"] = ok
    if expect_ok and not ok:
        failures.append("report.ok is false")

    scenario_value = report.get("scenario")
    detected_intent = None
    if isinstance(scenario_value, str):
        detected_intent = scenario_value
    elif isinstance(scenario_value, Mapping):
        detected_intent = str(scenario_value.get("intent", "")).strip() or None

    checks["detected_intent"] = detected_intent
    if expect_intent:
        if detected_intent is None:
            failures.append(f"intent check failed: expected '{expect_intent}', but report does not expose scenario intent")
        elif detected_intent != expect_intent:
            failures.append(f"intent check failed: expected '{expect_intent}', got '{detected_intent}'")

    success = report.get("success")
    success_condition = None
    if isinstance(success, Mapping):
        success_condition = success.get("success_condition")
        if success_condition is not None:
            success_condition = str(success_condition)
    checks["success_condition"] = success_condition

    expected_success = expect_success_condition
    if expected_success is None and expect_intent:
        expected_success = DEFAULT_SUCCESS_BY_INTENT.get(expect_intent)
    if expected_success:
        if success_condition != expected_success:
            failures.append(
                f"success_condition check failed: expected '{expected_success}', got '{success_condition}'"
            )

    command_log = _extract_command_log(report)
    checks["command_log_count"] = len(command_log)
    rejected_count = _count_rejected_commands(command_log)
    checks["rejected_command_count"] = rejected_count

    if require_jump_count is not None:
        jump_count = _count_jump_taps(command_log)
        checks["accepted_jump_tap_count"] = jump_count
        if jump_count != require_jump_count:
            failures.append(
                f"jump tap count check failed: expected {require_jump_count}, got {jump_count}"
            )

    return {
        "passed": len(failures) == 0,
        "checks": checks,
        "failures": failures,
    }


def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify UnrealAgentTest E2E report.")
    parser.add_argument("--report", type=Path, required=True, help="Path to report.json")
    parser.add_argument(
        "--expect-intent",
        default=None,
        choices=("movement_jump_sequence", "defeat_monster", "workflow_steps"),
        help="Expected scenario intent.",
    )
    parser.add_argument(
        "--expect-success-condition",
        default=None,
        help="Expected success.success_condition value. If omitted and --expect-intent is set, default is intent-based.",
    )
    parser.add_argument(
        "--require-jump-count",
        type=int,
        default=None,
        help="Require exact accepted jump tap count (tap_button with button_id=jump).",
    )
    parser.add_argument(
        "--allow-failure",
        action="store_true",
        help="Do not fail when report.ok is false.",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    report_path: Path = args.report.expanduser().resolve()

    if not report_path.exists():
        sys.stdout.write(
            json.dumps(
                {
                    "passed": False,
                    "checks": {"report_path": str(report_path)},
                    "failures": [f"report file not found: {report_path}"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        return 1

    report_raw = report_path.read_text(encoding="utf-8")
    report = json.loads(report_raw)
    if not isinstance(report, Mapping):
        sys.stdout.write(
            json.dumps(
                {
                    "passed": False,
                    "checks": {"report_path": str(report_path)},
                    "failures": ["report root must be a JSON object"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        return 1

    result = verify_report(
        report,
        expect_ok=not args.allow_failure,
        expect_intent=args.expect_intent,
        expect_success_condition=args.expect_success_condition,
        require_jump_count=args.require_jump_count,
    )
    result["checks"]["report_path"] = str(report_path)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
