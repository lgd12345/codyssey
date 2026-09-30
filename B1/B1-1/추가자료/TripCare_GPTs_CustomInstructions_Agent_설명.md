# TripCare 관점에서 보는 Custom Instructions, GPTs, 에이전트 기능

## 개요

TripCare OS는 \*\*전문 시스템 프롬프트(System Prompt)\*\*이자 **여행
의사결정 규격**이다. 반면 **Custom Instructions**, **GPTs**, **에이전트
기능**은 이 규격을 어디에 적용하고 어떤 실행 능력을 부여하는지에 관한
플랫폼 기능이다.

​

구분                    설명                    TripCare와의 관계

​

Custom Instructions     모든 일반 대화에        TripCare 전체를
적용되는 개인 설정      넣기에는 부적합

GPTs                    특정 목적의 맞춤형      TripCare를 제품 형태로
ChatGPT                 만드는 방법

에이전트 기능           목표를 받아 여러 단계를 TripCare를 실행형 여행
수행하는 실행 모드      에이전트로 확장

TripCare OS             여행 판단 규칙과 상태   위 기능들이 따라야 하는
관리 시스템             운영 규칙
------------------------

## 1. Custom Instructions

* 한국어로 답변

* 간결하게 설명

* 여행에서는 예산을 중요하게 고려

TripCare는 단순한 말투 설정이 아니라 상태 관리, 예산 검증, 실행 가능성
판단, 정보 검증, 조건 변경 처리 등의 시스템 규칙을 포함한다.

## 2. GPTs

구성 요소

* Instructions

* Knowledge

* Capabilities

* Actions

TripCare에서는 Instructions에
**TripCare\_OS\_CustomGPT\_Production\_EN\_v1.4**를 넣고, Knowledge에는 설계
문서와 테스트 사례를 넣는 것이 적절하다.

## 3. 에이전트 기능

에이전트는 다음과 같은 작업을 수행한다.

1. 조건 분석

2. 웹 검색

3. 가격 확인

4. 이동시간 계산

5. 예산 계산

6. 결과 검증

7. 사용자 승인

현재 TripCare는 에이전트 자체라기보다 **Agent Policy(운영 정책)​**
수준이다.

# TripCare를 GPTs로 만드는 방법

1. ChatGPT 웹에서 GPT 생성

2. 이름, 설명, 대화 시작 문구 작성

3. Instructions에 Production Prompt 입력

4. Knowledge에 설계 문서 업로드

5. Web Search, Data Analysis 활성화

6. Preview 테스트

7. 비공개 저장 후 반복 테스트

8. 필요 시 Actions(API) 연결

## 권장 구조

```text
TripCare GPT
├── Instructions
│      └── TripCare OS Production Prompt
├── Knowledge
│      ├── 설계 문서
│      └── 테스트 사례
├── Web Search
├── Data Analysis
└── (향후) Actions
```

## 발전 단계

1단계: 일반 프롬프트
“여행지를 추천해 줘”

2단계: 구조화 프롬프트
목적, 예산, 동행자, 취향 입력

3단계: 시스템 프롬프트
상태, 제약, 검증, 출력 정책 정의

4단계: Custom GPT
TripCare 전용 인터페이스와 지식 파일 구성

5단계: Tool-enabled GPT
검색·분석·외부 API 연결

6단계: Agent
여러 도구를 사용해 계획·실행·검증 반복

7단계: API 기반 서비스
별도 앱, 데이터베이스, 사용자 계정, 상태 저장

8단계: Evaluation harness
수백 개 테스트로 회귀·환각·상태 유지 검증

​

```text
일반 프롬프트
→ 시스템 프롬프트(현재 TripCare)
→ Custom GPT
→ Tool-enabled GPT
→ Agent
→ API 기반 서비스
→ Evaluation Harness
```

​
