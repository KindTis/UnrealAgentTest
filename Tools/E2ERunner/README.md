# E2ERunner

`e2e_runner.py`는 `equip -> approach -> attack -> kill` 흐름을 실행하고 결과 JSON을 저장합니다.

## 실행 방법

### launch 모드
Unreal을 함께 띄워서 E2E를 실행합니다.

```powershell
python Tools/E2ERunner/e2e_runner.py --launch --base-url http://127.0.0.1:31001
```

### attach 모드
이미 실행 중인 `-TestMode` 서버에 붙어서 E2E를 실행합니다.

```powershell
python Tools/E2ERunner/e2e_runner.py --base-url http://127.0.0.1:31001
```

## 성공 기준

- `result.ok`가 `true`
- `success.success_condition`이 `target_state.alive=false` 또는 `actor_died_event`
- `final_state.target_state.alive`가 `false`
- 세션 종료가 정상 처리됨

`success.success_condition`은 최종 판정 근거입니다. `target_state.alive=false`가 확인되면 타깃 생존 여부 기준으로 성공하고, `actor_died_event`가 감지되면 사망 이벤트 기준으로 성공합니다.
프로젝트 입력 매핑에서 축 입력을 처리하지 못하는 환경에서는 `approach` 단계가 `skipped` 처리될 수 있으며, 이 동작을 비활성화하려면 `--strict-approach`를 사용합니다.

## 산출물 경로

- 리포트: `Artifacts/E2ERunner/runs/<run_id>/report.json`
- Unreal 로그: `launch.log_path`

`report.json`은 실행 결과 전체를 담는 최종 산출물입니다. `launch.log_path`는 `--launch` 모드에서만 생성되며, UnrealEditor의 표준 출력과 로그가 기록된 파일 경로입니다.

## 참고

리포트 JSON 필드 규약은 같은 폴더의 [`report_schema.json`](./report_schema.json)을 따릅니다.
