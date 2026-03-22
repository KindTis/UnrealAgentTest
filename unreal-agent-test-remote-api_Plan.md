# unreal-agent-test-remote-api Plan

## Goal
`UnrealAgentTest_Spec.md`를 기준으로 Unreal 프로젝트 플러그인 기반의 Test Remote API를 단계적으로 구현하고, 오케스트레이션 에이전트가 다수 구현 에이전트를 지휘해 병렬 개발/검증이 가능한 실행 체계를 확립한다.
1차 마일스톤에서는 **실행 중인 게임/에디터 attach 기반**으로 AI Agent가 작성한 시나리오 JSON을 검증/실행하고, 상태 기반 이동/공격/처치 판정 및 종료 정책 옵션까지 포함한 E2E 자동화를 운영 가능한 기준선으로 확정한다.

## Problem / Background
기존 입력 주입/OCR 중심 자동화는 게임 의미 단위 판정과 실패 원인 추적이 어렵다.  
이번 구현은 Unreal 런타임을 세션 기반 테스트 서버로 확장해, 고수준 명령 전송과 authoritative state/event 기반 판정을 가능하게 해야 한다.

## Scope
- 프로젝트 플러그인(C++) 내 Remote API 핵심 구성요소 구현: 서버, 세션 관리자, 명령 서비스, 상태 조회 서비스, 이벤트 기록/송신.
- HTTP + WebSocket 기반 통신 계층 구성 및 최소 필수 엔드포인트 제공.
- interaction recipe registry 및 target resolver의 초기 버전 구현.
- Sub Agent 연동 SDK(외부 클라이언트)와 이벤트 루프/재시도 정책 구현.
- Main Agent 오케스트레이션 로직(병렬 세션 분배, 재시도, 결과 수집, 리포트 생성) 구현.
- 병렬 실행을 위한 포트/로그/아티팩트 분리 규칙 수립 및 최소 런처 구현.
- 실행 중 프로세스 attach 모드(`--launch` 비필수) 기반의 테스트 실행 경로 구현.
- AI Agent가 작성한 테스트 시나리오 JSON을 검증하고 실행하는 경로 구현.
- 시나리오 옵션에 종료 정책(`keep_running`, `close_game`, `close_editor`)을 포함하고 실행 종료 시 정책을 적용.

## Non-Scope
- Unreal 엔진 소스 직접 수정 또는 엔진 포크 기반 구현.
- Shipping 빌드 상시 활성화 원격 제어 시스템.
- OCR/픽셀 기반 판정을 핵심 검증 근거로 사용하는 구조.
- Public network 바인딩.
- 초기 단계에서 모든 UI 화면에 대한 recipe 100% 커버리지 확보.
- 1차 마일스톤에서 SDK를 외부 패키지 저장소(PyPI 등)로 배포하는 작업.

## Constraints
- 빌드/컴파일 검증 기준 프로젝트는 `C:\Users\tatis\Repos\ThirdPersonAction\ThirdPersonAction.uproject`를 사용해야 한다.
- 테스트 서버는 기본 `localhost` 바인딩만 허용한다.
- Dev/Test 환경 중심으로 동작하며 Shipping 기본 비활성 정책을 따라야 한다.
- 현재 코드베이스는 플러그인 모듈 골격만 존재하므로, 아키텍처 계층을 신규 설계/구현해야 한다.
- 1차 마일스톤 기본 실행 모드는 **게임/에디터 기동 후 attach**로 고정한다.
- 병렬 실행 기본 상한은 `max_concurrent_sessions=2`로 고정한다.
- 리소스 가드 임계값은 1차 마일스톤에서 비활성(`cpu_percent_limit=0`, `memory_available_mb_limit=0`)로 고정한다.

## Assumptions
- `ThirdPersonAction` 프로젝트에서 플러그인 연동 및 빌드 수행이 가능하다.
- 테스트 시나리오/recipe 정의 파일(JSON 또는 문서) 저장 경로를 프로젝트 내에서 확보할 수 있다.
- 오케스트레이션 계층은 Unreal 외부 프로세스(예: Python 기반)로 동작 가능하다.
- 병렬 실행 시 머신 자원(CPU/RAM)과 포트 범위를 테스트 환경에서 확보할 수 있다.
- SDK 공식 구현 언어는 1차 마일스톤에서 Python으로 고정한다.
- SDK는 1차 마일스톤에서 저장소 내 포함형으로 사용하며 별도 설치 절차 없이 Runner에서 직접 import한다.
- 초기 시나리오 최소 범위는 `"A무기로 정면 몬스터를 무찌르세요"` 단일 시나리오를 기준선으로 사용한다.

## Dependencies
- Unreal 모듈/플러그인 의존성: `Json`, `JsonUtilities`, `HttpServer`, `WebSockets`, `Sockets`, `Networking` 계열.
- 테스트 대상 프로젝트 리소스: 테스트 맵, 스폰 지점, 더미 크리처, 시나리오 데이터.
- 외부 실행 의존성: Sub Agent SDK 런타임, 오케스트레이션 스크립트 실행 환경.
- 공통 계약 문서: API 스키마, 이벤트 스키마, 에러 코드, trace_id 규칙.
- AI Agent가 작성한 시나리오 JSON 검증을 위한 시나리오 포맷 스키마.

## Design / Approach
오케스트레이션 에이전트가 중앙에서 계획/상태를 관리하고, 구현 에이전트들을 기능 경계별로 생성하여 병렬 수행한다.

| Agent | 역할 | 소유 범위 | 주요 산출물 |
|---|---|---|---|
| `OA-00` Orchestration Agent | 전체 일정/의존성/병렬 실행 지휘 | Plan/CheckList 관리, 통합 의사결정, PR 통합 | 통합 작업 보드, 병합 순서, 최종 검증 리포트 |
| `IA-01` Runtime Server Agent | 서버/세션 기반 골격 구현 | `GameTestRemoteServer`, `GameTestSessionManager`, 부트스트랩 | `/health`, `/capabilities`, `/session/start`, `/session/stop` |
| `IA-02` Command & Recipe Agent | 명령 처리/입력 계층 구현 | `GameTestCommandService`, recipe registry, input atom 처리 | `attack`, `tap_button`, `move_stick`, `execute_recipe` 초기 구현 |
| `IA-03` Query & Event Agent | 상태 조회/이벤트 계층 구현 | `GameTestQueryService`, `GameTestEventRecorder`, trace_id 매핑 | 상태 조회 API, 이벤트 스트림, 핵심 이벤트 모델 |
| `IA-04` SDK Agent | Sub Agent SDK 및 이벤트 루프 구현 | `UnrealTestClient`, wait/retry/timeout, 상태 해석기 | SDK 패키지, 샘플 시나리오 러너 |
| `IA-05` Parallel Runner Agent | 병렬 런처/아티팩트/리포트 구현 | 포트 allocator, 프로세스 launcher, 결과 수집기 | 다중 세션 실행 도구, run/session 단위 아티팩트 구조 |

작업 분배 원칙:
- `OA-00`이 의존성 그래프를 관리하고 병렬 가능한 에이전트 작업만 동시 실행한다.
- 코드 충돌 방지를 위해 에이전트별 소유 디렉터리를 분리한다.
- 각 에이전트는 완료 조건(Definition of Done)과 검증 명령을 함께 제출해야 한다.
- 통합 전 `OA-00`이 계약(API/이벤트 스키마) 호환성을 우선 검증한다.

병렬 세션 운영 정책(확정):
- `max_concurrent_sessions=2`
- 초과 요청은 FIFO 대기열로 처리
- `queue_wait_timeout_seconds=120` 초과 시 `queue_timeout` 실패
- `session_timeout_seconds=180`
- 연결/헬스체크 실패에 한해 1회 재시도
- 리소스 가드 임계값은 `0`으로 설정해 무시

초기 시나리오 정책(확정):
- 필수 시나리오: `"A무기로 정면 몬스터를 무찌르세요"`
- 대상 선택: 플레이어 전방 ±45도 내 생존 몬스터 중 최단거리 우선
- 성공 판정: `actor_died` 우선, 보조로 `target.health <= 0`
- 실패 판정: 총 실행시간 90초 초과, 대상 상실 10초 지속, `input_execution_failed` 연속 3회
- 종료 옵션 기본값: `keep_running` (`close_game`, `close_editor` 선택 가능)

시나리오 입력 정책(확정):
- 자연어 문장을 런타임에서 직접 실행/컴파일하지 않고, AI Agent가 포맷 사양에 맞춰 작성한 시나리오 JSON만 실행 입력으로 사용한다.
- 입력 시나리오는 JSON Schema + 로컬 `validate()`를 모두 통과해야 실행 가능하다.

SDK 계층 정책(확정):
- SDK는 Main/Sub 공통 기반 계층(`session`, `command`, `state`, `event`, `retry/timeout`)만 포함한다.
- Main 오케스트레이션 로직(분배/병렬/집계)과 Sub 시나리오 로직(전술 실행)은 SDK 바깥 Runner 계층에 둔다.
- 1차 마일스톤에서는 Python 모듈 형태(저장소 내 포함형)로 운영하고 설치형 배포는 후속 단계에서 판단한다.

## Implementation Steps
1. `OA-00`이 공통 계약 초안을 확정한다: API 라우트, 명령/상태/이벤트 JSON 스키마, 에러 코드, trace_id 규칙.
2. `OA-00`이 구현 에이전트(`IA-01`~`IA-05`)를 생성하고 소유 파일/모듈 경계를 할당한다.
3. `IA-01`이 Phase 1(최소 세션 서버)을 구현하고 `OA-00`에 인터페이스 스냅샷을 제출한다.
4. `IA-02`가 Phase 2 명령 계층과 recipe 실행 파이프라인 초기 버전을 구현한다.
5. `IA-03`이 Phase 2 조회 계층과 Phase 3 이벤트 스트림을 구현하고 trace_id 연결을 보장한다.
6. `OA-00`이 `IA-01`~`IA-03` 결과를 통합해 Unreal 플러그인 E2E 최소 시나리오를 고정한다.
7. `IA-04`가 SDK, 이벤트 루프, 룰 기반 상태 해석기 및 재시도 정책을 구현한다.
8. `IA-05`가 병렬 런처, 포트 할당, 로그/아티팩트 분리, 최종 리포트 생성기를 구현한다.
9. `OA-00`이 통합 회귀를 수행하고 실패 케이스(연결 실패, 타임아웃, 세션 비정상 종료) 복구 정책을 검증한다.
10. `OA-00`이 빌드/컴파일 및 시나리오 검증 결과를 정리해 운영 가능한 구현 기준선을 확정한다.
11. `IA-04`/`IA-05`가 attach 실행 모드 기준 시나리오 JSON 입력/검증 인터페이스를 구현한다.
12. `IA-02`/`IA-03`가 상태 조회를 기반으로 이동/공격/처치 판정 루프를 안정화한다.
13. `OA-00`이 종료 정책 옵션(`keep_running`, `close_game`, `close_editor`)을 시나리오 스키마와 실행기에 통합한다.

## Risks
- Unreal HTTP/WebSocket 모듈 호환성 문제로 초기 서버 부트스트랩이 지연될 수 있다. 대응: Phase 1에서 최소 경로로 먼저 연결성 검증.
- 명령 계층과 조회/이벤트 계층 간 스키마 불일치가 발생할 수 있다. 대응: `OA-00`이 계약 스키마를 선확정하고 CI 검증 추가.
- 병렬 실행 시 포트 충돌/리소스 고갈로 테스트 안정성이 저하될 수 있다. 대응: allocator와 세션 자원 상한을 강제.
- UI recipe 데이터 품질 부족으로 자동화 실패율이 높아질 수 있다. 대응: recipe 버전/해시 관리와 단계별 상태 전이 검증.
- 외부 SDK와 Unreal 플러그인 릴리즈 사이클이 어긋날 수 있다. 대응: capability discovery 기반 하위 호환 레이어 도입.

## Validation Plan
- 단위 검증:
  - 서버 라우트 헬스체크 및 세션 lifecycle 호출 검증.
  - 명령 수락(`accepted`)과 이벤트 결과 분리 검증.
  - query API가 authoritative state를 반환하는지 검증.
- 통합 검증:
  - 단일 세션 시나리오(장착→접근→공격→처치) E2E 실행.
  - trace_id 기준 명령-이벤트 상관관계 검증.
  - recipe step별 성공/실패 이벤트 검증.
  - attach 모드에서 AI Agent 작성 시나리오 JSON 재실행 시 결과 일관성 검증.
  - 종료 정책 옵션별 후처리 검증(`keep_running`, `close_game`, `close_editor`).
- 병렬 검증:
  - 2개 Sub Agent 동시 세션 실행, 포트/로그/아티팩트 분리 확인.
  - 타임아웃/재시도/세션 강제 종료 복구 시나리오 확인.
  - 대기열 타임아웃(`120초`) 및 세션 타임아웃(`180초`) 동작 검증.
- 빌드 검증:
  - `C:\Users\tatis\Repos\ThirdPersonAction\ThirdPersonAction.uproject` 기준 빌드 성공 확인.

## Open Questions
- 2세션 운영에서 20회 연속 성공 후 3세션 상향 여부 판단 기준(성공률/평균 소요시간) 정량화가 필요하다.
