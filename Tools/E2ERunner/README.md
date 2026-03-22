# E2ERunner

`e2e_runner.py`는 `equip -> approach -> attack -> kill` 흐름의 E2E 시나리오를 실행하고, 결과를 JSON으로 저장합니다.
시나리오 JSON은 AI Agent가 포맷 사양에 맞춰 작성한 값을 입력으로 사용합니다.

## 실행 방법

### launch 모드
Unreal을 함께 띄워서 E2E를 실행합니다.

```powershell
python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --scenario-file .\scenario.json
```

### attach 모드
이미 실행 중인 `-TestMode` 서버에 붙어서 E2E를 실행합니다. `--launch`를 주지 않으면 기본값은 `attach`입니다.

```powershell
python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:31001 --scenario-file .\scenario.json
```

종료 정책은 `--termination-mode keep_running|close_game|close_editor`로 지정합니다.

## 시나리오 JSON 입력

```powershell
python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:31001 --scenario-json "{...}"
```

필수 필드는 아래를 포함해야 합니다.

- `schema_version`, `source_text`, `language`, `intent`, `weapon`
- `target_selector` (`type=forward_cone`, `relative_to=player_forward`, `target_kind=monster`)
- `success_criteria` (`timeout_seconds`, `target_state=defeated`)
- `failure_criteria` (`target_lost_timeout_seconds`, `input_failure_limit`)
- `termination.mode` (`keep_running|close_game|close_editor`)

`intent`는 아래 2가지를 지원합니다.

- `defeat_monster`: 전투 시나리오(장착→접근→공격→처치)
- `movement_jump_sequence`: ThirdPerson 이동/점프 시나리오(카메라 정렬→전진→점프→후진)

샘플 파일:

- `Tools/E2ERunner/sample_defeat_monster_scenario.json`
- `Tools/E2ERunner/sample_movement_jump_scenario.json`

### ThirdPerson 이동/점프 시나리오 예시

```json
{
  "schema_version": 1,
  "source_text": "카메라를 정면으로 고정하고, 정면으로 2초 이동 후 점프하고, 뒤로 2초 이동한다.",
  "language": "ko",
  "intent": "movement_jump_sequence",
  "sequence": {
    "camera_lock_stick_id": "right_stick",
    "move_stick_id": "left_stick",
    "forward_seconds": 2.0,
    "backward_seconds": 2.0,
    "jump_button_id": "jump",
    "jump_duration_ms": 220,
    "jump_settle_seconds": 1.0,
    "move_x": 0.0,
    "forward_y": 1.0,
    "backward_y": -1.0,
    "pulse_interval_seconds": 0.1
  },
  "success_criteria": {
    "timeout_seconds": 20,
    "completion_state": "sequence_completed"
  },
  "failure_criteria": {
    "input_failure_limit": 3
  },
  "termination": {
    "mode": "keep_running"
  }
}
```

## 성공 기준

- `result.ok`가 `true`
- `success.success_condition`이 intent별 기대값과 일치
- `defeat_monster`에서는 `final_state.target_state.alive`가 `false`
- `movement_jump_sequence`에서는 `success.success_condition=sequence_completed`
- 세션 종료가 정상 처리됨
- intent별 시나리오 루프가 중단 없이 완료됨

`success.success_condition`은 최종 판정 근거입니다. `defeat_monster`에서는 `target_state.alive=false` 또는 `actor_died_event`가 성공 기준이고, `movement_jump_sequence`에서는 `sequence_completed`가 성공 기준입니다.

## 결과 출력 경로

- 리포트: `Artifacts/E2ERunner/runs/<run_id>/report.json`
- Unreal 로그: `launch.log_path`

`report.json`은 실행 결과 전체를 담는 최종 산출물입니다. `launch.log_path`는 `--launch` 모드에서만 생성되며, UnrealEditor의 표준 출력과 에러 로그를 기록합니다.

## 참고

리포트 JSON 필드 규약은 [`report_schema.json`](./report_schema.json)에 있습니다.
