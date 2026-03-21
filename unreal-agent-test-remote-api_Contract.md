# unreal-agent-test-remote-api Contract (v1)

## 목적
- 서버(C++)/SDK(Python)/오케스트레이션 간 공통 계약(API, 이벤트, 에러, `trace_id`)을 고정한다.
- 본 문서는 현재 구현(`codex/Dev`, 2026-03-22 기준)을 계약 기준선으로 문서화한다.

## 공통 규칙
- 인코딩: UTF-8
- 전송: HTTP(JSON), WebSocket(text JSON)
- 시간 필드:
  - HTTP 응답/이벤트 기본: ISO-8601 UTC 문자열
  - WebSocket 이벤트: `time` 필드에 ISO-8601 UTC 문자열
- 로컬 바인딩: `localhost`/`127.0.0.1`만 허용

## trace_id / sequence_id 규칙
- `trace_id`
  - 요청 `trace_id`가 비어 있으면 서버가 UUID(`digits-with-hyphens-lower`) 생성
  - 명령 관련 이벤트는 해당 명령 `trace_id`를 그대로 사용
- `sequence_id`
  - 세션별 독립 증가 정수(1부터 시작)
  - `/events?after_sequence=N`은 `sequence_id > N`만 반환
  - `last_sequence`는 해당 세션의 최신 시퀀스
- 이벤트 버퍼
  - 세션당 최대 256개(초과 시 오래된 이벤트부터 제거)

## HTTP API 계약

### 1) `GET /health`
- 200 OK
```json
{
  "status": "ok",
  "service": "unreal-agent-test-remote-api",
  "timestamp": "2026-03-22T00:00:00Z",
  "running": true,
  "port": 31001,
  "active_sessions": 1
}
```

### 2) `GET /capabilities`
- 200 OK
- 필수 필드:
  - `service`, `version`, `timestamp`
  - `routes[]`
  - `session_fields[]`
  - `events_query_fields[]`
- 선택 필드:
  - `events_websocket_url` (예: `ws://127.0.0.1:31002/events`)
  - `events_websocket_port`

### 3) `POST /session/start`
- 요청(JSON):
  - 선택: `session_id`, `run_id`
- 응답:
  - 200 OK: `accepted=true`, `session_id`, `run_id`, `started_at`, `active_sessions`
  - 400 Bad Request: `invalid_json`

### 4) `POST /session/stop`
- 요청(JSON):
  - 필수: `session_id`
- 응답:
  - 200 OK: `accepted=true`, `session_id`, `active_sessions`
  - 404 Not Found: `accepted=false`, `error=session_not_found`
  - 400 Bad Request: `missing_field`/`invalid_json`

### 5) `POST /command/execute`
- 요청(JSON):
  - 필수: `session_id`, `command`
  - 선택: `trace_id`, `args`(object)
- 지원 `command`:
  - `attack`
    - `target_id` 선택(비어 있지 않아야 함)
  - `tap_button`
    - `button_id` 필수, `duration_ms` 선택(양수)
  - `move_stick`
    - `stick_id`, `x`, `y` 필수 (`x`,`y`는 -1..1), `duration_ms` 선택(양수)
  - `release_stick`
    - `stick_id` 필수
  - `execute_recipe`
    - `recipe_id` 필수, `args` 선택(object)
- 성공 응답(200):
  - `accepted=true`
  - `command`, `trace_id`, `timestamp_utc`
  - `implementation_status=native_input`
  - `details` (아래 공통 상세 구조 포함)
- 실패 응답:
  - 400: 검증 실패 또는 실행 실패
  - 404: `session_not_found`

### 6) `GET /state/player`
### 7) `GET /state/target`
- 쿼리:
  - 필수: `session_id`
- 응답(200):
  - `type`, `timestamp`, `actor_id`, `alive`, `health`, `max_health`
  - `location{x,y,z}`, `rotation{pitch,yaw,roll}`
  - `status`, `current_target_id`, `equipped_weapon_id`, `current_action`, `team_id`
  - 메타: `session_id`, `last_command_name`, `last_trace_id`, `last_updated_utc`
- 오류:
  - 400: `missing_query`
  - 404: `session_not_found`

### 8) `GET /state/spatial`
- 쿼리:
  - 필수: `session_id`
  - 선택 override: `distance_cm`, `yaw_delta_degrees`, `recommended_left_stick_x`, `recommended_left_stick_y`, `navigation_path_length_cm`, `line_of_sight`, `target_in_attack_range`
- 응답(200):
  - `type=spatial_state`, `timestamp`
  - `session_id`, `trace_id`, `player_actor_id`, `target_actor_id`
  - `player_location`, `target_location`, `direction_to_target`
  - `player_forward_vector`, `target_forward_vector`
  - `distance_cm`, `yaw_delta_degrees`
  - `recommended_left_stick_x`, `recommended_left_stick_y`
  - `navigation_path_length_cm`, `line_of_sight`, `target_in_attack_range`
  - 메타: `last_command_name`, `last_trace_id`, `last_updated_utc`
- 오류:
  - 400: `missing_query`
  - 404: `session_not_found`

### 9) `GET /events`
- 쿼리:
  - 필수: `session_id`
  - 선택: `type`, `limit`, `after_sequence`
- 응답(200):
```json
{
  "session_id": "session-1",
  "timestamp": "2026-03-22T00:00:00Z",
  "events": [
    {
      "session_id": "session-1",
      "trace_id": "uuid",
      "sequence_id": 12,
      "timestamp": "2026-03-22T00:00:00Z",
      "type": "command_step_succeeded",
      "payload": {}
    }
  ],
  "last_sequence": 12
}
```
- `after_sequence`/`type`/`limit`를 요청하면 응답에도 해당 필드가 함께 노출될 수 있다.
- 오류:
  - 400: `missing_query`
  - 404: `session_not_found`

## WebSocket 이벤트 계약
- endpoint: `GET /capabilities`의 `events_websocket_url`
- 메시지 포맷(JSON):
```json
{
  "session_id": "session-1",
  "type": "command_accepted",
  "sequence_id": 13,
  "time": "2026-03-22T00:00:01Z",
  "trace_id": "uuid",
  "payload": {}
}
```
- 주의:
  - WS 이벤트 시간 필드는 `timestamp`가 아니라 `time`이다.
  - SDK는 `session_id`/`sequence_id` 기반으로 이벤트를 필터링하고, WS 실패 시 HTTP 폴링으로 폴백한다.

## 명령 응답 `details` 공통 구조
- 공통 키:
  - `command_name`, `trace_id`
  - `execution_state`, `validation_state`
  - `implementation_status`
  - `error_stage` (실패 시)
  - `command_step` object
  - `normalized_args` object
  - `input_execution` object(실행기 결과)
- 실행 실패 표준:
  - `accepted=false`
  - `error_code=input_execution_failed`
  - `error_stage=execution`
  - `implementation_status=native_input`

## 이벤트 타입 계약
- 명령/스텝:
  - `command_accepted`
  - `command_rejected`
  - `command_step_started`
  - `command_step_succeeded`
  - `command_step_failed`
- 전투 커스텀:
  - `damage_applied`
  - `actor_died`
- 일반:
  - `error`

## 에러 코드 계약
- 공통/라우팅:
  - `invalid_json`
  - `missing_field`
  - `missing_query`
  - `session_not_found`
- 명령 검증:
  - `unsupported_command`
  - `invalid_field`
- 명령 실행:
  - `input_execution_failed`

## SDK 호환 규칙
- `wait_for_event()`는 다음 우선순위를 따른다.
  1. `events_websocket_url` 기반 WS 수신
  2. 실패 시 `/events` 폴링
- 커서(`after_sequence`)는 WS/HTTP 경로 간 연속성을 유지한다.

## 변경 관리
- 본 계약 변경 시 반드시 다음을 함께 갱신한다.
  - 서버 구현(C++)
  - SDK 구현(Python)
  - `unreal-agent-test-remote-api_CheckList.md`
  - `unreal-agent-test-remote-api_Context.md`
