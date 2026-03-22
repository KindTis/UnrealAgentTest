# Agent Workflow for E2ERunner

This document defines a stable automation flow for AI agents:

1. Create scenario JSON
2. Run `e2e_runner.py`
3. Verify `report.json` using `verify_report.py`

## 1) Scenario JSON

Use templates:

- `Tools/E2ERunner/templates/movement_jump_sequence.template.json`
- `Tools/E2ERunner/templates/defeat_monster.template.json`
- `Tools/E2ERunner/templates/workflow_steps.template.json`

### Multi-step movement and jump

`movement_jump_sequence` supports `sequence.phases`:

```json
{
  "name": "left",
  "move_x": -1.0,
  "move_y": 0.0,
  "duration_seconds": 2.0,
  "jump_after": true
}
```

When `sequence.phases` is omitted, runner uses legacy flow:
`forward -> jump -> backward`.

### Conditional flow (`workflow_steps`)

`workflow_steps` supports `steps[]` and per-step `when` condition.

```json
{
  "name": "move_after_target_down",
  "action": "move_to_location",
  "when": {
    "state": "target_state",
    "path": "alive",
    "op": "eq",
    "value": false
  },
  "args": {
    "x": 300.0,
    "y": 100.0,
    "tolerance_cm": 30.0,
    "max_seconds": 15.0
  }
}
```

## 2) Execute

### Attach mode

```powershell
python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:31001 --scenario-file Artifacts/E2ERunner/scenarios/<name>.json --termination-mode keep_running
```

`auto_play_editor` is requested by default at `session_start`.
If you want strict validation that server-side auto-play is available:

```powershell
python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:31001 --scenario-file Artifacts/E2ERunner/scenarios/<name>.json --require-auto-play-editor
```

### Launch mode (Editor)

```powershell
python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --scenario-file Artifacts/E2ERunner/scenarios/<name>.json --termination-mode keep_running
```

When a launch run fails, the runner now keeps the launched process alive by default (`--keep-process-on-failure`) for debugging.

### Launch mode (Game)

```powershell
python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --scenario-file Artifacts/E2ERunner/scenarios/<name>.json --termination-mode keep_running --extra-arg=-game
```

## 3) Verify

```powershell
python Tools/E2ERunner/verify_report.py --report Artifacts/E2ERunner/runs/<run_id>/report.json --expect-intent movement_jump_sequence
```

Require exact accepted jump count:

```powershell
python Tools/E2ERunner/verify_report.py --report Artifacts/E2ERunner/runs/<run_id>/report.json --expect-intent movement_jump_sequence --require-jump-count 3
```

Workflow example:

```powershell
python Tools/E2ERunner/verify_report.py --report Artifacts/E2ERunner/runs/<run_id>/report.json --expect-intent workflow_steps
```

## Output contract

Agents must report:

- `run_id`
- `ok`
- `success.success_condition`
- failure detail when failed
- absolute path to `report.json`
