# Vision Navigation LLM Decider

이 문서는 **선택 경로**인 브리지 기반 LLM decider 실행 방법을 정의합니다.

기본 경로는 AI Agent(Sub)가 `observe.json`을 직접 판독하고 `decide.json`을 작성하는 방식입니다.  
이 문서는 API 호출 기반 자동 decider가 필요할 때만 사용합니다.

수동 decider 운영 절차(실전 재현/lock 이슈 대응)는 아래 문서를 우선 참고합니다.

- `Tools/E2ERunner/VISION_DECIDER_RUNBOOK.md`

## 1) 필수 환경 변수

```powershell
$env:OPENAI_API_KEY="YOUR_API_KEY"
```

선택:

```powershell
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
```

## 2) 권장 실행 (runner + LLM decider 동시 실행)

```powershell
python Tools/E2ERunner/run_vision_with_llm_decider.py `
  --launch `
  --base-url http://127.0.0.1:31001 `
  --scenario-file .\Artifacts\E2ERunner\scenarios\vision_navigation_find_red_pillar.json `
  --model gpt-4.1-mini `
  --extra-arg=-game
```

기본 동작은 `strict LLM` 모드입니다.  
LLM 호출 실패 시 fallback 입력을 쓰지 않고 `status=failure`를 기록합니다.

## 3) 수동 분리 실행

러너:

```powershell
python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001 --scenario-file .\scenario.json --run-id e2e-xxx --session-id e2e-xxx-session-01 --extra-arg=-game
```

decider:

```powershell
python Tools/E2ERunner/bridge_decider_llm.py --bridge-dir .\Artifacts\E2ERunner\runs\e2e-xxx\bridge\e2e-xxx-session-01 --model gpt-4.1-mini
```

## 4) 출력 파일

- observe: `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/observe.json`
- decide: `Artifacts/E2ERunner/runs/<run_id>/bridge/<session_id>/decide.json`
- report: `Artifacts/E2ERunner/runs/<run_id>/report.json`

## 5) 정책 정규화(`decision_policy`)

하드코딩 대신 시나리오의 `decision_policy`를 읽어 모델 출력을 정규화합니다.

- `mode=strict`이면 LLM 출력이 달라도 정책 액션으로 강제합니다.
- `mode=advisory`이면 LLM 출력을 우선하고 guardrail만 적용합니다.
- `target_missing.strategy=scan_yaw`를 쓰면 탐색 회전을 고정할 수 있습니다.
- `target_found.strategy=success_after_wait`를 쓰면 성공 직전 대기 시간을 고정할 수 있습니다.

예시(빨간 기둥):

- 미탐지: `scan_yaw`, `scan_step_degrees=45`
- 탐지: `success_after_wait`, `success_wait_seconds=1.0`
