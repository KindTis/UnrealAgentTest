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
- Applied Guide: `feature-implementation-workflow/Planning_Request_Guide.md`
- Applied Guide: `feature-implementation-workflow/Implementation_Request_Guide.md`

## Change Summary
- `OA-00` 오케스트레이션 에이전트가 E2E 기준선(장착→접근→공격→처치)과 리포트 스키마를 고정했다.
- `IA-04` 워커가 `Tools/E2ERunner/e2e_runner.py`를 구현해 `--launch` 실호출 자동 실행 및 결과 리포트 생성 흐름을 완성했다.
- `OA-00` 통합 검증에서 `python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --health-timeout 90 --poll-interval 0.2`를 실행해 `ok=true`(run_id=`e2e-20260322T035026Z-3526`)를 확인했다.
- `IA-02`가 `GameTestInputExecutor`의 축 입력 처리 결과(`input_x_handled`, `input_y_handled`)와 명령 수락 판정 불일치를 수정해, 실제 이동이 발생해도 false-negative로 실패 처리되는 문제를 해소했다.
- `IA-01`이 `FGameTestRemoteServer::Stop()` 종료 경로를 보강해 `HTTPServer` 모듈 언로드 이후 `StopAllListeners()` 호출로 발생하던 assert를 방지했다.
- `OA-00`이 CheckList/Context를 최신 구현 및 검증 상태로 동기화했다.
- 사용자 결정에 따라 1차 마일스톤 기준을 attach 우선 실행, 자연어→시나리오 JSON 변환, 상태 기반 이동/공격/처치, 종료 정책 옵션 포함으로 확정했다.
- SDK 정책을 "Python 공식 + 저장소 내 포함형(비설치 기본) + Main/Sub 분리 구조"로 확정하고 Plan/CheckList에 반영했다.
- 사용자 결정에 따라 병렬 실행 정책을 `max_concurrent_sessions=2`, FIFO 대기열, `queue_wait_timeout=120s`, `session_timeout=180s`, 연결/헬스체크 실패 1회 재시도로 확정했다.
- 리소스 가드는 항목만 유지하고 임계값은 `0`으로 고정해 1차 마일스톤에서는 무시하도록 확정했다.
- 초기 시나리오 최소 범위를 `"A무기로 정면 몬스터를 무찌르세요"` 단일 기준선으로 확정했다.

## Files Touched
- `UnrealAgentTest/Source/UnrealAgentTest/Public/GameTestInputExecutor.h` (신규)
- `UnrealAgentTest/Source/UnrealAgentTest/Private/GameTestInputExecutor.cpp` (신규/갱신)
- `UnrealAgentTest/Source/UnrealAgentTest/Private/GameTestCommandService.cpp` (갱신)
- `UnrealAgentTest/Source/UnrealAgentTest/Private/GameTestRemoteServer.cpp` (갱신)
- `UnrealAgentTest/Source/UnrealAgentTest/UnrealAgentTest.Build.cs` (갱신)
- `Tools/UnrealTestClient/unreal_test_client.py` (갱신)
- `Tools/SmokeRunner/smoke_runner.py` (신규)
- `Tools/E2ERunner/e2e_runner.py` (신규/갱신)
- `Tools/E2ERunner/report_schema.json` (신규)
- `unreal-agent-test-remote-api_Contract.md` (신규)
- `unreal-agent-test-remote-api_Context.md` (갱신)
- `unreal-agent-test-remote-api_CheckList.md` (갱신)

## Reasoning
- 실제 게임 내 이동이 확인되는데 E2E 결과가 실패로 기록되는 문제는 신뢰도 저하가 크므로, 입력 처리 실패와 명령 수락 여부를 분리해 판정 규칙을 재정의했다.
- 종료 assert는 기능 성공 여부와 무관하게 런타임 안정성을 직접 해치므로 즉시 우선순위를 높여 패치했다.
- E2E 실호출 통과를 기준선으로 고정해 이후 회귀에서 “실제 런타임 동작” 기준으로 비교 가능하게 했다.
- 1차 마일스톤의 성패를 런치 편의가 아니라 실제 운영 시나리오(attach + 자연어 지시 실행)로 정의해야 사용자 목적과 검증 기준이 일치한다.
- SDK는 공통 통신/세션 계층으로 고정하고 오케스트레이션/시나리오 전술을 분리해야 계약 변경 시 수정 범위를 최소화할 수 있다.
- 1차에서는 성능 최적화보다 재현 가능한 기준선 확보가 우선이므로 리소스 가드는 비활성(0)으로 두고 세션 상한/타임아웃으로 안정성을 관리한다.

## Alternatives Considered
- 입력 처리 미핸들(axis not handled)을 즉시 명령 실패로 유지:
  - 장점: 엄격한 검증.
  - 단점: 프로젝트 입력 바인딩 차이에서 false-negative가 빈번해 배제.
- 종료 시점에 항상 `FHttpServerModule::Get()` 강제 호출:
  - 장점: 코드 단순.
  - 단점: 모듈 언로드 순서에 따라 assert 발생 가능성이 있어 배제.

## Trade-offs
- 축 입력 best-effort 허용으로 명령 성공 판정은 안정화됐지만, 완전한 입력 보장은 프로젝트별 바인딩 구성에 여전히 의존한다.
- 종료 안정성 패치는 assert를 제거하지만, 모듈이 이미 언로드된 경우 리스너 정리 경로는 스킵된다(Verbose 로그로 추적).
- SDK를 저장소 포함형으로 유지하면 즉시 사용성은 높지만, 외부 재사용 시 패키징 표준화가 후속 과제로 남는다.
- 리소스 가드 비활성으로 인해 고부하 상황에서 성능 저하 가능성은 남지만, 1차 기준선 단계에서는 장애 원인 축소 효과가 더 크다.

## Impact
- E2E 결과가 실제 런타임 동작과 정합되도록 개선되어 자동화 결과 신뢰도가 상승했다.
- 엔진 종료 단계 안정성이 향상되어 테스트 반복 실행 시 크래시 리스크가 감소했다.
- CheckList/Context가 최신 구현 상태와 검증 결과를 반영해 다음 작업 판단 비용이 줄었다.
- 1차 마일스톤 완료 기준이 명확해져 attach 경로와 시나리오 변환 구현의 우선순위가 고정됐다.
- SDK 책임 경계가 명확해져 Main/Sub 구현 시 중복 로직 유입 위험이 감소했다.
- 병렬 정책/시나리오 기준이 수치화되어 이후 구현/검증 결과의 합격 여부 판단이 명확해졌다.

## Follow-up
- `OA-00`: `move_stick/release_stick` 판정 로직에 대한 회귀 테스트 케이스를 E2E 리포트 체크 항목으로 고정.
- `OA-00`: 종료 시나리오(에디터 종료, 프로세스 강제 종료 포함)에서 서버 정리 로그/이벤트 진단 정보를 표준화.
- `IA-04`/`IA-05`: 자연어 입력을 시나리오 JSON으로 변환하는 인터페이스와 스키마 검증기를 구현.
- `IA-02`/`IA-03`: 상태 조회 기반 이동/공격/처치 루프를 attach 모드 기본 플로우로 통합.
- `IA-05`: 병렬 실행기 설정값(`2세션`, 대기열 120초, 세션 180초, 리소스 가드 0)을 코드/CLI 기본값으로 반영.

## Outstanding Issues
- 2세션 기준 20회 연속 실행 후 3세션 상향 여부 판단 기준(성공률/평균 지연) 정량화가 필요하다.
