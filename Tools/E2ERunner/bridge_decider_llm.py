from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib import error, request


class BridgeDeciderError(RuntimeError):
    """Raised when bridge decider cannot proceed."""


ALLOWED_ACTIONS = {"move_stick", "release_stick", "tap_button", "wait", "camera_yaw"}
ALLOWED_STATUSES = {"continue", "success", "failure"}
ALLOWED_SUCCESS_MODES = {"position", "visual", "hybrid"}


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


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _extract_json_object(text: str) -> Dict[str, Any]:
    payload = text.strip()
    if not payload:
        raise BridgeDeciderError("LLM returned an empty response.")

    if payload.startswith("```"):
        lines = payload.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            payload = "\n".join(lines[1:-1]).strip()
        if payload.lower().startswith("json"):
            payload = payload[4:].strip()

    decoder = json.JSONDecoder()
    start = payload.find("{")
    while start >= 0:
        try:
            obj, _ = decoder.raw_decode(payload[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = payload.find("{", start + 1)
    raise BridgeDeciderError("Could not parse JSON object from LLM response.")


def _extract_chat_content(chat_response: Mapping[str, Any]) -> str:
    choices = chat_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise BridgeDeciderError("LLM response missing choices.")

    first = choices[0]
    if not isinstance(first, Mapping):
        raise BridgeDeciderError("LLM response choice is not an object.")

    message = first.get("message")
    if not isinstance(message, Mapping):
        raise BridgeDeciderError("LLM response missing message object.")

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    text_parts.append(text_value)
        if text_parts:
            return "\n".join(text_parts)
    raise BridgeDeciderError("LLM response content is not text.")


def _validate_decision_schema(decision: Mapping[str, Any], *, run_id: str, session_id: str, iteration: int) -> Dict[str, Any]:
    status = str(decision.get("status", "")).strip().lower()
    if status not in ALLOWED_STATUSES:
        raise BridgeDeciderError(f"Invalid status: {status}")

    success_mode = str(decision.get("success_mode", "visual")).strip().lower() or "visual"
    if success_mode not in ALLOWED_SUCCESS_MODES:
        success_mode = "visual"

    reason = str(decision.get("reason", "")).strip()
    if not reason:
        reason = "llm decision"

    success = bool(decision.get("success", status == "success"))
    actions_raw = decision.get("actions", [])
    if not isinstance(actions_raw, list):
        raise BridgeDeciderError("actions must be an array.")

    actions: list[Dict[str, Any]] = []
    for index, action in enumerate(actions_raw):
        if not isinstance(action, Mapping):
            raise BridgeDeciderError(f"actions[{index}] must be an object.")
        action_name = str(action.get("action", "")).strip()
        if action_name not in ALLOWED_ACTIONS:
            raise BridgeDeciderError(f"Unsupported action: {action_name}")
        args = action.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, Mapping):
            raise BridgeDeciderError(f"actions[{index}].args must be an object.")
        actions.append({"action": action_name, "args": dict(args)})

    return {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "iteration": iteration,
        "status": status,
        "success": success,
        "success_mode": success_mode,
        "reason": reason,
        "actions": actions,
    }


def _fallback_decision(*, run_id: str, session_id: str, iteration: int, error_text: str, fallback_yaw_degrees: float) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "iteration": iteration,
        "status": "continue",
        "success": False,
        "success_mode": "visual",
        "reason": f"fallback_decision_due_to_llm_error:{error_text}",
        "actions": [
            {
                "action": "camera_yaw",
                "args": {"degrees": fallback_yaw_degrees, "duration_ms": 120},
            },
            {
                "action": "wait",
                "args": {"seconds": 0.2},
            },
        ],
    }


def _llm_error_failure_decision(*, run_id: str, session_id: str, iteration: int, error_text: str) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "iteration": iteration,
        "status": "failure",
        "success": False,
        "success_mode": "visual",
        "reason": f"llm_decision_error:{error_text}",
        "actions": [],
    }


def _build_system_prompt() -> str:
    return (
        "You are an Unreal vision-navigation decider.\n"
        "Return a single JSON object only.\n"
        "You must strictly follow this schema:\n"
        "{"
        "\"schema_version\":1,"
        "\"run_id\":\"...\","
        "\"session_id\":\"...\","
        "\"iteration\":1,"
        "\"status\":\"continue|success|failure\","
        "\"success\":true|false,"
        "\"success_mode\":\"position|visual|hybrid\","
        "\"reason\":\"short text\","
        "\"actions\":["
        "{\"action\":\"camera_yaw\",\"args\":{\"degrees\":20,\"duration_ms\":120}},"
        "{\"action\":\"move_stick\",\"args\":{\"stick_id\":\"left_stick\",\"x\":0.0,\"y\":1.0,\"duration_ms\":120}},"
        "{\"action\":\"release_stick\",\"args\":{\"stick_id\":\"left_stick\"}},"
        "{\"action\":\"tap_button\",\"args\":{\"button_id\":\"jump\",\"duration_ms\":120}},"
        "{\"action\":\"wait\",\"args\":{\"seconds\":0.2}}"
        "]"
        "}\n"
        "Rules:\n"
        "1) Keep actions short and safe (<= 3 actions).\n"
        "2) If target is not found, prefer camera_yaw scan.\n"
        "3) If target is found, return status=success with empty actions.\n"
        "4) Never output markdown or explanations."
    )


def _build_user_payload(observe: Mapping[str, Any], *, run_id: str, session_id: str, iteration: int) -> Dict[str, Any]:
    observation = observe.get("observation")
    if not isinstance(observation, Mapping):
        observation = {}

    goal = observe.get("goal")
    if not isinstance(goal, Mapping):
        goal = {}

    capture = observation.get("capture")
    if not isinstance(capture, Mapping):
        capture = {}

    image_base64 = capture.get("image_base64")
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise BridgeDeciderError("observe.json is missing image_base64.")

    viewport_state = capture.get("viewport_state")
    if not isinstance(viewport_state, Mapping):
        viewport_state = {}

    user_text = {
        "run_id": run_id,
        "session_id": session_id,
        "iteration": iteration,
        "goal": {
            "description": goal.get("description"),
            "visual_target": goal.get("visual_target"),
            "position_target": goal.get("position_target"),
        },
        "player_state": observation.get("player_state"),
        "spatial_state": observation.get("spatial_state"),
        "viewport_state": viewport_state,
    }

    return {
        "text": json.dumps(user_text, ensure_ascii=False, separators=(",", ":")),
        "image_data_url": f"data:image/jpeg;base64,{image_base64}",
    }


def _call_chat_completions(
    *,
    api_base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
    temperature: float,
    max_tokens: int,
    system_prompt: str,
    user_payload: Mapping[str, Any],
) -> Dict[str, Any]:
    endpoint = api_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_payload["text"]},
                    {"type": "image_url", "image_url": {"url": user_payload["image_data_url"]}},
                ],
            },
        ],
    }
    body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body_bytes,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with request.urlopen(req, timeout=max(1.0, timeout_seconds)) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise BridgeDeciderError("LLM response is not a JSON object.")
            return parsed
    except error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        raise BridgeDeciderError(f"HTTP {exc.code} from LLM endpoint: {body_text}") from exc
    except error.URLError as exc:
        raise BridgeDeciderError(f"Could not reach LLM endpoint: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BridgeDeciderError(f"Invalid JSON from LLM endpoint: {exc}") from exc


def _decide_once(
    *,
    observe_payload: Mapping[str, Any],
    api_base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    run_id = str(observe_payload.get("run_id", "")).strip()
    session_id = str(observe_payload.get("session_id", "")).strip()
    iteration = _safe_int(observe_payload.get("iteration"), 0)
    if not run_id or not session_id or iteration <= 0:
        raise BridgeDeciderError("observe.json is missing run/session/iteration.")

    user_payload = _build_user_payload(
        observe_payload,
        run_id=run_id,
        session_id=session_id,
        iteration=iteration,
    )
    llm_raw = _call_chat_completions(
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=_build_system_prompt(),
        user_payload=user_payload,
    )
    text = _extract_chat_content(llm_raw)
    decision_candidate = _extract_json_object(text)
    return _validate_decision_schema(
        decision_candidate,
        run_id=run_id,
        session_id=session_id,
        iteration=iteration,
    )


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM bridge decider for vision_navigation.")
    parser.add_argument("--bridge-dir", type=Path, required=True, help="Bridge directory path containing observe.json and decide.json.")
    parser.add_argument("--api-base-url", default="https://api.openai.com/v1", help="OpenAI-compatible API base URL.")
    parser.add_argument("--api-key", default="", help="API key. Defaults to OPENAI_API_KEY env when omitted.")
    parser.add_argument("--model", default="gpt-4.1-mini", help="Vision-capable model name.")
    parser.add_argument("--poll-interval-seconds", type=float, default=0.2, help="Polling interval for observe.json.")
    parser.add_argument("--request-timeout-seconds", type=float, default=45.0, help="LLM API request timeout.")
    parser.add_argument("--temperature", type=float, default=0.0, help="LLM temperature.")
    parser.add_argument("--max-tokens", type=int, default=280, help="Max completion tokens.")
    parser.add_argument("--fallback-yaw-degrees", type=float, default=20.0, help="Fallback camera yaw when LLM call fails.")
    parser.add_argument(
        "--allow-fallback-action",
        action="store_true",
        help="Allow non-LLM fallback action when LLM call fails (default: disabled, strict LLM mode).",
    )
    parser.add_argument("--verbose", action="store_true", help="Print iteration progress.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    bridge_dir = args.bridge_dir.expanduser().resolve()
    observe_path = bridge_dir / "observe.json"
    decide_path = bridge_dir / "decide.json"

    api_key = str(args.api_key or "").strip()
    if not api_key:
        import os

        api_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
    if not api_key:
        raise BridgeDeciderError("OPENAI_API_KEY is required for LLM decider.")

    last_iteration = 0
    poll_interval = max(0.05, _safe_float(args.poll_interval_seconds, 0.2))

    if args.verbose:
        print(f"[bridge_decider_llm] bridge_dir={bridge_dir}")
        print(f"[bridge_decider_llm] model={args.model}")

    while True:
        observe = _read_json(observe_path)
        if observe is None:
            time.sleep(poll_interval)
            continue

        iteration = _safe_int(observe.get("iteration"), 0)
        if iteration <= 0 or iteration == last_iteration:
            time.sleep(poll_interval)
            continue

        run_id = str(observe.get("run_id", "")).strip()
        session_id = str(observe.get("session_id", "")).strip()
        try:
            decision = _decide_once(
                observe_payload=observe,
                api_base_url=args.api_base_url,
                api_key=api_key,
                model=args.model,
                timeout_seconds=max(1.0, _safe_float(args.request_timeout_seconds, 45.0)),
                temperature=max(0.0, min(2.0, _safe_float(args.temperature, 0.0))),
                max_tokens=max(80, _safe_int(args.max_tokens, 280)),
            )
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}:{exc}"
            if args.allow_fallback_action:
                decision = _fallback_decision(
                    run_id=run_id,
                    session_id=session_id,
                    iteration=iteration,
                    error_text=error_text,
                    fallback_yaw_degrees=_safe_float(args.fallback_yaw_degrees, 20.0),
                )
            else:
                decision = _llm_error_failure_decision(
                    run_id=run_id,
                    session_id=session_id,
                    iteration=iteration,
                    error_text=error_text,
                )

        _write_json_atomic(decide_path, decision)
        last_iteration = iteration

        if args.verbose:
            print(
                f"[bridge_decider_llm] iteration={iteration} "
                f"status={decision.get('status')} "
                f"actions={len(decision.get('actions', []))}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
