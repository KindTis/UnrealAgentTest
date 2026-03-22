# unreal-agent-test-remote-api CheckList

## Todo
- [ ] 없음.

## In Progress
- [ ] 없음.

## Blocked
- [ ] 없음.

## Done
- [x] Planning Request 분류 및 스킬 가이드 적용.
- [x] FeatureName 정규화: `unreal-agent-test-remote-api`.
- [x] Plan/Context/CheckList 초기 문서 세트 생성.
- [x] 오케스트레이션 에이전트 기반 작업 분배 구조 정의.
- [x] `IA-01`: Phase 1 최소 세션 서버(`/health`, `/capabilities`, `/session/start`, `/session/stop`) 구현.
- [x] `OA-00`: 멀티 에이전트 생성 및 병렬 업무 분배(Loop 2: `IA-02`, `IA-03`).
- [x] `IA-02`: `GameTestCommandService` 1차 구현(`attack`, `tap_button`, `move_stick`, `release_stick`, `execute_recipe` 검증/응답).
- [x] `IA-03`: `GameTestQueryService`, `GameTestEventRecorder` 1차 구현.
- [x] `OA-00`: 서버 라우팅 1차 통합(`/command/execute`, `/state/player`, `/state/target`, `/events`).
- [x] `OA-00`: 멀티 에이전트 생성 및 병렬 업무 분배(Loop 3: `IA-02`, `IA-03`).
- [x] `IA-02`: 명령 응답 details 표준화(`command_step`, `normalized_args`, `error_stage`).
- [x] `IA-03`: 이벤트 레코더 확장(`command_step_started/succeeded/failed`, `type_filter`, `limit`).
- [x] `IA-03`: `FGameTestSpatialStateInput` 기반 spatial 상태 모델 확장.
- [x] `OA-00`: 서버 라우팅 2차 통합(`/state/spatial`, `/events?type&limit`, command step 이벤트 기록).
- [x] `OA-00`: 멀티 에이전트 생성 및 병렬 업무 분배(Loop 4: `IA-04`, `IA-05`).
- [x] `IA-04`: Python 기반 UnrealTestClient SDK 구현(`connect/start_session/send_command/get_state/get_events/wait_for_event`).
- [x] `IA-04`: 룰 기반 상태 해석기 구현(`damage_applied`, `actor_died`, `command_step_*`).
- [x] `IA-05`: 병렬 실행 계획 런처 구현(run/session/port/artifact/command plan 생성, plan-only 기본 모드).
- [x] `OA-00`: 멀티 에이전트 생성 및 병렬 업무 분배(Loop 5: `IA-03`, `IA-05`).
- [x] `IA-03`: WebSocket 이벤트 스트림 구현(신규 이벤트 push, `events_websocket_url` capability 노출).
- [x] `IA-05`: `--execute` 생명주기 강화(status/timeout/terminate/kill/실행시간 수집).
- [x] `OA-00`: 멀티 에이전트 생성 및 병렬 업무 분배(Loop 6: `IA-02`, `IA-04`).
- [x] `IA-02`: 실제 입력 실행기(`GameTestInputExecutor`) 연결 및 실행 실패 표준화(`input_execution_failed`, `error_stage=execution`).
- [x] `IA-04`: SDK `wait_for_event` WebSocket 우선 소비 + HTTP 폴백 구현.
- [x] `OA-00`: ThirdPersonAction 기준 빌드/컴파일 검증 5회 수행.
- [x] `OA-00`: API/이벤트/에러/trace_id 공통 계약 문서 고정(`unreal-agent-test-remote-api_Contract.md`).
- [x] `OA-00`: `Tools/SmokeRunner/smoke_runner.py` 기반 `-TestMode` HTTP+WS 스모크 자동화 스크립트 구현.
- [x] `OA-00`: `Tools/SmokeRunner/smoke_runner.py --launch --base-url http://127.0.0.1:31001 --extra-arg=-game --health-timeout 240` 실호출 스모크 통과.
- [x] `OA-00`: `Tools/E2ERunner/e2e_runner.py` 기반 E2E 자동화(장착→접근→공격→처치) 구현 및 리포트 스키마 정합화.
- [x] `OA-00`: `python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --health-timeout 90 --poll-interval 0.2` 실호출 E2E 통과(`ok=true`, run_id=`e2e-20260322T035026Z-3526`).
- [x] `IA-02`: `move_stick/release_stick` 축 입력 처리 결과와 명령 수락 판정 불일치 수정(`GameTestInputExecutor`).
- [x] `IA-01`: 엔진 종료 단계 `HTTPServer` 모듈 언로드 이후 `StopAllListeners` 호출로 인한 assert 방지 패치(`GameTestRemoteServer::Stop`).
- [x] `OA-00`: 1차 마일스톤 완료 기준 확정(attach 기본, AI Agent 사전 작성 시나리오 JSON, 상태 기반 이동/공격/처치, 종료 옵션 포함).
- [x] `OA-00`: SDK 정책 확정(Python 공식, 저장소 내 포함형 비설치 기본, SDK/Main/Sub 계층 분리).
- [x] `OA-00`: 병렬 실행 정책 확정(`max_concurrent_sessions=2`, FIFO 대기열, `queue_wait_timeout=120s`, `session_timeout=180s`, 연결/헬스체크 실패 1회 재시도).
- [x] `OA-00`: 리소스 가드 임계값 0으로 고정(`cpu_percent_limit=0`, `memory_available_mb_limit=0`, 가드 무시).
- [x] `OA-00`: 초기 시나리오 최소 범위 확정(`"A무기로 정면 몬스터를 무찌르세요"`, 전방 ±45도 최단거리 타겟 규칙, 성공/실패/종료 옵션 기준).
- [x] `IA-04`: 시나리오 검증 모듈 추가(`Tools/E2ERunner/scenario_schema.py`), JSON 포맷 검증(`validate_scenario`) 적용.
- [x] `IA-04`/`IA-05`: `e2e_runner`를 시나리오 JSON 입력 전용(`--scenario-json`, `--scenario-file`)으로 정리하고 attach 기본 실행 경로 통합.
- [x] `IA-02`/`IA-03`: `e2e_runner`에 상태 기반 전투 루프 통합(전방 ±45도 판정, 이동/공격 반복, `actor_died`/`target_state.alive=false` 성공 판정).
- [x] `IA-05`: `e2e_runner` 종료 옵션(`keep_running`, `close_game`, `close_editor`) 반영 및 attach 모드 미적용 노트 처리.
- [x] `IA-05`: `parallel_runner` 병렬 정책 구현(`max_concurrent_sessions=2`, FIFO queue, `queue_wait_timeout=120s`, `session_timeout=180s`, 리소스 가드 기본값 0 비활성).
- [x] `IA-04`: `e2e_runner`에서 자연어/LLM 컴파일 의존 제거 및 AI Agent 작성 JSON 실행 흐름으로 단순화.
- [x] `IA-04`: `movement_jump_sequence` intent 추가(카메라 정렬→전진 2초→점프→후진 2초) 및 ThirdPerson 맵 검증용 시나리오 샘플 제공.

## Validation Status
- Passed: `ThirdPersonActionEditor Win64 Development` 빌드 성공 (2026-03-22, Loop 6 통합 반영 후).
- Passed: `ThirdPersonActionEditor Win64 Development` 빌드 성공 (2026-03-22, Loop 5 통합 반영 후).
- Passed: `ThirdPersonActionEditor Win64 Development` 빌드 성공 (2026-03-22, Loop 3 통합 반영 후).
- Passed: `ThirdPersonActionEditor Win64 Development` 빌드 성공 (2026-03-22, Loop 2 통합 반영 후).
- Passed: `ThirdPersonActionEditor Win64 Development` 빌드 성공 (2026-03-22, IA-01 단계).
- Passed: `python -m py_compile` (UnrealTestClient, ParallelRunner 모듈).
- Passed: `python -m py_compile` (SmokeRunner, UnrealTestClient 모듈).
- Passed: `python Tools/ParallelRunner/parallel_runner.py --count 1 --base-port 31011 ...` plan-only JSON 출력 검증.
- Passed: `python Tools/SmokeRunner/smoke_runner.py --launch --base-url http://127.0.0.1:31001 --extra-arg=-game --health-timeout 240` (`ok=true`, run_id=`smoke-20260321T170217Z-4250`).
- Passed: WebSocket 실시간 이벤트 수신 + WS 실패 시 HTTP 폴백 검증(`events_websocket_live=true`, `events_http_fallback=true`).
- Passed: `python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --health-timeout 90 --poll-interval 0.2` (`ok=true`, run_id=`e2e-20260322T035026Z-3526`).
- Passed: `Artifacts/E2ERunner/runs/e2e-20260322T035026Z-3526/report.json` JSON 스키마 검증 통과(`schema_validation:OK`).
- Passed: `ThirdPersonActionEditor Win64 Development` 빌드 성공 (2026-03-22, 종료 안정성 패치 반영 후).
- Passed: `python -m py_compile Tools/E2ERunner/e2e_runner.py`.
- Passed: `python -m py_compile Tools/E2ERunner/scenario_schema.py`.
- Passed: `python -m py_compile Tools/ParallelRunner/parallel_runner.py`.
- Passed: `python Tools/E2ERunner/e2e_runner.py --help` (신규 CLI 옵션 노출 확인).
- Passed: `python Tools/ParallelRunner/parallel_runner.py --help` (정책 CLI 옵션 노출 확인).
- Passed: `python Tools/E2ERunner/e2e_runner.py --help` (시나리오 JSON 입력 전용 CLI 확인).
- Passed: `python Tools/ParallelRunner/parallel_runner.py --count 1 --base-port 30000 --artifacts-root .\\Artifacts\\ParallelRunner_Sample` (`policy` 블록 출력 확인).
- Passed: `python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:39999 --scenario-file .\\Artifacts\\E2ERunner\\sample_scenario.json --health-timeout 0.2 --poll-interval 0.05` (attach 경로 JSON 입력/검증 후 헬스체크 타임아웃 정상 실패 확인, run_id=`e2e-20260322T052640Z-44b1`).
- Passed: `python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:39999 --scenario-file Tools/E2ERunner/sample_movement_jump_scenario.json --health-timeout 0.2 --poll-interval 0.05` (`movement_jump_sequence` 스키마 검증 및 attach 경로 헬스체크 타임아웃 정상 실패 확인, run_id=`e2e-20260322T054155Z-4a97`).
- Passed: `python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:39999 --scenario-file Tools/E2ERunner/sample_defeat_monster_scenario.json --health-timeout 0.2 --poll-interval 0.05` (`defeat_monster` 회귀 검증, run_id=`e2e-20260322T054155Z-ffb6`).

## Deferred / Out of Scope
- [ ] Shipping 빌드 상시 활성화 원격 제어 기능.
- [ ] Public network 바인딩 지원.
- [ ] OCR 기반 판정을 핵심 성공 기준으로 채택하는 기능.
- [ ] 엔진 소스 직접 수정/엔진 포크 의존 구현.
