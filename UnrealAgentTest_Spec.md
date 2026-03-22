# Unreal AI Test Remote API 기술 명세서

## 1. 문서 개요

### 1.1 목적
본 문서는 **AI Agent 기반 게임 플레이 테스트 자동화 시스템**을 Unreal Engine 프로젝트에 도입하기 위한 기술 명세를 정의한다.

목표는 다음과 같다.

- AI Agent가 Unreal 런타임에 대해 **고수준 명령**을 전달할 수 있어야 한다.
- Unreal은 그 명령의 결과를 **구조화된 상태 및 이벤트 정보**로 반환할 수 있어야 한다.
- 테스트 시나리오는 **Main Agent / Sub Agent 구조**로 실행될 수 있어야 한다.
- 하나의 Main Agent가 여러 Sub Agent를 병렬로 조율할 수 있어야 한다.
- 테스트 결과는 최종적으로 **기계 판독 가능**하면서도 **사람이 이해 가능한 보고서**로 정리될 수 있어야 한다.

---

## 2. 배경 및 문제 정의

기존의 일반적인 자동화 입력 방식(키보드/마우스 입력 주입, 화면 OCR, 픽셀 판독 등)은 게임 테스트 자동화에 다음과 같은 문제가 있다.

- 포커스/해상도/프레임 상태에 따라 결과가 흔들린다.
- 입력이 성공했는지 게임 로직 차원에서 판정하기 어렵다.
- 공격, 대미지, 사망, 드랍, 루팅과 같은 **게임 의미 단위**를 직접 관찰하기 어렵다.
- 병렬 테스트 및 실패 원인 분석이 어렵다.

따라서 본 시스템은 Unreal 런타임을 단순 GUI 앱이 아니라 **세션 기반 테스트 서버**로 간주하고, AI Agent는 Unreal에 대해 **고수준 테스트 명령**을 전달하며, 결과는 **authoritative state / event**로 수신하는 구조를 목표로 한다.

---

## 3. 시스템 목표

### 3.1 핵심 목표
1. Sub Agent가 Unreal 테스트 세션에 연결할 수 있어야 한다.
2. Sub Agent가 고수준 명령을 전송할 수 있어야 한다.
3. Unreal은 명령 결과를 이벤트/상태 형태로 반환할 수 있어야 한다.
4. Main Agent가 여러 Sub Agent를 동시에 조율할 수 있어야 한다.
5. 테스트 환경은 병렬 실행 가능해야 한다.
6. 시스템은 엔진 소스 수정 없이 프로젝트 단위로 도입 가능해야 한다.

### 3.2 비목표
다음은 초기 범위에서 제외한다.

- 범용 데스크톱 UI 자동화 프레임워크 개발
- 화면 OCR 기반 판정 시스템 구축
- 엔진 포크를 전제로 한 구조 설계
- Shipping 빌드에서 항상 활성화되는 원격 제어 시스템 구축

---

## 4. 아키텍처 개요

시스템은 다음 3계층으로 구성한다.

### 4.1 Main Agent
역할:
- 테스트 시나리오 로딩
- Sub Agent 생성 및 관리
- 테스트 분배 및 병렬 실행 조율
- 타임아웃/재시도/실패 분류
- 최종 테스트 보고서 생성

### 4.2 Sub Agent
역할:
- 특정 Unreal 테스트 세션과 연결
- 명령 전송
- 상태 조회
- 이벤트 스트림 수신
- 중간 진행 상황을 Main Agent에 보고

### 4.3 Unreal Runtime + Test Remote API
역할:
- 테스트 세션 시작/종료
- 고수준 명령 실행
- 상태 조회 응답
- 이벤트 발행
- 테스트용 로깅 및 아티팩트 관리

---

## 5. 구현 위치 및 배포 전략

본 기능은 **언리얼 엔진 소스 자체를 수정하는 방식이 아니라, 프로젝트 레벨의 C++ 플러그인(Project Plugin)** 으로 구현하는 것을 기본 원칙으로 한다.

### 5.1 구현 원칙
다음 기능들은 모두 **프로젝트 플러그인 내부의 C++ 모듈**로 구현한다.

- 테스트 원격 API
- 세션 관리
- 명령 처리
- 상태 조회
- 이벤트 기록 및 송신
- Sub Agent 연동용 인터페이스

### 5.2 프로젝트 플러그인 방식을 채택하는 이유
1. **엔진 포크를 피할 수 있다.**  
   엔진 소스 수정 없이 기능을 프로젝트 단위로 독립적으로 추가할 수 있으므로, 엔진 업그레이드 및 유지보수 부담을 줄일 수 있다.

2. **기능 격리가 용이하다.**  
   테스트 자동화용 코드와 실제 게임 플레이 코드를 분리할 수 있어, 운영 빌드와 테스트 빌드의 책임 경계를 명확하게 유지할 수 있다.

3. **활성/비활성 관리가 쉽다.**  
   테스트 전용 플러그인을 필요 환경에서만 활성화할 수 있으며, 배포 정책을 빌드 구성별로 분리하기 쉽다.

4. **프로젝트 자산과 결합하기 쉽다.**  
   테스트 맵, 테스트용 액터, 스폰 포인트, 더미 크리처, 시나리오 자산 등 콘텐츠 레벨 요소와 자연스럽게 연동할 수 있다.

### 5.3 구현 범위 구분

#### 프로젝트 플러그인(C++)
다음 요소는 **프로젝트 플러그인 내부 C++ 코드**로 구현한다.

- 테스트 원격 서버
- 고수준 명령 처리 계층
- 상태 조회 서비스
- 이벤트 기록/송신 서비스
- 세션 관리자
- Sub Agent용 연동 인터페이스
- 병렬 테스트 실행 지원용 런타임 관리 기능

#### 프로젝트 콘텐츠/블루프린트
다음 요소는 **프로젝트 콘텐츠 또는 블루프린트 자산**으로 구성할 수 있다.

- 테스트 전용 맵
- 테스트용 스폰 지점
- 더미 크리처
- 테스트 시나리오 배치 액터
- 테스트 전용 데이터 에셋
- 시각적 디버그용 블루프린트 헬퍼

### 5.4 비목표
초기 구현 단계에서는 다음을 목표로 하지 않는다.

- 언리얼 엔진 소스 직접 수정
- 엔진 포크 기반 기능 추가
- 콘텐츠 전용 구현만으로 전체 테스트 자동화 기능 구성

즉, **핵심 인프라는 프로젝트 플러그인(C++)에서 담당하고, 테스트 자산과 월드 구성은 콘텐츠/블루프린트에서 보조하는 구조**를 채택한다.

### 5.5 예외 사항
다음과 같은 특수한 요구가 발생하는 경우에만 엔진 소스 수정 여부를 별도로 검토한다.

- 프로젝트 플러그인 수준에서 접근 불가능한 저수준 입력 파이프라인 수정이 필요한 경우
- 엔진 내부 비공개 시스템에 대한 직접 후킹이 필요한 경우
- 성능 또는 구조적 이유로 엔진 레벨 통합이 불가피한 경우

단, 이러한 경우에도 **프로젝트 플러그인 방식으로 해결 가능한지 먼저 검토한 후**, 엔진 수정은 최후 수단으로 판단한다.

---

## 6. 핵심 설계 원칙

### 6.1 계층형 명령 설계
외부 Agent가 사용하는 명령은 하나의 추상화 계층만 두지 않는다. 테스트 목적에 따라 다음 3계층을 구분한다.

- **Semantic Command 계층**: 전투 판정, 대미지 검증, AI 행동 검증처럼 게임 의미 단위 결과를 빠르게 확인하기 위한 명령
- **Interaction Recipe 계층**: 실제 플레이어 입력 흐름과 UI 상태 변화를 검증하기 위해, 외부 문서/JSON에 정의된 단계형 입력 시퀀스를 실행하는 계층
- **Physical Input Atom 계층**: 버튼 탭, 버튼 홀드, 스틱 이동, 대기 같은 실제 컨트롤러 입력 원자 동작 계층

입력 디바이스 기본 표준은 **Xbox Gamepad**로 통일한다.

- 기본 버튼 표기: `A`, `B`, `X`, `Y`, `LB`, `RB`, `LT`, `RT`, `Back`, `Start`, `LS`, `RS`, `DPadUp`, `DPadDown`, `DPadLeft`, `DPadRight`
- 기본 스틱 표기: `LeftStick`, `RightStick`
- 다른 입력 장치는 필요 시 별도 device profile로 확장하되, 본 문서의 기본 예시와 recipe는 모두 Xbox Gamepad 기준으로 작성한다.

기본 원칙은 다음과 같다.

- 전투/판정/상태 검증 중심 테스트는 `move`, `attack`, `set_target` 같은 Semantic Command를 사용할 수 있다.
- UI/UX 검증이 필요한 테스트는 `equip_weapon`, `pickup_nearest_loot` 같은 **모호한 복합 명령을 단일 RPC로 호출하지 않는다**.
- 대신 `inventory.open`, `inventory.tab.to_items`, `inventory.focus_item_slot`, `ui.confirm` 같은 **외부 정의 기반 recipe**의 연속으로 수행한다.
- recipe는 사람이 읽을 수 있는 문서와 기계가 읽을 수 있는 JSON 양쪽으로 정의할 수 있어야 한다.
- Agent는 UI 구조를 추측하지 않고, recipe 정의와 현재 UI 상태를 바탕으로 행동해야 한다.
- `equip_weapon`, `pickup_nearest_loot` 같은 명령은 필요 시 편의용 매크로로 제공할 수 있으나, 내부적으로는 반드시 recipe sequence로 확장 가능해야 한다.

예: 무기 장착 UI 검증 시 권장 흐름
- `execute_recipe(recipe_id="inventory.open")`
- `execute_recipe(recipe_id="inventory.tab.to_items")`
- `execute_recipe(recipe_id="inventory.focus_item_slot", args={ "item_id": "Sword_01" })`
- `execute_recipe(recipe_id="ui.confirm")`
- `execute_recipe(recipe_id="inventory.close")`

### 6.2 결과는 구조화된 상태/이벤트로 수신
명령 수행 결과는 자연어 문자열이 아니라, JSON 구조의 상태 및 이벤트로 반환해야 한다.

예:
- `damage_applied`
- `actor_died`
- `weapon_equipped`
- `item_picked_up`

### 6.3 명령 수락과 실제 결과를 분리
명령 호출 직후 응답은 “명령이 수락되었는지”만 반환한다.

실제 게임 결과는 이벤트 스트림과 상태 조회를 통해 확인한다.
단계형 UI 명령의 경우 각 step의 성공/실패 역시 개별 이벤트 및 상태 전이로 확인해야 한다.

예:
- 명령 응답: `accepted = true`
- 이후 이벤트: `damage_applied(amount=40)`

### 6.4 Sub Agent는 API를 추측하지 않는다
Sub Agent는 Unreal API를 추론해서 사용하면 안 된다.  
반드시 다음 중 하나를 통해 **명시적 계약**을 받아야 한다.

- capability discovery
- SDK
- JSON 기반 CLI
- 상위 wrapper protocol
- interaction recipe document / JSON manifest

### 6.5 authoritative state 우선
테스트 결과 판정은 화면 OCR이나 문자열 로그 파싱보다, Unreal 내부 상태 조회 결과를 우선 기준으로 삼는다.

### 6.6 행동-관측 분리 원칙
UI/UX 및 게임플레이 테스트에서 Agent의 **행동은 실제 컨트롤러 입력처럼 수행**하되, **판정은 관측 계층을 통해 수행**한다.

- 행동 계층: 버튼 탭, 버튼 홀드, 스틱 이동, 스틱 해제 같은 physical input atom
- 관측 계층: 상태 조회, 이벤트 스트림, 로그, 스크린샷, 리플레이

우선순위는 다음과 같다.

1. authoritative state / event
2. 구조화된 로그
3. 스크린샷 / 영상 / 리플레이

즉 Agent는 플레이어처럼 입력하지만, “충분히 가까워졌는가”, “몬스터가 죽었는가”, “무기가 장착되었는가” 같은 판정은 가능한 한 Unreal 내부 상태를 기준으로 판단한다. 스크린샷은 주로 UI 상태 확인과 시각적 증거 보존에 사용한다.

### 6.7 타겟 해석 원칙
특정 타겟이 필요한 테스트는 다음 우선순위로 타겟을 해석한다.

1. 시나리오 JSON에 명시된 `target_actor_id`, `target_alias`, `target_tag`
2. 시나리오 JSON에 정의된 검색 조건(`class`, `team`, `hostile`, `distance`, `line_of_sight`)
3. 런타임 월드 검색을 통한 후보 탐색
4. 조건을 만족하는 가장 가까운 적 선택

즉 Agent는 가능하면 시나리오가 제공한 명시적 타겟을 사용하고, 필요 시 월드 검색으로 보완한다.

---

## 7. 통신 구조

### 7.1 기본 구조
권장 통신 구조는 다음과 같다.

- **HTTP**: 명령 실행 및 상태 조회
- **WebSocket**: 실시간 이벤트 스트림

### 7.2 통신 목적
#### HTTP
- 세션 시작/종료
- 명령 실행
- 상태 조회
- capability 조회

#### WebSocket
- 대미지 이벤트
- 사망 이벤트
- 장착 이벤트
- 루팅 이벤트
- 오류 이벤트
- 진행 이벤트

### 7.3 로컬 바인딩 원칙
테스트 원격 API는 기본적으로 **localhost 전용**으로 바인딩한다.

외부 공개 네트워크 바인딩은 기본적으로 금지한다.

---

## 8. Unreal 내부 구성 요소

### 8.1 GameTestRemoteServer
역할:
- HTTP/WebSocket 서버 진입점
- 라우팅
- 세션 식별
- 연결 관리
- capability 노출

책임:
- `/health`
- `/capabilities`
- `/session/*`
- `/command/*`
- `/state/*`
- `/events`

### 8.2 GameTestCommandService
역할:
- 외부 고수준 명령을 Unreal 내부 행동으로 변환

초기 필수 명령:
- `move`
- `stop_move`
- `look`
- `attack`
- `interact`
- `set_target`
- `clear_target`
- `teleport_player`
- `spawn_creature`
- `reset_scenario`
- `tap_button`
- `button_down`
- `button_up`
- `move_stick`
- `release_stick`
- `tap_dpad`
- `wait`
- `execute_recipe`
- `resolve_target`

보조 명령:
- `equip_weapon` (비UI 검증 또는 매크로 확장용)
- `pickup_nearest_loot` (비UI 검증 또는 매크로 확장용)

명령 설계 원칙:
- UI/UX 테스트의 기본 경로는 위젯 의미 명령이 아니라 `execute_recipe(recipe_id, args)`여야 한다.
- recipe는 내부적으로 `tap_button`, `button_down`, `button_up`, `move_stick`, `wait` 같은 physical input atom으로 확장되어야 한다.
- `nearest`, `auto`, `smart` 같은 암묵 타겟팅은 기본 경로로 삼지 않는다.
- 복합 명령은 내부 recipe 목록과 실제 input step 목록을 노출할 수 있어야 한다.
- 게임플레이 이동 명령은 정적인 `(0, 1)` 입력이 아니라 대상 방향을 기준으로 계산된 스틱 벡터를 전송할 수 있어야 한다.

### 8.2.1 Interaction Recipe Registry
UI 상호작용은 코드에 하드코딩된 행동이 아니라, 외부 정의 가능한 recipe registry를 통해 관리한다.

registry는 다음 형태 중 하나로 제공할 수 있다.
- 프로젝트 플러그인 설정 JSON
- 프로젝트 콘텐츠의 Data Asset
- 외부 문서에서 생성한 JSON manifest

필수 속성:
- recipe id
- 전제 UI 상태
- 입력 디바이스 타입 (`xbox_gamepad`)
- step 목록
- focus navigation graph 또는 slot coordinate map
- 각 step의 기대 UI 상태 변화
- 실패 시 재시도 가능 여부
- recipe set version
- content hash

예:
- `inventory.open`
- `inventory.tab.to_items`
- `inventory.focus_item_slot`
- `ui.confirm`
- `inventory.close`

### 8.2.2 Target Resolver
전투/상호작용 테스트에서 사용할 타겟은 별도 resolver를 통해 결정한다.

해석 소스:
- 시나리오 JSON의 명시적 타겟 정의
- 시나리오 JSON의 검색 조건
- 런타임 월드 검색 결과

지원 규칙:
- `target_actor_id` 우선
- `target_alias` 또는 `target_tag` 검색
- `hostile == true` 조건 검색
- 거리 기준 정렬
- line of sight 우선
- 조건 불충족 시 가장 가까운 적 fallback

### 8.3 GameTestQueryService
역할:
- authoritative state 제공

초기 필수 조회 항목:
- 플레이어 상태
- 장착 무기
- 현재 타겟
- 타겟 후보 목록
- 인벤토리 상태
- UI 상태
- 크리처 상태
- 공간 관계 상태
- 최근 대미지 이벤트
- 교전 상태
- 로딩 상태
- 맵 상태

UI 상태 조회 예:
- 현재 활성 화면/메뉴
- 메뉴 스택
- 현재 포커스된 위젯
- 현재 선택된 인벤토리 슬롯/아이템
- 현재 포커스 좌표 또는 focus node id
- 커서 표시 여부
- 입력 모드(Game Only / Game and UI / UI Only)
- 드래그 앤 드롭 진행 상태
- 현재 입력 디바이스 프로파일
- 최근 recipe 실행 결과

공간 관계 상태 조회 예:
- 플레이어 월드 위치 / 회전
- 대상 몬스터 월드 위치 / 회전
- 플레이어와 대상 간 거리(cm)
- 플레이어 전방 벡터와 대상 방향 벡터
- yaw delta to target
- normalized left stick vector to target
- line of sight 여부
- 내비게이션 가능 경로 길이
- 현재 이동 입력 상태
- 현재 공격 입력 상태

### 8.3.1 Observation Support
Agent가 플레이어처럼 입력하면서도 안정적으로 판정할 수 있도록 다음 관측 기능을 제공한다.

- `capture_screenshot`
- `capture_video_clip` 또는 리플레이 북마크
- `query_spatial_state`
- `query_actor_state`
- `query_combat_state`
- `query_target_candidates`
- `query_target_candidates`

원칙:
- 스크린샷은 시각 증거 및 UI 검증 보조용
- 위치/거리/사망 판정은 `query_spatial_state`, `query_actor_state`, 이벤트 스트림을 우선 사용

### 8.4 GameTestEventRecorder
역할:
- 게임 이벤트 기록
- 세션별 이벤트 발행
- trace_id 기반 명령-결과 연결

초기 필수 이벤트:
- `command_accepted`
- `command_rejected`
- `weapon_equipped`
- `target_changed`
- `damage_applied`
- `actor_died`
- `loot_spawned`
- `item_picked_up`
- `interaction_failed`
- `ui_screen_changed`
- `ui_focus_changed`
- `ui_item_selected`
- `ui_action_invoked`
- `recipe_started`
- `recipe_step_started`
- `recipe_step_succeeded`
- `recipe_step_failed`
- `command_step_started`
- `command_step_succeeded`
- `command_step_failed`
- `error`

### 8.5 GameTestSessionManager
역할:
- 세션 생성/종료
- 세션별 플레이어/맵/시나리오 바인딩
- 세션별 이벤트 큐 분리
- 세션 타임아웃 관리
- 세션별 로그 경로 관리

---

## 9. 상태 및 이벤트 모델

### 9.1 공통 필드
모든 명령 응답/상태/이벤트는 최소 다음 필드를 포함해야 한다.

- `session_id`
- `timestamp`
- `trace_id` (해당 시)
- `type`
- `payload`

### 9.2 플레이어 상태
필수 필드:
- player id
- 위치
- 회전
- HP
- 현재 장착 무기
- 현재 타겟
- 행동 상태
- 현재 입력 상태(선택)

### 9.3 크리처 상태
필수 필드:
- actor id
- HP
- alive/dead
- 위치
- 상태값
- 최근 피격 여부

### 9.4 대미지 이벤트
필수 필드:
- source actor id
- target actor id
- damage amount
- damage type
- critical 여부
- source weapon id
- target hp before
- target hp after
- trace_id

### 9.5 아이템 획득 이벤트
필수 필드:
- picker actor id
- item id
- quantity
- inventory slot (선택)
- trace_id

### 9.6 UI 상태
필수 필드:
- current screen id
- open menu stack
- focused widget id
- focused navigation node id
- selected panel id (선택)
- selected slot id 또는 item id (선택)
- input mode
- cursor visible 여부
- drag source / drag target (해당 시)
- active device profile (`xbox_gamepad`)
- active recipe id (해당 시)

UI/UX 테스트에서는 상태 판정 시 다음을 함께 확인한다.
- 명령 전 상태
- step 실행 후 상태
- 최종 게임플레이 상태

### 9.7 Interaction Recipe 실행 이벤트
필수 필드:
- recipe id
- recipe version
- recipe set version
- device profile
- step index
- input action
- expected ui state
- observed ui state
- success 여부
- trace_id

### 9.8 공간 관계 상태
필수 필드:
- player actor id
- target actor id
- player position
- target position
- distance_cm
- player forward vector
- direction to target
- yaw_delta_degrees
- recommended_left_stick_x
- recommended_left_stick_y
- line of sight 여부
- navigation path length (선택)
- target in attack range 여부

### 9.9 타겟 후보 상태
필수 필드:
- candidate actor id
- alias 또는 tag 목록
- hostile 여부
- distance_cm
- line of sight 여부
- priority score
- selected 여부

### 9.10 전투 입력 상태
필수 필드:
- move stick vector
- look stick vector
- attack button pressed 여부
- attack button hold duration
- pressed buttons 목록
- last_button_down timestamp
- last_button_up timestamp
- current locomotion state
- current combat state

---

## 10. Sub Agent 측 구현 요구사항

### 10.1 UnrealTestClient SDK
Sub Agent는 Unreal 테스트 API를 직접 raw request로 조합하기보다, 전용 클라이언트 SDK를 사용해야 한다.

필수 기능:
- `connect`
- `disconnect`
- `get_capabilities`
- `get_interaction_recipes`
- `start_session`
- `stop_session`
- `send_command`
- `get_state`
- `subscribe_events`
- `wait_for_event`
- `resolve_target_from_scenario`

### 10.2 고수준 래퍼 메서드
SDK는 최소 다음 래퍼를 제공해야 한다.

- `move(direction, duration)`
- `attack(target_id=None)`
- `query_player_state()`
- `query_target_state()`
- `query_inventory_state()`
- `query_ui_state()`
- `query_spatial_state(target_id=None)`
- `query_actor_state(actor_id)`
- `query_target_candidates(filters=None)`
- `capture_screenshot(tag=None)`
- `tap_button(button_id, duration_ms=None)`
- `button_down(button_id)`
- `button_up(button_id)`
- `move_stick(stick_id, x, y, duration_ms)`
- `release_stick(stick_id)`
- `tap_dpad(direction, count=1)`
- `wait(duration_ms)`
- `execute_recipe(recipe_id, args=None)`
- `resolve_target(criteria=None)`
- `move_toward_target_with_left_stick(target_id, duration_ms)`
- `wait_until(predicate, timeout_ms)`

복합 동작은 opaque command가 아니라 조합형 helper로 제공하는 것을 권장한다.

예:
- `open_inventory_via_gamepad()`
- `move_to_inventory_tab(tab_id)`
- `equip_item_via_inventory_recipe(item_id)`
- `resolve_target_from_scenario_or_nearest_enemy()`
- `approach_target_via_left_stick(target_id, stop_distance_cm)`
- `press_attack_until_target_dead(target_id)`
- `loot_item_via_world_interaction(item_id=None)`

이 helper는 내부적으로 recipe sequence를 생성하며, 각 recipe step의 trace를 외부에서 확인할 수 있어야 한다.

### 10.3 이벤트 루프
Sub Agent는 이벤트 수신을 위한 별도 루프를 가져야 한다.

필수 기능:
- WebSocket 수신
- 이벤트 큐 관리
- trace_id 기반 매칭
- 타임아웃 처리
- 세션 종료 감지
- 중복 이벤트 제거

### 10.4 상태 해석기
Sub Agent는 상태 및 이벤트를 룰 기반으로 해석해야 한다.

예:
- `damage_applied.amount == 40`
- `actor_died.target == Creature_01`
- `inventory contains GoblinGear_01`
- `ui.current_screen == "inventory"`
- `ui.focused_navigation_node == "inventory_grid_r3_c2"`
- `recipe_step_succeeded.recipe_id == "inventory.open"`
- `recipe_step_succeeded.input_action == "tap_button:Start"`

LLM은 상위 시나리오 판단에 사용할 수 있으나, 상태 파싱 자체는 규칙 기반 구현을 우선한다.

### 10.5 재시도 정책
다음에 대한 재시도/실패 정책이 필요하다.

- 연결 실패
- 명령 전송 실패
- accepted 응답 실패
- 이벤트 수신 타임아웃
- 세션 비정상 종료

---

## 11. Main Agent / Sub Agent 병렬 아키텍처

### 11.1 Main Agent 책임
- 테스트 계획 수립
- 테스트 시나리오 분배
- Sub Agent 인스턴스 생성
- 병렬 실행 조율
- 재시도/중단/복구 결정
- 결과 수집 및 보고서 생성

### 11.2 Sub Agent 책임
- 단일 Unreal 테스트 세션 담당
- 시나리오 단계 수행
- 이벤트 수집
- 상태 조회
- 중간 결과 보고

### 11.3 병렬 실행 방식
각 Sub Agent는 독립된 Unreal 인스턴스에 연결하는 것을 기본 원칙으로 한다.

각 인스턴스는 다음을 분리한다.

- session id
- port
- run id
- log path
- artifact path

예:
- Sub-01 → localhost:31001
- Sub-02 → localhost:31002
- Sub-03 → localhost:31003

---

## 12. 부트스트랩 및 프로세스 실행

### 12.1 명령행 인자 활용
각 Unreal 테스트 인스턴스는 명령행 인자를 통해 bootstrap 한다.

권장 인자:
- `-TestMode`
- `-SessionId=...`
- `-Port=...`
- `-RunId=...`
- `-Scenario=...`
- `-Seed=...`

### 12.2 역할
명령행 인자는 다음 용도로 사용한다.

- 테스트 모드 활성화
- 세션 식별
- 포트 할당
- 시나리오 초기 설정
- deterministic seed 설정

명령행 인자는 실시간 제어 채널이 아니라 **초기 실행 설정용**으로 사용한다.

---

## 13. 입력 처리 전략

### 13.1 기본 원칙
Sub Agent는 “결과만 만드는 명령”과 “실제 사용자 입력 경로를 재현하는 명령”을 구분해야 한다.

- 기능 검증 중심 테스트는 Semantic Command를 사용할 수 있다.
- UI/UX 검증 중심 테스트는 Interaction Recipe 시퀀스를 사용해야 한다.
- 동일한 시나리오라도 목적에 따라 실행 모드를 선택할 수 있어야 한다.
- UI recipe는 코드가 아니라 외부 문서 또는 JSON manifest로 정의 가능해야 한다.
- 게임플레이 테스트에서도 이동/공격 같은 실제 조작은 가능하면 컨트롤러 입력 원자로 수행한다.
- 단, 거리/위치/사망 여부 판정은 상태 조회와 이벤트 스트림을 우선 사용한다.
- 기본 컨트롤러 표준은 `xbox_gamepad`다.
- 타겟이 필요한 시나리오는 시나리오 JSON에서 타겟을 명시하거나, 명시되지 않으면 월드 검색 fallback을 허용한다.

### 13.2 실행 모드
#### 1순위: Recipe-Driven Interaction Mode
UI/UX 테스트의 기본 모드다. 실제 플레이어가 수행하는 컨트롤러 입력 경로를 recipe 단위로 검증한다.

예: 인벤토리에서 무기 장착
- `execute_recipe("inventory.open")`
- `execute_recipe("inventory.tab.to_items")`
- `execute_recipe("inventory.focus_item_slot", { "item_id": "Sword_01" })`
- `execute_recipe("ui.confirm")`
- `query_ui_state()`
- `query_player_state()`

장점:
- 실제 사용자 흐름 검증 가능
- 버튼 입력 순서 자체를 검증 가능
- UI 상태/포커스/선택 상태 검증 가능
- UX 회귀 탐지에 유리

#### 2순위: Semantic Shortcut Mode
게임 규칙, 전투 결과, 아이템 장착 결과만 빠르게 확인할 때 사용하는 모드다.

예:
- `equip_weapon("Sword_01")`
- `pickup_nearest_loot()`

제약:
- UI 경로가 올바르게 동작했는지 검증하지 못한다.
- UI/UX 테스트 케이스의 주 경로로 사용하지 않는다.
- 사용 시 결과 보고서에 shortcut mode 사용 여부를 남겨야 한다.

#### 3순위: Raw Input Fallback Mode
프로젝트 플러그인 계층에서 recipe가 아직 준비되지 않은 화면에 한해 제한적으로 사용한다.

예:
- 특정 임시 디버그 메뉴에 대한 키 입력 주입
- 서드파티 UI 플러그인 화면에 대한 제한적 포커스 이동

제약:
- 반드시 UI 상태 조회와 함께 사용한다.
- 전투 판정, 루팅 판정, 장착 판정의 최종 근거로 단독 사용하지 않는다.

### 13.3 Interaction Recipe 설계 규칙
- recipe는 특정 화면에서의 실제 사용자 입력 절차를 서술해야 한다.
- recipe는 게임 로직 함수 이름이 아니라 입력 디바이스 행동으로 구성해야 한다.
- recipe는 사람이 읽는 문서와 기계가 읽는 JSON이 동일한 의미를 가져야 한다.
- recipe는 전제 조건, 입력 step, 기대 UI 상태, 실패 조건을 포함해야 한다.
- 각 step은 `accepted/rejected` 외에 기대 상태 전이를 문서화해야 한다.
- 각 step은 개별 `trace_id` 또는 parent trace 하위의 `step_id`로 추적 가능해야 한다.
- recipe에 사용되는 버튼 이름은 모두 Xbox Gamepad 논리 버튼 기준이어야 한다.

### 13.4 Interaction Recipe 저장 방식
recipe는 다음과 같은 외부 정의 파일로 관리할 수 있다.

- `InteractionRecipes.md`
- `interaction_recipes.json`
- 프로젝트 Data Asset에서 export한 JSON
- `scenario_targets.json`

필요 시 다음 보조 정의를 함께 둔다.

- `ui_navigation_graph.json`: 포커스 노드 간 상하좌우 이동 규칙
- `ui_slot_locator.json`: 아이템/슬롯/탭과 포커스 노드의 매핑 규칙

JSON 예시:

```json
{
  "recipe_id": "inventory.open",
  "device_profile": "xbox_gamepad",
  "recipe_set_version": "1.0.0",
  "preconditions": {
    "ui.current_screen": "hud"
  },
  "steps": [
    {
      "action": "tap_button",
      "button": "Start",
      "expected_ui_state": {
        "current_screen": "main_menu"
      }
    },
    {
      "action": "tap_button",
      "button": "RB",
      "repeat": 2,
      "expected_ui_state": {
        "current_screen": "inventory"
      }
    }
  ]
}
```

포커스 이동이 필요한 경우 Agent는 UI를 추측하지 않고, 다음 순서로 동작한다.

1. 현재 `query_ui_state()`로 focused navigation node를 확인
2. `ui_navigation_graph.json`에서 목표 노드까지의 경로 계산
3. 경로에 따라 `tap_dpad(Left/Right/Up/Down)` sequence 실행
4. 각 step마다 기대 focus node 도달 여부 검증

### 13.5 복합 명령 정책
`equip_weapon`, `pickup_nearest_loot` 같은 명령은 삭제 대상이라기보다 **편의용 매크로 또는 shortcut**으로 재정의한다.

- 기능 테스트에서는 사용 가능
- UI/UX 테스트에서는 내부 recipe expansion을 반드시 노출해야 함
- 보고서에는 “shortcut 검증”인지 “recipe-driven interaction 검증”인지 구분해서 기록해야 함

### 13.6 예시: 게임패드 기반 장비 장착 시퀀스
다음은 사용자가 요구한 흐름과 같은 형태의 recipe 기반 예시다.

문서 정의:
- `inventory.open`: `Start` 버튼 1회 입력 후 인벤토리 화면 진입 확인
- `inventory.tab.to_items`: `RB` 버튼 2회 입력 후 인벤토리 탭 포커스 확인
- `inventory.focus_item_slot`: 현재 포커스에서 대상 아이템 슬롯까지 십자키 경로 이동
- `ui.confirm`: `A` 버튼 입력 후 선택 확인

Agent 실행:
1. `execute_recipe("inventory.open")`
2. `execute_recipe("inventory.tab.to_items")`
3. `execute_recipe("inventory.focus_item_slot", { "item_id": "Sword_01" })`
4. `execute_recipe("ui.confirm")`
5. `query_player_state()  // equipped_weapon == Sword_01`

즉 Agent는 “인벤토리 열기” 방법을 추론하지 않고, 미리 정의된 recipe를 읽어 그대로 수행한다.

### 13.7 관측 전략
실제 입력 기반 테스트에서도 Agent는 다음 관측 루프를 가져야 한다.

1. 현재 UI 상태 또는 공간 상태 조회
2. 다음 input atom 또는 recipe 선택
3. 입력 수행
4. 이벤트 / 상태 변화 확인
5. 목표 달성 여부 판단 또는 다음 입력 반복

관측 소스 사용 원칙:
- UI 화면 진입, 탭 전환, 포커스 이동: `query_ui_state()` + 스크린샷
- 위치, 거리, 방향, 전투 가능 범위: `query_spatial_state()`
- 장착 완료, 피격, 사망: `query_player_state()`, `query_actor_state()`, 이벤트 스트림
- 최종 증적: 로그 + 스크린샷 + 이벤트 타임라인

### 13.8 타겟 선택 전략
타겟이 필요한 시나리오는 다음 우선순위로 대상을 선택한다.

1. 시나리오 JSON의 `target_actor_id`
2. 시나리오 JSON의 `target_alias`
3. 시나리오 JSON의 `target_query`
4. 월드 검색으로 찾은 가장 가까운 적

시나리오 JSON 예시:

```json
{
  "scenario_id": "combat_weapon_a_001",
  "target": {
    "target_alias": "primary_enemy",
    "target_query": {
      "hostile": true,
      "max_distance_cm": 30000,
      "prefer_line_of_sight": true,
      "sort": "nearest"
    }
  }
}
```

월드 검색 fallback 규칙:
- hostile actor만 후보로 본다.
- dead actor는 제외한다.
- 같은 조건이면 distance가 가장 짧은 대상을 선택한다.
- line of sight가 있는 대상을 우선한다.

### 13.9 방향 기반 이동 입력 원칙
`몬스터를 향해 이동한다`는 표현은 단순히 `LeftStick = (0, 1)`를 반복한다는 뜻이 아니다.

원칙:
- Agent는 `query_spatial_state(target_id)`를 통해 대상 방향 벡터와 yaw delta를 읽는다.
- 이를 기반으로 현재 카메라/플레이어 기준 이동 방향에 맞는 `LeftStick(x, y)` 값을 계산한다.
- 따라서 이동 입력은 “앞으로 고정”이 아니라 “대상을 향해 정규화된 스틱 벡터”를 보내는 방식이어야 한다.

예:
- 대상이 정면이면 `LeftStick(0.0, 1.0)`
- 대상이 우전방이면 `LeftStick(0.35, 0.93)`
- 대상이 좌측이면 `LeftStick(-1.0, 0.0)`

### 13.10 버튼 입력 lifecycle 원칙
버튼 입력은 `hold_button(300ms)` 같은 축약 표현보다 `button_down` / `button_up` 중심으로 해석하는 것을 기본으로 한다.

원칙:
- `tap_button(A)`는 내부적으로 `button_down(A)` 후 짧은 지연 뒤 `button_up(A)`로 구성한다.
- 연속 공격, 차징 공격, 조준 유지 같은 동작은 `button_down` 후 상태를 관측하다가 조건 충족 시 `button_up`으로 종료한다.
- 보고서에는 버튼이 눌린 시점과 해제된 시점을 모두 남긴다.

### 13.11 예시: `A무기를 착용하여 100m 앞 몬스터를 공격하여 무찌른다`
다음은 사용자가 제시한 QA/회귀 테스트 흐름을 문서형 시나리오로 정리한 예다.

사전 조건:
- 플레이어는 HUD 화면에 있다.
- 인벤토리에 `Weapon_A`가 존재한다.
- 타겟은 시나리오 JSON의 명시적 대상 또는 월드 검색 fallback으로 결정된다.
- 게임패드 프로파일은 `xbox_gamepad`다.

실행 단계:
1. `execute_recipe("inventory.open")`
2. `execute_recipe("inventory.tab.to_items")`
3. `execute_recipe("inventory.focus_item_slot", { "item_id": "Weapon_A" })`
4. `execute_recipe("ui.confirm")`  // Xbox `A`
5. `query_player_state()`로 `equipped_weapon == Weapon_A` 확인
6. `resolve_target(criteria=scenario.target)` 또는 `query_target_candidates()`로 대상 확정
7. `query_spatial_state(target_id=resolved_target)`로 현재 거리와 방향 확인
8. 필요 시 `capture_screenshot(tag="before_approach")`로 시각 증거 저장
9. 목표 거리 이하가 될 때까지 다음 루프 수행
10. `query_spatial_state(target_id=resolved_target)`에서 `recommended_left_stick_x`, `recommended_left_stick_y`를 읽음
11. `move_stick("LeftStick", recommended_left_stick_x, recommended_left_stick_y, duration_ms=300)` 수행
12. 거리 감소 여부와 `target_in_attack_range`를 확인
13. `target_in_attack_range == true` 또는 정의한 거리 임계값 이하가 되면 `release_stick("LeftStick")`
14. `button_down("RT")`
15. 전투 중 `query_actor_state(resolved_target)`와 `damage_applied`, `actor_died` 이벤트를 구독
16. 타겟이 살아 있으면 공격 상태 유지 또는 프로젝트 규칙에 맞게 `RT`를 반복 입력
17. `actor_died.target == resolved_target` 또는 `alive == false`가 확인되면 `button_up("RT")`
18. `capture_screenshot(tag="after_combat")`
19. 세션 로그, 이벤트 로그, 상태 스냅샷, 스크린샷을 묶어 결과 보고서 생성

판정 기준:
- 장착 성공: `equipped_weapon == Weapon_A`
- 타겟 확정 성공: `resolved_target != null`
- 접근 성공: 거리 값이 지속적으로 감소
- 전투 성공: `resolved_target.alive == false`
- 증적 확보: 전/후 스크린샷, 전투 이벤트 타임라인, 상태 스냅샷 존재

---

## 14. 로깅 및 아티팩트

### 14.1 필수 로그
- 세션 로그
- 명령 로그
- 이벤트 로그
- 상태 스냅샷 로그
- 오류 로그

### 14.2 권장 아티팩트
- 스크린샷
- 리플레이
- 최근 이벤트 덤프
- 실패 시 상태 덤프
- 전투 타임라인 요약
- recipe 실행 trace

### 14.3 디렉터리 분리
모든 아티팩트는 다음 단위로 분리한다.

- run id
- session id
- timestamp

---

## 15. 보안 및 운영 제약

### 15.1 기본 제약
- localhost 전용 바인딩
- Dev/Test 빌드 전용 활성화
- Shipping 기본 비활성화
- 세션 토큰 또는 최소 식별 키 검증
- 외부 공개망 노출 금지

### 15.2 운영 정책
- 테스트 서버는 자동화 환경에서만 활성화
- 테스트 전용 플러그인은 필요 환경에서만 enable
- production runtime과 테스트 runtime 책임 분리

---

## 16. 구현 단계 제안

### Phase 1. 최소 세션 서버
구현:
- `/health`
- `/capabilities`
- `/session/start`
- `/session/stop`

완료 기준:
- 외부 클라이언트 연결 가능
- 세션 lifecycle 관리 가능

### Phase 2. 최소 명령/상태
구현:
- `attack`
- `get_player_state`
- `get_target_state`
- `tap_button`
- `tap_dpad`
- `move_stick`
- `release_stick`
- `execute_recipe`
- `get_ui_state`
- `query_spatial_state`

완료 기준:
- 명령 accepted 응답 가능
- 상태 JSON 조회 가능
- 최소 recipe 기반 UI 상호작용 시퀀스 검증 가능
- 이동 입력과 거리 감소 검증 가능

### Phase 3. 이벤트 스트림
구현:
- `damage_applied`
- `actor_died`
- `weapon_equipped`
- `ui_screen_changed`
- `ui_focus_changed`
- `command_step_succeeded`
- `recipe_step_succeeded`

완료 기준:
- 명령-결과 추적 가능
- trace_id 매칭 가능
- UI step별 상태 전이 추적 가능
- 전투 입력과 결과 이벤트 연결 가능

### Phase 4. 루팅/상호작용
구현:
- `get_inventory_state`
- `item_picked_up`
- `loot_spawned`
- `inventory.focus_item_slot` recipe
- `ui.confirm` recipe
- `drag_item` 또는 동등한 recipe

완료 기준:
- 처치 후 루팅 검증 가능
- 인벤토리 기반 상호작용 검증 가능

### Phase 5. Sub Agent SDK
구현:
- UnrealTestClient
- 이벤트 루프
- 상태 해석기
- 재시도/타임아웃 정책

완료 기준:
- SDK만으로 시나리오 구동 가능

### Phase 6. 병렬 실행 런처
구현:
- 포트 allocator
- process launcher
- log/artifact 분리
- session manager integration

완료 기준:
- 다중 Sub Agent 병렬 테스트 가능

---

## 17. 금지 사항

다음 구현 방식은 금지하거나 지양한다.

- API 경로를 Agent가 추측하게 만드는 것
- 자연어 문자열만 반환하는 것
- 화면 OCR만으로 결과를 판정하는 것
- 문자열 로그 파싱에만 의존하는 것
- 세션 상태를 전역 singleton으로 섞는 것
- 테스트 서버를 public network에 노출하는 것
- Shipping 빌드에 기본 활성화하는 것

---

## 18. 최종 산출물

### Unreal 측
- 프로젝트 플러그인
- 테스트 서버 모듈
- 명령 처리 서비스
- 상태 조회 서비스
- 이벤트 기록/송신 서비스
- 세션 관리자
- 병렬 실행 bootstrap 지원
- interaction recipe registry 로더

### Sub Agent 측
- UnrealTestClient SDK
- 이벤트 루프
- 상태 해석기
- 명령 재시도/타임아웃 처리기
- recipe 문서/JSON 해석기
- 관측 루프 및 증적 수집기

### 공통
- JSON 스키마
- 에러 코드 정의
- trace_id 규칙
- 로그 포맷
- artifact 디렉터리 규칙
- interaction recipe 문서/manifest 규칙

---

## 19. 한 줄 요약

본 시스템은 Unreal을 **AI가 조작 가능한 세션 기반 테스트 서버**로 확장하고, 이를 **프로젝트 레벨 C++ 플러그인**으로 구현하며, Sub Agent는 **고수준 명령 + 구조화된 상태/이벤트**를 통해 테스트를 수행하도록 설계한다.
