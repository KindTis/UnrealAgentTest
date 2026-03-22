# Movement Decider Mode

## 목적

`movement_jump_sequence`를 매크로 순차 실행이 아니라, phase 단위로 decider가 관측 후 입력 결정을 내리는 방식으로 실행합니다.

## 시나리오 포맷

`sequence.decision_mode`를 `decider`로 지정하면 활성화됩니다.

```json
{
  "intent": "movement_jump_sequence",
  "sequence": {
    "decision_mode": "decider",
    "decision_bridge": {
      "mode": "file",
      "decide_wait_timeout_seconds": 30.0,
      "decide_retry_count": 1,
      "decide_poll_interval_seconds": 0.1
    },
    "phases": [
      {"name": "forward", "move_x": 0.0, "move_y": 1.0, "duration_seconds": 2.0, "jump_after": true},
      {"name": "backward", "move_x": 0.0, "move_y": -1.0, "duration_seconds": 2.0, "jump_after": false}
    ]
  }
}
```

## 브리지 파일

- `observe.json`: `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/observe.json`
- `decide.json`: `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/decide.json`
- `bridge.lock`: `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/bridge.lock`

`observe.json.kind`는 `movement_jump_observe`입니다.

## decide.json 형식

```json
{
  "schema_version": 1,
  "run_id": "e2e-xxxx",
  "session_id": "session-xxxx",
  "iteration": 1,
  "status": "continue",
  "reason": "forward phase 진행",
  "actions": [
    {"action": "move_stick", "args": {"stick_id": "left_stick", "x": 0.0, "y": 1.0, "duration_ms": 300}},
    {"action": "tap_button", "args": {"button_id": "jump", "duration_ms": 220}},
    {"action": "release_stick", "args": {"stick_id": "left_stick"}}
  ]
}
```

`status`는 `continue | success | failure`를 사용합니다.

- `continue`: 해당 phase 액션 실행 후 다음 phase로 진행
- `success`: 해당 phase 실행 후 시나리오 즉시 성공 종료
- `failure`: 즉시 실패 종료
