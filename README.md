# VR Detective – 백엔드 서버

VR 추리 심문 게임의 FastAPI 서버입니다. AI가 사건을 만들고, 서버가 규칙으로 검사하고, 심문 중에는 AI가 용의자를 연기합니다.
게임의 진실(범인, 결정적 증거)은 서버가 고정하고, AI는 대사만 만듭니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `main.py` | 서버 API, 게임 규칙(압박도·자백·판정), 사건 선택, 자동 사건 보충 |
| `case_generator.py` | AI 사건 생성 → 규칙 검사 → AI 검토 → `cases/`에 저장 |
| `validator.py` | 사건 규칙 검사기 (용의자 3명, 단서 역할 태그 등) |
| `test_validator.py` | 검사기 테스트 |
| `usage_counter.py` | AI 호출 횟수를 날짜별로 기록 (`ai_usage.json`) |
| `cases/` | 검사를 통과한 사건 파일 (최대 10개, 넘으면 오래된 것은 `cases/old/`로 이동) |

## 처음 실행하기

1. 가상환경을 만들고 패키지를 설치합니다.
   ```
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. 프로젝트 폴더에 `.env` 파일을 만듭니다.
   **`.env`는 각자 만들고 자기 키를 넣기 (키는 채팅·Notion에 붙여 넣지 않기)**
   ```
   LLM_API_KEY=각자_발급한_OpenRouter_키
   LLM_BASE_URL=https://openrouter.ai/api/v1
   LLM_MODEL=openrouter/free
   AUTO_GENERATE=off
   ```
3. 서버를 켭니다.
   ```
   python -m uvicorn main:app --reload
   ```
4. 브라우저에서 `http://127.0.0.1:8000/docs` (Swagger)를 열어 API를 테스트합니다.
5. 끌 때는 터미널에서 `Ctrl + C`.

## API

| 메서드 | 경로 | 설명 | AI 호출 |
|---|---|---|---|
| POST | `/game/start` | 게임 시작 (아직 안 한 가장 새 사건 → 없으면 무작위 → 없으면 기본 호텔 사건) | 0 |
| POST | `/game/interrogate` | 질문·증거 제시. 같은 질문 반복은 압박도 그대로, 이전 답변 재사용(`from_cache`) | 0~1 |
| GET | `/game/{game_id}/state` | 용의자 압박도·자백 상태 | 0 |
| POST | `/game/accuse` | 범인 + 결정적 증거 판정 | 0 |
| DELETE | `/game/{game_id}` | 게임 종료 | 0 |
| POST | `/case/generate` | 사건 1개 생성 (몇 분 걸림) | 2~16 |
| GET | `/case/list` | 저장된 사건 목록, 플레이 여부, 자동 생성 상태 | 0 |
| GET | `/usage` | 오늘·최근 7일 AI 호출 횟수, OpenRouter 계정 정보 | 0 |

## 사건 만들기

- 터미널: `python case_generator.py`
- Swagger: `POST /case/generate`
- 자동: `.env`에 `AUTO_GENERATE=on` → 게임을 시작할 때마다 뒤에서 다음 게임용 사건 1개를 만듭니다. (`.env`를 바꾸면 서버를 껐다 켜야 적용)

## 주의사항

- 무료 모델은 하루 호출 한도가 있습니다. 사건 1개 생성에 2~16번, 질문 1번에 1번 호출합니다. `GET /usage`로 확인하세요.
- 발표·시연 당일에는 `AUTO_GENERATE=off`를 권장합니다. (심문 답변에 한도를 남겨 두기)
- 게임 상태는 서버 메모리에만 있어서, 서버가 다시 시작되면(`--reload`로 코드 저장 시 포함) 진행 중인 게임이 사라집니다.
- AI 호출이 실패하면 기본 대사("머리가 너무 아파서…")가 나옵니다. HTTP 200이라도 AI가 성공했다는 뜻은 아닙니다.
- Unity를 다른 기기(Quest)에서 실행하면 `127.0.0.1` 대신 서버 PC의 IP로 바꿔야 합니다.
