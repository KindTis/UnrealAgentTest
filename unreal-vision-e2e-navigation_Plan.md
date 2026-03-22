# unreal-vision-e2e-navigation Plan

## Goal
테스트 에이전트가 스크린샷을 기반으로 중간 상황을 판단하고, LLM 의사결정 결과(JSON 액션)를 반복 실행하여 목표 지점까지 도달하는 `observe -> decide -> act` 루프를 구현한다.  
1차 목표 시나리오는 다음과 같다.
- 카메라를 회전해 빨간 기둥이 있는 언덕을 탐색한다.
- 절벽을 피하고 경사로를 찾아 언덕 위로 이동한다.
- 기둥 앞 도착을 성공으로 판정한다.

## Problem / Background
현재 E2E 러너는 JSON 기반 순차 실행에 강점이 있지만, 화면 상황 변화(시야 확보 실패, 우회 필요, 목표 재탐색)에 대한 반응형 판단이 제한적이다.  
특히 본 시나리오는 단순 상태 로그만으로 판정하기 어려워, 화면 캡처 기반 시각 인지가 필수다.

## Scope
- Unreal Remote API에 스크린샷 캡처 기능 추가(해상도/품질 최적화 옵션 포함).
- 캡처 소스는 테스트 대상 프로세스(게임 창/PIE 뷰포트)로 한정하고, 디스플레이 전체 캡처를 금지.
- `vision_navigation` 계열 시나리오 스키마 추가(목표/반복/종료 조건/행동 화이트리스트).
- 에이전트가 주도하는 판단 루프(`observe -> decide -> act`) 추가.
- 1차 마일스톤 에이전트-러너 결정 연동은 파일 브리지(`observe.json`/`decide.json`) 방식으로 고정.
- 멀티 에이전트 운영 규칙 추가(에이전트별 DoD 카드, 인터페이스 스키마 버전/변경로그, OA 통합 게이트).
- LLM 출력 JSON 스키마 검증 및 안전 실행기(허용 액션만 실행).
- 반복 루프 중 아티팩트 저장(입력 이미지, LLM 응답, 실행 로그, 중간 상태).
- 성공/실패 판정 규칙 정의(시각 중심/위치 중심/하이브리드).

## Non-Scope
- 별도 CV 모델 학습/추론 모듈 개발.
- 모든 맵/모든 오브젝트에 대한 일반화된 내비게이션 완성.
- 실시간 고주파(프레임 단위) 제어 최적화.
- 멀티 Sub 동시 제어(Main->Sub*N) 2차 마일스톤 기능.

## Constraints
- 빌드/컴파일 검증은 반드시 `C:\Users\tatis\Repos\ThirdPersonAction\ThirdPersonAction.uproject` 기준.
- 인지 파이프라인은 별도 CV 모듈 없이 LLM(멀티모달) 기반으로 구성.
- 초기 단계는 느려도 허용하되, 이미지 전송량 최적화는 필수.
- 캡처 대상은 테스트 세션의 렌더 타깃(게임/PIE 뷰포트)만 허용하며, OS 레벨 전체 화면 캡처는 허용하지 않음.
- 1차 마일스톤 실행 모델은 단일 Sub/단일 테스트 세션(1:1) 기준으로 설계한다.
- 캡처 기본값은 `height=360`, `preserve_aspect_ratio=true`, `quality=60`으로 고정한다.
- 안전상 액션 실행은 화이트리스트/최대 반복/타임아웃 제약을 강제.
- 1차 단계에서는 러너가 LLM API를 직접 호출하지 않고, 테스트 에이전트(Codex/Claude)가 판단 주체가 된다.
- 각 구현 에이전트는 코딩 시작 전 DoD 카드를 제출하고, OA 승인 후 작업을 시작한다.
- 캡처 API/시나리오/결정 JSON/리포트 스키마 변경 시 `schema_version` 증가와 `CHANGELOG` 기록을 강제한다.

## Assumptions
- 테스트 맵에 빨간 기둥 오브젝트가 존재하며 시각적으로 구분 가능하다.
- 언덕 상단 도달을 위치 반경 또는 시각 조건으로 정의할 수 있다.
- 캡처된 프레임으로 목표 탐색 가능 수준의 품질을 확보할 수 있다.
- 테스트 에이전트가 일정 주기 또는 필요 시점에 화면을 모니터링/캡처하고 개입할 수 있다.

## Dependencies
- `GameTestRemoteServer` 확장(스크린샷 API, 이미지 인코딩, 응답 스키마).
- `e2e_runner.py` 확장(루프 엔진, LLM 클라이언트, 안전 실행기).
- 시나리오 스키마 확장(`scenario_schema.py`).
- 아티팩트 저장 체계(이미지/JSON/리포트 디렉터리 규약).

## Design / Approach
- 오케스트레이션 에이전트(`OA-00`)가 계획/상태/검증을 관리한다.
- 구현 분할:
  - `IA-01` Remote API: 스크린샷 캡처 엔드포인트, 해상도/품질 파라미터.
  - `IA-04` Runner/LLM: 프롬프트 구성, 응답 스키마 검증, 반복 루프.
  - `IA-05` Artifact/검증: 이미지/결정/행동 로그 저장 및 리포트 확장.
- 에이전트별 DoD 카드(필수):
  - `owner`: 에이전트 ID 및 담당 파일 경계.
  - `inputs`: 의존 인터페이스/스키마 버전.
  - `outputs`: 산출 코드/문서/아티팩트.
  - `done_when`: 단위 검증 기준(명령/테스트/기대 결과).
  - `handoff`: OA 인수인계 체크리스트.
- 인터페이스 거버넌스:
  - 대상: `capture API`, `observe.json`, `decide.json`, `report.json`, `scenario schema`.
  - 규칙: 변경 시 `schema_version` 증가 + 변경 사유/영향/마이그레이션 메모를 상대 경로 `Tools/E2ERunner/INTERFACE_CHANGELOG.md`에 기록.
- OA 통합 게이트:
  - 게이트 A: IA-01/IA-04/IA-05의 DoD 충족 여부 검증.
  - 게이트 B: 인터페이스 버전 정합성(요청/응답/리포트) 검증.
  - 게이트 C: 최종 E2E 1회 성공 + 실패 리플레이 1회에서 원인 분석 가능성 검증.
- 캡처 계약:
  - 요청 파라미터에 `session_id`를 필수로 포함한다.
  - 응답에 `captured_session_id`와 `viewport_state`를 포함해 캡처 타깃 일치 여부를 추적한다.
  - `viewport_state` 표준 필드: `is_minimized`, `is_occluded`, `is_focused`, `viewport_width`, `viewport_height`, `capture_source`.
  - `capture_source` 값은 `game_viewport|pie_viewport`로 제한한다.
- 파일 브리지 경로 규약(상대 경로):
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/observe.json`
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/decide.json`
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/bridge.lock`
- 루프 소유권:
  - 테스트 에이전트가 루프 주체이며, 필요 시 캡처 빈도를 동적으로 조정한다.
  - 러너는 안전장치(타임아웃/화이트리스트/로그/아티팩트)와 실행만 담당한다.
- 루프 단위:
  1. Observe: 저해상도 JPEG 캡처(`height=360`, `width=auto(원본 비율 유지)`, quality 60 기본).
  2. Decide: 에이전트가 이미지+컨텍스트를 바탕으로 `next_actions` JSON 결정.
  3. Act: 허용 액션(`move_stick`, `release_stick`, `tap_button`, `wait`, `camera_yaw`)만 실행.
  4. Check: 성공/실패/반복 여부 판정.
- 성공 판정 모드:
  - `position`: 시나리오에 좌표가 직접 기입된 경우 위치 중심 판정을 최우선으로 적용.
  - `visual`: 좌표가 없고 목표가 묘사형(예: `언덕 위의 빨간 기둥`)인 경우 시각 중심 판정.
  - `hybrid`: 좌표+묘사 동시 입력 시 사용하되, 성공 게이트는 `position`을 우선하고 `visual`은 보조 근거로 기록.
- 판독 불가 처리:
  - 창 최소화/뷰포트 비활성/캡처 타임아웃 등으로 판독이 불가하면 즉시 실패 처리하고 원인 코드를 로그/리포트에 남긴다.
  - 오류 코드 매핑: `viewport_minimized`, `viewport_occluded`, `capture_timeout`, `capture_unavailable`.
- 성능 최적화 전략(1차):
  - 기본 저해상도 판독.
  - 불확실도 높을 때만 일시적으로 해상도 상승(예: `height=540`, `width=auto(원본 비율 유지)`).
- 기본 타임아웃 정책(초기값):
  - 캡처 timeout 2초, 액션 timeout 3초, 루프 주기 0.7초, 최대 120회 반복, 전체 240초.

## Implementation Steps
1. `vision_navigation` 시나리오 JSON 스키마 초안 추가.
2. OA가 IA-01/IA-04/IA-05 DoD 카드 템플릿을 배포하고 승인한다.
3. 인터페이스 버전 관리 규칙(`schema_version`/`CHANGELOG`)을 정의한다.
   - `CHANGELOG` 파일은 상대 경로 `Tools/E2ERunner/INTERFACE_CHANGELOG.md`를 사용한다.
4. Remote API에 스크린샷 캡처 API 추가(`height`, `preserve_aspect_ratio`, `jpeg_quality` 옵션).
   - 캡처 소스는 테스트 대상 프로세스 뷰포트로 고정(전체 디스플레이 캡처 금지).
   - 응답에 `viewport_state` 표준 필드와 `captured_session_id`를 포함한다.
5. 캡처 API 단위 검증(응답 크기/포맷/지연 시간).
6. 에이전트 주도 판단 인터페이스 추가(파일 브리지 `observe.json`/`decide.json` 계약 + timeout/retry).
   - 상대 경로 브리지 규약(run_id/session_id 네임스페이스, lock 파일, stale 정리) 구현.
7. LLM 출력 JSON 스키마 및 실행 화이트리스트 검증기 추가.
8. `observe -> decide -> act` 루프 엔진 구현(최대 반복/전체 timeout 포함).
9. 아티팩트 저장 확장(루프별 이미지, 결정 JSON, 실행 결과).
10. 판독 불가 실패 코드/원인 로깅 구현(`viewport_minimized`, `viewport_occluded`, `capture_timeout`, `capture_unavailable`).
11. 성공/실패 판정 규칙 구현(좌표 명시=위치 우선, 묘사형 목표=시각 중심, 혼합=좌표 우선 하이브리드).
12. 샘플 시나리오 작성(빨간 기둥 언덕 도달).
13. OA 통합 게이트 실행(DoD 충족/버전 정합성 검증 후 실맵 검증 1회 성공 + 실패 리플레이 1회).

## Risks
- LLM 시각 판단 불안정으로 반복/진동 행동이 발생할 수 있다.
- 캡처 주기/LLM 응답 지연으로 테스트 시간이 길어질 수 있다.
- 화면 정보만으로 절벽 회피 판단이 어려울 수 있다.
- 성공 판정이 과도하게 느슨하면 오검출, 엄격하면 미검출 위험이 있다.

## Validation Plan
- 정적 검증:
  - 시나리오 스키마 검증 통과.
  - LLM 응답 스키마 검증 통과(허용 액션 외 거부).
- 기능 검증:
  - 캡처 API 응답 품질/크기 검증.
  - 캡처 결과에 타 애플리케이션/UI가 포함되지 않고, 테스트 대상 뷰포트 영역만 포함되는지 검증.
  - 판독 불가 상황(최소화/가림/타임아웃)에서 즉시 실패 + 원인 코드/창 상태 로그가 남는지 검증.
  - 루프 1회당 `observe/decide/act` 로그 누락 없음 확인.
  - 스키마 버전/변경로그(`schema_version`/`Tools/E2ERunner/INTERFACE_CHANGELOG.md`) 누락 없이 반영되었는지 검증.
  - 파일 브리지 상대 경로 네임스페이스(run_id/session_id) 충돌 및 stale 파일 재사용이 없는지 검증.
- 시나리오 검증:
  - 빨간 기둥 언덕 도달 시 `ok=true` + 성공 근거 이미지 저장.
  - 실패 케이스에서 실패 원인(미탐색/타임아웃/안전중단) 분류 확인.
  - 좌표형 시나리오에서 위치 중심 판정이 동작하는지 확인.
  - 묘사형 시나리오에서 시각 중심 판정이 동작하는지 확인.
  - OA 통합 게이트(A/B/C) 통과 여부를 최종 승인 조건으로 검증.

## Open Questions
- 없음(현재 기준).
