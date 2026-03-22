# unreal-vision-e2e-navigation CheckList

## Todo
- [ ] `vision_navigation` 시나리오 스키마 정의 및 검증기 확장.
- [ ] Remote API 스크린샷 캡처 엔드포인트 구현.
- [ ] 캡처 소스 제한 구현(테스트 대상 프로세스 뷰포트 전용, 전체 디스플레이 캡처 금지).
- [ ] 캡처 옵션(해상도/품질) 및 기본값 정책 구현.
- [ ] 캡처 API `session_id` 필수/`captured_session_id` 응답 필드 구현.
- [ ] LLM 호출 어댑터 및 응답 JSON 스키마 검증기 구현.
- [ ] 파일 브리지(`observe.json`/`decide.json`) 판단 연동 구현(timeout/retry 포함).
- [ ] 파일 브리지 상대 경로 규약 구현(run_id/session_id 네임스페이스 + lock + stale 정리).
- [ ] IA-01/IA-04/IA-05 에이전트별 DoD 카드 작성 및 OA 승인 절차 적용.
- [ ] 인터페이스 버전 관리 적용(`schema_version` 증가 규칙 + `Tools/E2ERunner/INTERFACE_CHANGELOG.md` 기록).
- [ ] `observe -> decide -> act` 반복 루프 엔진 구현.
- [ ] 액션 화이트리스트/안전 가드(최대 반복/타임아웃/중단 규칙) 구현.
- [ ] 루프 아티팩트 저장(이미지/판단 JSON/실행 로그) 구현.
- [ ] 판독 불가 실패 처리 구현(최소화/가림/캡처 타임아웃) 및 원인 코드 로깅.
- [ ] 빨간 기둥 언덕 도달 샘플 시나리오 작성.
- [ ] 성공/실패 판정 규칙 구현 및 리포트 반영(좌표 우선 하이브리드 포함).
- [ ] OA 통합 게이트 실행(DoD 충족/버전 정합성/E2E 성공·실패 검증) 및 승인 기록.
- [ ] 실맵 검증(성공/실패 각 1회) 수행.

## In Progress
- [ ] 없음.

## Blocked
- [ ] 없음.

## Done
- [x] Planning Request 분류 및 가이드 적용.
- [x] FeatureName 확정: `unreal-vision-e2e-navigation`.
- [x] Plan/Context/CheckList 초기 문서 생성.
- [x] 성공 판정 분기 정책 확정(좌표형=위치 중심, 묘사형=시각 중심, 혼합=하이브리드).
- [x] 에이전트 주도 모니터링/캡처/입력 개입 방향 확정.
- [x] 캡처 범위 정책 확정(타겟 프로세스 뷰포트 한정, 전체 화면 캡처 금지).
- [x] 1차 마일스톤 결정 JSON 전달 방식 확정(파일 브리지 `observe.json`/`decide.json`).
- [x] 파일 브리지 상대 경로 규약 확정(`Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/...`).
- [x] 성공 판정 우선순위 확정(좌표 존재 시 좌표 우선).
- [x] 판독 불가 처리 정책 확정(원인 로깅 + 즉시 실패).
- [x] 멀티 에이전트 리스크 대응 정책 확정(DoD 카드 강제 + 스키마 버전/변경로그 강제 + OA 통합 게이트).
- [x] 기본 타임아웃 초안 확정(캡처 2s, 액션 3s, 루프 0.7s, 최대 120회, 전체 240s).
- [x] 캡처 기본값 확정(`height=360`, `preserve_aspect_ratio=true`, `quality=60`).
- [x] 인터페이스 변경 로그 경로 확정(`Tools/E2ERunner/INTERFACE_CHANGELOG.md`).

## Validation Status
- Pending: 구현 전 단계(문서 계획 수립 완료).

## Deferred / Out of Scope
- [ ] 별도 CV 모듈 학습/추론 파이프라인 개발.
- [ ] 다중 Sub 동시 제어(Main->Sub*N) 고도화.
- [ ] 전 맵 범용 자동 탐색 완성.
