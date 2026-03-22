# Vision Navigation LLM Decider

이 문서는 **선택 경로**인 브리지 기반 LLM decider 실행 방법을 정의합니다.

기본 경로는 AI Agent(Sub)가 `observe.json`을 직접 판독하고 `decide.json`을 작성하는 방식입니다.  
이 문서는 API 호출 기반 자동 decider가 필요할 때만 사용합니다.

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
