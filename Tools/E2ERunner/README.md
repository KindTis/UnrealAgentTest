# E2ERunner

`e2e_runner.py`는 Unreal Remote API를 사용해 E2E 시나리오를 실행하고, 결과를 `Artifacts/E2ERunner/runs/<run_id>/report.json`에 저장합니다.

지원 intent:

- `defeat_monster`
- `movement_jump_sequence`
- `workflow_steps`
- `vision_navigation`

## 실행

### launch 모드

UnrealEditor를 함께 띄워 실행합니다.

```powershell
python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --scenario-file .\scenario.json
```

### attach 모드

이미 실행 중인 프로세스에 붙어 실행합니다.

```powershell
python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:31001 --scenario-file .\scenario.json
```

## `vision_navigation`

`vision_navigation`은 파일 브리지(`observe.json` / `decide.json`)로 판단을 주고받는 흐름입니다.

기본 운영 모드:

- decider 주체는 AI Agent(Sub)입니다.
- AI Agent가 `observe.json`(이미지 포함)을 반복 판독하고 `decide.json`을 작성합니다.
- 즉, 테스트 주도권은 AI Agent가 가지며, 화면 모니터링과 입력 결정을 직접 수행합니다.

선택 운영 모드:

- 필요 시 `bridge_decider_llm.py`로 API 기반 decider를 붙일 수 있습니다.
- 이 경로는 자동화 보조 수단이며 기본값이 아닙니다.

- observe: `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/observe.json`
- decide: `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/decide.json`
- lock: `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/bridge.lock`

동작 순서:

1. 러너가 화면 캡처와 상태를 `observe.json`에 기록합니다.
2. AI Agent(decider)가 `decide.json`에 액션 JSON을 기록할 때까지 대기합니다.
3. 러너가 액션을 검증한 뒤 `send_command`로 실행합니다.
4. 성공 조건이 만족될 때까지 반복합니다.

실전 운영 절차(다른 에이전트 재현용):

- `Tools/E2ERunner/VISION_DECIDER_RUNBOOK.md`
- Runner 실행, `observe.json` 실시간 판독, `decide.json` 원자적 쓰기, `bridge.lock` 재시도 처리, 금지사항(red-pixel 로직 추가 금지)을 포함합니다.

### 성공 판정

- `position`: `goal.position_target`이 있으면 좌표 판정이 우선입니다.
- `visual`: 시각 목표와 캡처 결과를 기준으로 판정합니다.
- `hybrid`: 좌표와 시각 목표를 모두 사용할 수 있으며, `goal.position_target`이 있으면 좌표 판정을 먼저 적용합니다.

### 캡처 기준

스크린샷은 세로 `height` 기준으로 요청하고, `preserve_aspect_ratio=true`를 유지합니다. 즉 실제 폭은 종횡비를 보존하는 방식으로 자동 결정됩니다.

기본값:

- `height=360`
- `preserve_aspect_ratio=true`
- `jpeg_quality=60`

### 즉시 실패 조건

아래 상태는 화면 판독이 불가능한 상태로 간주하고 즉시 실패 처리합니다.

- `viewport_minimized`

`viewport_occluded`는 다음 경우에 즉시 실패로 간주합니다.

- 캡처 소스가 `game_viewport` 또는 `pie_viewport`인 경우
- 또는 이미지 payload 자체가 없는 경우

캡처 소스가 `scene_capture_2d_game` / `scene_capture_2d_pie`이고 이미지 payload가 있으면 `is_occluded=true`라도 판독을 계속 진행합니다.

`capture_timeout`, `capture_unavailable`는 `failure_criteria.capture_failure_limit` 한도까지 재시도 후 실패 처리합니다.

## 결과

- `report.json`: 실행 결과 요약
- `unreal.log`: `--launch` 모드에서 생성되는 Unreal 로그
- `bridge/`: `vision_navigation`의 observe/decide 교환 파일

`report.json` 스키마는 `Tools/E2ERunner/report_schema.json`을 따릅니다.
