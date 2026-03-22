# unreal-vision-e2e-navigation Context

## Date / Session
- Date: 2026-03-22 (KST)
- Session 1: Planning Request 처리
- Applied Guide: `feature-implementation-workflow/Planning_Request_Guide.md`

## Change Summary
- 신규 피처 `unreal-vision-e2e-navigation`를 생성했다.
- “LLM + 스크린샷 기반 observe -> decide -> act 루프”를 1차 구현 목표로 확정했다.
- 별도 CV 모듈 없이 멀티모달 LLM만 인지 엔진으로 사용하는 방향을 계획에 반영했다.
- 해상도 최적화(`height=360`, `width=auto(원본 비율 유지)`, JPEG quality 60 기본) 및 불확실 시 고해상도 재판독 전략을 반영했다.
- 캡처 소스를 테스트 대상 프로세스(게임/PIE 뷰포트)로 제한하고, 디스플레이 전체 캡처를 금지하는 정책을 확정했다.
- 1차 마일스톤 실행 모델을 단일 Sub/단일 테스트 세션(1:1) 기준으로 확정했다.
- 1차 마일스톤 에이전트-러너 결정 전달 채널을 파일 브리지(`observe.json`/`decide.json`)로 확정했다.
- 파일 브리지 경로를 상대 경로 규약(`Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/...`)으로 확정했다.
- 인터페이스 변경 기록 파일을 상대 경로 `Tools/E2ERunner/INTERFACE_CHANGELOG.md`로 확정했다.
- 멀티 에이전트 리스크 완화를 위해 에이전트별 DoD 카드 강제, 인터페이스 스키마 버전/변경로그 강제, OA 통합 게이트 적용을 확정했다.
- 성공 판정 정책을 다음으로 확정했다:
  - 좌표 직접 기입 시 `위치 중심(최우선)`
  - 묘사형 목표(예: `언덕 위의 빨간 기둥`) 시 `시각 중심`
  - 혼합 정보 제공 시 `하이브리드(좌표 우선, 시각 보조 근거)`
- 창 최소화/가림/캡처 타임아웃 등 판독 불가 상황은 원인 로깅과 함께 테스트 실패로 처리하기로 확정했다.
- 캡처 기본값(`height=360`, `preserve_aspect_ratio=true`, `quality=60`)을 전역 기본값으로 확정했다.
- 테스트 에이전트가 루프 주체가 되어, 필요 시 지속 모니터링/캡처/입력 개입을 수행하는 방향을 확정했다.

## Files Touched
- `unreal-vision-e2e-navigation_Plan.md`
- `unreal-vision-e2e-navigation_Context.md`
- `unreal-vision-e2e-navigation_CheckList.md`

## Reasoning
- 현재 순차형 시나리오 엔진은 반응형 판단이 제한되어, 언덕 탐색/우회 같은 상황 대응이 어렵다.
- 사용자가 요구한 판정 방식은 화면 기반 인지가 핵심이므로 캡처+LLM 루프가 직접적인 해법이다.
- 캡처 범위를 테스트 대상 프로세스로 제한해야 테스트 신뢰성과 보안/프라이버시 측면의 노이즈를 줄일 수 있다.
- 1차는 느려도 허용되므로, 안정성(스키마 검증/화이트리스트/아티팩트 추적)을 우선한다.
- 목표 표현 방식에 따라 판정 전략을 분기해야 오검출/미검출을 줄일 수 있다.
- 에이전트 주도 루프는 실시간 상황 대응(재탐색/개입) 측면에서 매크로형 러너보다 유리하다.
- 멀티 에이전트 병렬 구현에서는 인터페이스 불일치/통합 지연 리스크가 커서, DoD+버전관리+게이트가 필수다.

## Alternatives Considered
- 별도 CV 모듈(색/형상 탐지) + 규칙 기반 제어:
  - 장점: 호출 비용/지연 감소 가능.
  - 단점: 요구사항(LLM 중심)과 방향 불일치, 확장성 저하.
- 상태값 중심 비시각 루프:
  - 장점: 구현 단순.
  - 단점: 본 시나리오(빨간 기둥 탐색)의 핵심 요구를 충족하지 못함.

## Trade-offs
- LLM 기반 인지는 구현 유연성이 높지만 지연/비용이 커진다.
- 저해상도 캡처는 속도에 유리하지만 판독 신뢰도가 낮아질 수 있다.
- 따라서 기본 저해상도 + 조건부 고해상도 재판독으로 균형을 잡는다.

## Impact
- E2E 테스트가 단순 매크로 실행에서 상황 인지 기반 루프로 확장된다.
- 향후 “도망 타깃 추적”, “시야 기반 탐색”, “장애물 우회” 같은 시나리오로 확장할 수 있는 기반이 생긴다.

## Follow-up
- 주요 결정사항 확정 완료, 구현 단계로 전환.
- Remote API 캡처 엔드포인트부터 우선 개발 후 Runner 루프를 연결.
- 샘플 시나리오와 검증 리포트 스키마를 동시에 업데이트.
- 파일 브리지(`observe.json`/`decide.json`) 규약(타임아웃, 스키마, 재시도)부터 우선 구현.

## Outstanding Issues
- Play 전 자동 진입 문제와의 결합 범위(이번 피처 포함 여부) 미확정.
