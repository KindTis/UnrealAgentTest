# Vision Navigation Manual Decider Runbook

이 문서는 **AI Agent가 decider를 직접 수행**할 때, 마지막 성공 사례 기준으로 재현 가능한 운영 절차를 정의합니다.

목표:

- Runner만 실행하고 멈추는 실패 방지
- `observe.json` 실시간 판독 누락 방지
- 카메라 회전만 반복하는 실패 방지
- red-pixel/OpenCV 임의 로직 추가 방지
- Windows 파일 교체 타이밍(`bridge.lock`, `observe.json`, `decide.json`) 이슈 방지

---

## 1. 실행 준비

- 작업 경로: `C:\Users\tatis\Repos\UnrealAgentTest`
- UProject: `C:\Users\tatis\Repos\ThirdPersonAction\ThirdPersonAction.uproject`
- 브리지 경로 패턴:
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/observe.json`
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/decide.json`
  - `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/bridge.lock`

권장 시나리오 설정(경량 판독):

- `intent=vision_navigation`
- `success_criteria.success_mode=visual`
- `capture.height=240~360`
- `capture.preserve_aspect_ratio=true`
- `capture.jpeg_quality=45~60`
- `decision_bridge.decide_wait_timeout_seconds >= 60`

---

## 2. Runner 실행

PowerShell 예시:

```powershell
python Tools/E2ERunner/e2e_runner.py `
  --launch `
  --base-url http://127.0.0.1:31001 `
  --scenario-file .\Artifacts\E2ERunner\scenarios\vision_navigation_find_red_pillar_light.json `
  --run-id e2e-light-redpillar `
  --session-id e2e-light-redpillar-session-01 `
  --uproject C:/Users/tatis/Repos/ThirdPersonAction/ThirdPersonAction.uproject `
  --extra-arg=-game `
  --no-keep-process-on-failure
```

중요:

- Runner 실행 후 **반드시 decider 루프를 즉시 시작**해야 합니다.
- `run_id`, `session_id`는 decide JSON 검증 키이므로 중간에 바꾸면 안 됩니다.

---

## 3. Decider 루프(핵심)

### 루프 트리거

- `bridge.lock.status == waiting_for_decision`일 때만 현재 iteration에 대한 결정을 작성합니다.
- `bridge.lock`은 **힌트**입니다. 실제 의사결정 입력은 `observe.json`입니다.

### 매 iteration 절차

1. `observe.json` 읽기
2. `observe.iteration` 확인
3. `observation.capture.image_base64`를 이미지로 복원
4. 이미지를 실제 판독해 액션 결정
5. `decide.json` 작성(원자적 저장)

### 종료 조건

- `bridge.lock.status in {completed, failed}` 또는
- `report.json`에 `ended_at_utc`가 채워짐

---

## 4. 파일 잠금/교체 이슈 대응(Windows)

`bridge.lock`, `observe.json`은 러너가 갱신 시점에 교체할 수 있습니다.
아래 원칙을 지키면 충돌을 크게 줄일 수 있습니다.

읽기 원칙:

- 파일을 오래 열어두지 말고, 매 폴링마다 짧게 열고 닫습니다.
- `JSONDecodeError`, `OSError`, `PermissionError`가 나면 실패 처리하지 말고 짧게 대기 후 재시도합니다.
- `bridge.lock` 읽기 실패 시 즉시 중단하지 말고 `observe.json` 기준으로 계속 진행합니다.

쓰기 원칙(`decide.json`):

- 항상 `tmp` 파일에 먼저 쓰고 `replace`로 교체합니다.
- 한 iteration에 decide는 1회만 기록합니다.
- `run_id/session_id/iteration`이 observe와 다르면 무효로 간주됩니다.

예시(Python):

```python
tmp = decide_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(decide_path)
```

---

## 5. 의사결정 정책(최소 규칙)

- 목표 물체(예: 빨간 기둥)가 중앙 부근에서 명확히 보이면:
  - `status="success"`, `success=true`, `actions=[]`
- 목표가 보이나 중앙이 아니면:
  - `camera_yaw` 소각도 + `wait`
- 목표가 안 보이면:
  - `camera_yaw` 스윕(±60~120) + `wait`
- 여러 회차 미탐지면:
  - `move_stick(left_stick)` 전진 + `release_stick` 후 재탐색

금지:

- red pixel 임계치 검출(OpenCV 포함) 추가 금지
- 코드 수정으로 판독 로직 추가 금지
- 이미지 판독 없이 `camera_yaw`만 반복 금지

---

## 6. 실패 패턴과 차단 규칙

### 패턴 A: Runner만 실행하고 decide 미작성

- 증상: `decision_timeout` 또는 `vision_navigation=false`
- 차단: Runner 실행 직후 decider 루프 시작을 필수 단계로 고정

### 패턴 B: observe를 안 보고 카메라만 회전

- 증상: 반복 회전 후 `max_iterations_reached`
- 차단: 각 iteration에서 image 복원 여부를 체크리스트에 강제

### 패턴 C: red pixel 로직 추가

- 증상: 요구와 다른 코드 변경, 불안정한 판정
- 차단: "판독은 이미지 기반 추론만" 규칙을 문서/프롬프트에 명시

---

## 7. 완료 검증

최종 확인 파일:

- `Artifacts/E2ERunner/runs/<run_id>/report.json`

확인 항목:

- `ok == true`
- `checks.vision_navigation == true`
- `checks.scenario_flow == true`
- `vision_navigation.final_decision.status == "success"`
- `vision_navigation.iterations`가 1 이상

---

## 8. 운영 체크리스트

- [ ] 시나리오 파일 준비(visual/hybrid/loop/capture/decision_bridge 확인)
- [ ] Runner 실행(`--run-id`, `--session-id` 명시)
- [ ] 브리지 경로 확인(observe/decide/lock)
- [ ] `waiting_for_decision`마다 observe 판독 후 decide 기록
- [ ] decide는 원자적 저장(tmp->replace)
- [ ] lock/observe 읽기 실패 시 재시도(즉시 실패 금지)
- [ ] `report.json` 종료 상태 확인 후 결과 보고

