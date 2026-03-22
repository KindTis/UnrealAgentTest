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
- Applied Guide: `feature-implementation-workflow/Planning_Request_Guide.md`
- Applied Guide: `feature-implementation-workflow/Implementation_Request_Guide.md`

## Change Summary
- `OA-00` 오케스트레이션 에이전트가 E2E 기준선(장착→접근→공격→처치)과 리포트 스키마를 고정했다.
- `IA-04` 워커가 `Tools/E2ERunner/e2e_runner.py`를 구현해 `--launch` 실호출 자동 실행 및 결과 리포트 생성 흐름을 완성했다.
- `OA-00` 통합 검증에서 `python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --health-timeout 90 --poll-interval 0.2`를 실행해 `ok=true`(run_id=`e2e-20260322T035026Z-3526`)를 확인했다.
- `IA-02`가 `GameTestInputExecutor`의 축 입력 처리 결과(`input_x_handled`, `input_y_handled`)와 명령 수락 판정 불일치를 수정해, 실제 이동이 발생해도 false-negative로 실패 처리되는 문제를 해소했다.
- `IA-01`이 `FGameTestRemoteServer::Stop()` 종료 경로를 보강해 `HTTPServer` 모듈 언로드 이후 `StopAllListeners()` 호출로 발생하던 assert를 방지했다.
- `OA-00`이 CheckList/Context를 최신 구현 및 검증 상태로 동기화했다.

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

## Impact
- E2E 결과가 실제 런타임 동작과 정합되도록 개선되어 자동화 결과 신뢰도가 상승했다.
- 엔진 종료 단계 안정성이 향상되어 테스트 반복 실행 시 크래시 리스크가 감소했다.
- CheckList/Context가 최신 구현 상태와 검증 결과를 반영해 다음 작업 판단 비용이 줄었다.

## Follow-up
- `OA-00`: `move_stick/release_stick` 판정 로직에 대한 회귀 테스트 케이스를 E2E 리포트 체크 항목으로 고정.
- `OA-00`: 종료 시나리오(에디터 종료, 프로세스 강제 종료 포함)에서 서버 정리 로그/이벤트 진단 정보를 표준화.

## Outstanding Issues
- 일정/우선순위 기준은 여전히 미확정이다.
- SDK 공식 언어 및 배포 형태는 미확정이다.
- 병렬 동시 세션 상한은 미확정이다.
