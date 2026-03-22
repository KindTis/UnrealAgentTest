# unreal-agent-test-remote-api Context

## Date / Session
- Date: 2026-03-22 (KST)
- Session 1: Planning Request 처리
- Session 2: Implementation Request 처리 (Loop 1, IA-01 Phase 1)
- Session 3: Multi-Agent Implementation 처리 (Loop 2, IA-02 + IA-03 + OA 통합)
- Session 4: Multi-Agent Implementation 처리 (Loop 3, IA-02 + IA-03 + OA 통합)
- Session 5: Multi-Agent Implementation 처리 (Loop 4, IA-04 + IA-05 병렬 구현)
- Session 6: Multi-Agent Implementation 처리 (Loop 5, IA-03 + IA-05 병렬 구현)
- Session 7: Multi-Agent Implementation 처리 (Loop 6, IA-02 + IA-04 병렬 구현)
- Session 8: Implementation Request 처리 (OA-00 계약 문서 고정)
- Session 9: Implementation Request 처리 (OA-00 `-TestMode` 스모크 자동화 스크립트 구현)
- Session 10: Validation Run 처리 (`Tools/SmokeRunner/smoke_runner.py` 실호출 스모크 실행)
- Session 11: Multi-Agent Implementation 처리 (OA-00 + IA-02 + IA-04, E2E 자동화 고도화)
- Session 12: Validation Run 처리 (`Tools/E2ERunner/e2e_runner.py --launch` 실호출 E2E 실행)
- Session 13: Implementation Request 처리 (`move_stick/release_stick` 판정 불일치 수정)
- Session 14: Implementation Request 처리 (엔진 종료 시 `HTTPServer` 모듈 언로드 assert 방지)
- Session 15: Maintenance / Update Request 처리 (1차 마일스톤 확정 항목 + SDK 정책 반영)
- Session 16: Maintenance / Update Request 처리 (병렬 세션 정책/초기 시나리오 범위 수치 확정)
- Session 17: Multi-Agent Implementation 처리 (상태 기반 전투 루프 + 병렬 정책 코드 반영)
- Session 18: Maintenance / Update Request 처리 (입력 판정/종료 안정성 개선)
- Session 19: Maintenance / Update Request 처리 (시나리오 JSON 입력 정책 고정, 런타임 컴파일러 제거)
- Applied Guide: `feature-implementation-workflow/Planning_Request_Guide.md`
- Applied Guide: `feature-implementation-workflow/Implementation_Request_Guide.md`

## Change Summary
- `OA-00` 오케스트레이션 에이전트가 E2E 기준선(장착→접근→공격→처치)과 리포트 스키마를 고정했다.
- `IA-04` 워커가 `Tools/E2ERunner/e2e_runner.py`를 구현해 `--launch` 실호출 자동 실행 및 결과 리포트 생성 흐름을 완성했다.
- `OA-00` 통합 검증에서 `python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --health-timeout 90 --poll-interval 0.2`를 실행해 `ok=true`(run_id=`e2e-20260322T035026Z-3526`)를 확인했다.
- `IA-02`가 `GameTestInputExecutor`의 축 입력 처리 결과(`input_x_handled`, `input_y_handled`)와 명령 수락 판정 불일치를 수정해 false-negative를 해소했다.
- `IA-01`이 `FGameTestRemoteServer::Stop()` 종료 경로를 보강해 `HTTPServer` 모듈 언로드 이후 assert 발생을 방지했다.
- 사용자 결정에 따라 1차 마일스톤 기준을 attach 우선 실행, 상태 기반 이동/공격/처치, 종료 정책 옵션 포함으로 확정했다.
- SDK 정책을 "Python 공식 + 저장소 내 포함형(비설치 기본) + Main/Sub 분리 구조"로 확정했다.
- 병렬 실행 정책(`max_concurrent_sessions=2`, FIFO, `queue_wait_timeout=120s`, `session_timeout=180s`)과 리소스 가드 비활성(`0`)을 확정했다.
- 초기 시나리오 최소 범위를 `"A무기로 정면 몬스터를 무찌르세요"` 단일 기준선으로 확정했다.
- `IA-04`가 `Tools/E2ERunner/scenario_schema.py`를 추가해 시나리오 JSON 검증기(`validate_scenario`)를 구현했다.
- `IA-04`/`IA-05`가 `e2e_runner`를 시나리오 JSON 입력 전용(`--scenario-json`, `--scenario-file`)으로 정리하고 attach 기본 경로로 단순화했다.
- 런타임 자연어 컴파일 계층(`scenario_compiler.py`)과 관련 CLI 의존을 제거했다.
- 문서(Plan/Contract/CheckList/Context)를 "AI Agent 사전 작성 JSON 입력 + 로컬 검증 후 실행" 정책으로 동기화했다.

## Files Touched
- `UnrealAgentTest/Source/UnrealAgentTest/Public/GameTestInputExecutor.h` (신규)
- `UnrealAgentTest/Source/UnrealAgentTest/Private/GameTestInputExecutor.cpp` (신규/갱신)
- `UnrealAgentTest/Source/UnrealAgentTest/Private/GameTestCommandService.cpp` (갱신)
- `UnrealAgentTest/Source/UnrealAgentTest/Private/GameTestRemoteServer.cpp` (갱신)
- `UnrealAgentTest/Source/UnrealAgentTest/UnrealAgentTest.Build.cs` (갱신)
- `Tools/UnrealTestClient/unreal_test_client.py` (갱신)
- `Tools/SmokeRunner/smoke_runner.py` (신규)
- `Tools/E2ERunner/e2e_runner.py` (신규/갱신)
- `Tools/E2ERunner/scenario_schema.py` (신규)
- `Tools/E2ERunner/report_schema.json` (신규)
- `Tools/ParallelRunner/parallel_runner.py` (갱신)
- `unreal-agent-test-remote-api_Contract.md` (신규/갱신)
- `unreal-agent-test-remote-api_Plan.md` (갱신)
- `unreal-agent-test-remote-api_Context.md` (갱신)
- `unreal-agent-test-remote-api_CheckList.md` (갱신)

## Reasoning
- 실제 게임 내 이동이 확인되는데 E2E가 실패로 기록되는 문제는 신뢰도 저하가 크므로, 입력 처리 실패와 명령 수락 여부를 분리해 판정 규칙을 재정의했다.
- 종료 assert는 기능 성공 여부와 무관하게 런타임 안정성을 직접 해치므로 우선순위를 높여 패치했다.
- 1차 마일스톤의 성패를 launch 편의가 아니라 운영 시나리오(attach + 시나리오 JSON 실행)로 정의해야 사용자 목적과 검증 기준이 일치한다.
- 시나리오 생성 책임은 실행기(`e2e_runner`)가 아니라 상위 AI Agent에 두고, 실행기는 검증/실행 책임만 갖게 분리해야 변경 영향 범위를 최소화할 수 있다.

## Alternatives Considered
- 런타임 자연어 컴파일러 유지:
  - 장점: 단일 도구에서 입력부터 실행까지 가능.
  - 단점: 모델/키/네트워크 의존으로 실행 경로가 불안정해져 배제.
- 키워드 기반 로컬 파서 유지:
  - 장점: 오프라인/결정적 동작.
  - 단점: 문장 다양성 대응이 제한적이라 배제.
- JSON 입력 전용 + 로컬 스키마 검증 채택:
  - 장점: 실행 책임 범위가 명확하고 재현성이 높음.
  - 단점: 상위 Agent가 사전에 시나리오 JSON을 생성해야 함.

## Trade-offs
- 축 입력 best-effort 허용으로 명령 성공 판정은 안정화됐지만, 완전한 입력 보장은 프로젝트별 바인딩 구성에 의존한다.
- 종료 안정성 패치는 assert를 제거하지만, 모듈이 이미 언로드된 경우 리스너 정리 경로는 스킵된다(로그로 추적).
- 리소스 가드 비활성으로 고부하 상황 성능 저하 가능성은 남지만, 1차 기준선 단계에서는 장애 원인 축소 효과가 더 크다.
- 실행기의 입력 정책을 JSON 전용으로 고정하면서 유연성 일부를 포기하는 대신, 실행 실패 원인 추적 가능성이 높아졌다.

## Impact
- E2E 결과가 실제 런타임 동작과 정합되도록 개선되어 자동화 결과 신뢰도가 상승했다.
- 엔진 종료 단계 안정성이 향상되어 테스트 반복 실행 시 크래시 리스크가 감소했다.
- 문서와 코드가 동일 정책(JSON 직접 입력, 로컬 검증 통과 필수)을 공유해 다음 구현/검증 판단 비용이 줄었다.

## Follow-up
- `OA-00`: `move_stick/release_stick` 판정 로직 회귀 테스트 케이스를 E2E 리포트 체크 항목으로 고정.
- `OA-00`: 종료 시나리오(에디터 종료, 프로세스 강제 종료 포함)에서 서버 정리 로그/이벤트 진단 정보를 표준화.
- `IA-04`: 시나리오 포맷 사양서와 `scenario_schema.py`의 필드 제약을 동기화하고 샘플 JSON 세트를 확장.
- `IA-02`/`IA-03`: 상태 조회 기반 이동/공격/처치 루프를 attach 모드 기본 플로우로 추가 안정화.
- `OA-00`: 실제 `-TestMode` attach 상태에서 `"A무기"` 시나리오 실호출 E2E를 재검증하고 기준 리포트를 갱신.

## Outstanding Issues
- 2세션 기준 20회 연속 실행 후 3세션 상향 여부 판단 기준(성공률/평균 지연) 정량화가 필요하다.
