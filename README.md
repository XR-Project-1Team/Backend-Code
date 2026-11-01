# VR Detective – 백엔드 서버

VR 추리 심문 게임의 FastAPI 서버입니다. AI가 사건을 만들고, 서버가 규칙으로 검사하고, 심문 중에는 AI가 용의자를 연기합니다.
게임의 진실(범인, 결정적 증거)은 서버가 고정하고, AI는 대사만 만듭니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `main.py` | 서버 API, 게임 규칙(압박도·자백), 사건 선택, 자동 사건 보충 |
| `game_rules.py` | 질문 카테고리, 증거 관문(압박도 천장), 바이탈 리딩, 범인 지목(오답 기회·힌트·등급), 현장 조사(구역) — AI 호출 없음 |
| `interrogation.py` | 심문 AI 프롬프트 + 대답 검사(자백·비밀 누설, 근거 없는 시각) + 1번 재요청 |
| `persona.py` | 용의자 말투 프리셋 5종 |
| `question_bank.py` | 용의자별 카테고리 질문 목록 (사건별 AI 질문 + 질문 틀) — AI 호출 없음 |
| `case_generator.py` | AI 사건 생성 → 형식 검사 → 품질 검사 → AI 검토 → `cases/`에 저장 |
| `validator.py` / `case_quality.py` | 사건 형식 검사기 / 사건 내용 품질 검사기 |
| `test_validator.py` / `test_interrogation.py` / `test_game_rules.py` | 테스트 (AI 호출 없음) |
| `demo_interrogation.py` | 실제 AI로 심문을 돌려 보는 데모 (AI 호출 있음) |
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
| POST | `/game/start` | 게임 시작 (아직 안 한 가장 새 사건 → 없으면 무작위 → 없으면 기본 호텔 사건). 단서는 찾은 것만, 조사 구역 목록(`areas`), 사건 브리핑(`briefing`) | 0 |
| POST | `/game/investigate` | 구역(`area_id`)을 조사해 그 구역의 단서를 찾음 | 0 |
| POST | `/game/interrogate` | 질문·증거 제시. 같은 질문 반복(띄어쓰기·문장부호만 달라도)은 압박도 그대로, 이전 답변 재사용(`from_cache`). 빈 질문은 400, 끝난 게임은 409 | 0~2 |
| GET | `/game/{game_id}/state` | 용의자 압박도·자백 상태 | 0 |
| POST | `/game/accuse` | 범인 + 결정적 증거 판정. 틀리면 힌트를 주고 다시 도전 (3번 틀리면 미해결 엔딩) | 0 |
| DELETE | `/game/{game_id}` | 게임 종료 | 0 |
| POST | `/case/generate` | 사건 1개 생성 (몇 분 걸림) | 2~16 |
| GET | `/case/list` | 저장된 사건 목록, 플레이 여부, 자동 생성 상태 | 0 |
| GET | `/usage` | 오늘·최근 7일 AI 호출 횟수, OpenRouter 계정 정보 | 0 |

### 카테고리별 질문 목록
게임 시작 응답의 `questions`: `[{suspect_id: 1, categories: [{category: "관계", questions: [...]}, ...]}, ...]`
- 카테고리는 `관계` / `알리바이` / `감정`, 카테고리마다 최대 6개
- 1순위: 사건을 만들 때 AI가 쓴 용의자 맞춤 질문(`suspects[].questions`), 2순위: `question_bank.py`의 질문 틀에 피해자 이름·사망 추정 시각·다른 용의자를 채운 질문
- 게임 중에 질문을 만들려고 AI를 부르지 않음 (질문 1번에 대답용 AI 1번은 그대로)
- 질문을 보낼 때 `question_category`를 함께 보내면 바이탈 판정이 그 카테고리 기준으로 됨

### 단서 질문 (찾은 단서를 말로 떠보기)
- 단서를 찾으면 그 단서의 질문이 열림: 시작 응답 `clue_questions`, 조사 응답 `new_clue_questions`(이번에 열린 것)·`clue_questions`(전체) — `[{clue_id, text}]`
- 질문할 때 `clue_id`를 함께 보내면 카테고리는 `단서`, 압박도는 보통 질문처럼 +5(증거 관문 천장까지), 아직 못 찾은 단서면 400
- 바이탈: 범인은 자기를 가리키는 단서면 압박도 30 미만 `긴장`, 이상 `거짓` / 무고한 사람은 자기 비밀 단서면 `긴장` (증거 제시보다 약한 신호)
- 심문 AI에는 단서 이름만 알려 주고(설명은 안 줌), 형사가 먼저 꺼낸 단서는 범인이 언급해도 '범인만 아는 사실' 위반으로 보지 않음
- 새로 만드는 사건은 AI가 단서마다 `question`을 쓰고, 없으면 "「단서 이름」에 대해 들은 적이 있습니까?"

### 사건 브리핑
게임 시작 응답의 `briefing`: `title`, `victim`, `location`, `time_of_death`, `text`(수사 브리핑 글), `suspects`("이름 (직업) - 소개" 목록)
- 새로 만드는 사건은 AI가 `briefing`(3~5문장)을 함께 만들고, `case_quality.py`가 빈 글·정답 노출 단어·용의자 이름을 검사
- 브리핑 글이 없는 사건은 `case_summary`로 대신함

### 현장 조사 (구역별 단서 찾기)
단서마다 조사 구역(`area`)이 있는 사건은 처음에 단서가 0개입니다. 구역을 조사해야 그 구역의 단서가 나옵니다.

1. `POST /game/start` → `investigation: true`, `areas: [{area_id: "A1", name: "5층 테라스", investigated: false}, ...]`, `evidences: []`
2. `POST /game/investigate` `{"game_id": "...", "area_id": "A1"}` → `message`, `found_evidences`(이 구역 단서), `evidences`(찾은 단서 전체), `areas`
3. 이미 조사한 구역을 다시 조사하면 `already_investigated: true` (새 단서 없음)

- 아직 못 찾은 단서를 심문에 내거나 지목에 쓰면 400 (오답 횟수에 넣지 않음)
- 오답 힌트는 못 찾은 단서의 이름 대신 조사할 구역을 알려 줌
- 구역이 없는 사건(예전 사건, 비상용 호텔 사건)은 `investigation: false`이고 처음부터 단서를 전부 공개
- 새로 만드는 사건은 AI가 구역을 3~5개로 나누고, `case_quality.py`가 개수·사람 이름·결정적 단서 몰림을 검사
- `GET /game/{game_id}/state`에 `found_evidence_ids`(찾은 단서 번호) 추가

### 증거 관문 (압박도 천장)
질문만으로는 압박도를 끝까지 올릴 수 없습니다. 그 용의자를 가리키는 **핵심 증거**를 내야 천장이 올라갑니다.

| 그 용의자에게 낸 핵심 증거 | 질문(+5)·관계없는 증거(+2)로 올릴 수 있는 최대치 |
|---|---|
| 0개 | 29 (여유) |
| 1개 | 59 (방어) |
| 2개 이상 | 89 (흔들림) |

- **헛짚기**: 그 사람과 상관없는 증거(압박도 표에도 없고 핵심 증거도 아님)를 처음 내밀면 압박도 **-5** (0 아래로는 안 내려감). 같은 증거를 다시 내밀면 변화 없음
  → 증거를 아무에게나 내밀기보다 단서 질문으로 먼저 떠보게 하려는 장치

- 핵심 증거: 범인은 자기를 가리키는 결정적·정황·모순 단서, 무고한 사람은 자기 비밀을 건드리는 미스리드·모순 단서
- 핵심 증거로 오르는 압박도는 천장과 상관없이 오릅니다. 그래서 90 이상(자백 구간)은 증거로만 갈 수 있습니다.
- 역할 표시가 없는 비상용 호텔 사건은 `evidence_effects`에 있는 단서를 핵심 증거로 봅니다.

### 심문 요청·응답에 추가된 칸
- 요청 `question_category` (선택): `관계` / `알리바이` / `감정` / `증거제시`. 없으면 서버가 증거 여부와 질문 문장으로 짐작합니다.
- 응답 `question_category`: 서버가 사용한 질문 종류
- 응답 `vital`: 바이탈 리딩 결과 `정상` / `긴장` / `거짓` / `신호 공백`
  - 범인은 알리바이·감정 질문에서 긴장하다가, 자기를 가리키는 증거 앞에서 `거짓`
  - 무고한 사람도 개인 비밀(미스리드·모순 단서)을 건드리면 `거짓` (레드헤링)
  - 사건 파일에 `"culprit_unaware": true`가 있으면 범인의 `거짓`이 `신호 공백`이 됩니다. (범인 본인도 기억 못 하는 사건용)
- 응답 `pressure_cap`: 지금 질문으로 올릴 수 있는 최대 압박도 (`GET /game/{game_id}/state`에도 있음)
- 응답 `need_evidence`: true면 질문으로는 더 못 올림 → 증거를 내야 다음 단계로 감

### 범인 지목 응답에 추가된 칸
`success`, `message`는 그대로이고 아래 칸이 추가됐습니다.
- `game_over`: 게임이 끝났는지 (정답이거나 3번 틀렸을 때 true)
- `wrong_count`, `remaining_chances`: 틀린 횟수, 남은 기회
- `rejected_suspects`: 기각된 용의자 번호 목록
- `hint`: 틀린 이유에 맞춘 힌트 (정답을 직접 말하지 않음)
- `grade`: 엔딩 등급. 정답일 때 틀린 횟수 0/1/2번 → A/B/C, 미해결 → D

> Unity는 `game_over`가 false면 `EndGame()`을 부르지 말아야 다시 도전할 수 있습니다.

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
