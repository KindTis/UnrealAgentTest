# E2ERunner Agent Workflow

이 문서는 `E2ERunner`를 사용할 때의 기본 점검 기준을 정리합니다.

## 0. Decider 원칙

- 기본 decider는 AI Agent(Sub)입니다.
- AI Agent가 `observe.json`을 실시간에 가깝게 반복 판독하고 `decide.json`을 작성합니다.
- API 기반 decider(`bridge_decider_llm.py`)는 선택 경로이며 기본값이 아닙니다.

## 1. 시나리오 준비

`vision_navigation` 시나리오는 다음 필드를 준비해야 합니다.

- `goal`
- `success_criteria`
- `failure_criteria`
- `loop`
- `capture`
- `decision_bridge`
- `termination`

### `goal`

- `description`과 `visual_target`은 선택 항목입니다.
- `position_target`을 지정할 수 있습니다.
- `success_mode`가 `position` 또는 `hybrid`일 때 `position_target`이 있으면 좌표 판정이 우선합니다.
- `success_mode`가 `visual`이면 좌표는 사용하지 않습니다.

### `success_criteria`

- `timeout_seconds`
- `completion_state = goal_reached`
- `success_mode = position | visual | hybrid`

### `failure_criteria`

- `input_failure_limit`
- 필요 시 `capture_failure_limit`
- 화면이 최소화된 상태는 즉시 실패로 처리합니다.

### `loop`

- `max_iterations`
- `observe_interval_seconds`
- `capture_timeout_seconds`
- `action_timeout_seconds`

### `capture`

- 스크린샷은 세로 `height` 기준으로 요청합니다.
- `preserve_aspect_ratio=true`를 유지해야 합니다.
- 기본값은 `height=360`, `preserve_aspect_ratio=true`, `jpeg_quality=60`입니다.

### `decision_bridge`

- `mode = file`
- `decide_wait_timeout_seconds`
- `decide_retry_count`

## 2. 실행 흐름

`vision_navigation`은 다음 순서로 반복됩니다.

1. 러너가 화면 캡처와 상태를 `observe.json`에 기록합니다.
2. AI Agent(decider)가 `observe.json`을 판독하고 `decide.json`에 액션 JSON을 기록합니다.
3. 러너가 JSON을 검증하고 액션을 실행합니다.
4. 성공 조건이 충족되거나 실패 조건에 걸릴 때까지 반복합니다.

## 3. 즉시 실패 조건

아래 상태는 "판독 불가"로 간주합니다.

- `viewport_minimized`

`viewport_occluded`는 다음에만 "판독 불가"로 간주합니다.

- 캡처 소스가 `game_viewport` 또는 `pie_viewport`인 경우
- 또는 이미지 payload가 없는 경우

캡처 소스가 `scene_capture_2d_game` / `scene_capture_2d_pie`이고 이미지 payload가 있으면 판독을 계속 진행합니다.

캡처 응답이 지연되거나 누락되면 다음 순서로 처리합니다.

1. 타임아웃 기록
2. 실패 카운트 증가
3. 한도 초과 시 즉시 실패

## 4. 성공 판정 우선순위

- `position`: 좌표가 있으면 좌표 판정을 우선 사용합니다.
- `visual`: 시각 목표를 기준으로 판정합니다.
- `hybrid`: 좌표를 우선 사용하고, 필요 시 시각 판정으로 보완합니다.

## 5. 보고 기준

최소한 다음 결과를 확인합니다.

- `run_id`
- `ok`
- `success.success_condition`
- 실패 시 `failure` 사유
- `report.json` 저장 경로
