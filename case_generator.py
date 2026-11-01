import os
import sys
import json
import random
import shutil
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from validator import validate_generated_case, CLUE_ROLE_LIMITS
from case_quality import check_case_quality, split_warnings
from usage_counter import counted_call

# .env 파일의 API 키를 불러옴
load_dotenv()

# 심문 AI와 같은 OpenRouter 키를 쓰되, 사건 생성 전용 모델을 따로 지정할 수 있음
client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
    timeout=120,      # 무료 모델이 멈춰 있을 때 무한정 기다리지 않도록 (초)
    max_retries=0,    # 자동 재시도를 끄면 AI 호출 횟수를 정확히 셀 수 있음 (재시도는 generate_case가 직접 함)
)
CASE_MODEL_NAME = os.getenv("CASE_LLM_MODEL", os.getenv("LLM_MODEL", "openrouter/free"))

# 검증을 통과한 사건이 저장되는 폴더
CASES_DIR = Path(__file__).parent / "cases"
# 개수 제한을 넘은 오래된 사건을 옮겨 두는 폴더 (게임에서는 쓰지 않음, 지우지 않고 보관)
OLD_CASES_DIR = CASES_DIR / "old"
MAX_ACTIVE_CASES = 10

MAX_ATTEMPTS = 4

# 매번 다른 사건이 나오도록 무작위로 섞어 줄 재료 (레고 블록)
CASE_TYPES = ["살인", "독살", "실종 후 사망", "추락사로 위장된 살인"]
PLACES = ["호텔", "산장", "미술관", "대학 연구실", "유람선", "고급 레스토랑", "작은 출판사", "시골 펜션"]

ROLE_RULES = "\n".join(
    f"    - {role}: {low}~{high}개" for role, (low, high) in CLUE_ROLE_LIMITS.items()
)

SYSTEM_PROMPT = f"""
당신은 추리게임의 '사건 설계 AI'입니다. 논리적으로 모순이 없는 사건 하나를 만듭니다.
반드시 한국어로 작성하고, 아래 JSON 구조로만 답하십시오. 설명 문장은 쓰지 마십시오.

[규칙]
1. 용의자는 정확히 3명이고 suspect_id는 1, 2, 3 입니다. 그중 1명만 범인입니다.
2. 단서는 9~12개이고 evidence_id는 "E01"부터 차례대로 붙입니다.
3. 단서마다 role(역할 태그)을 하나 붙입니다. 개수 규칙:
{ROLE_RULES}
   - 결정적: 범인만 가리키는 단서 (related_suspect_id = 범인)
   - 정황: 범인 쪽으로 기울게 하는 단서 (related_suspect_id = 범인)
   - 알리바이: 무고한 용의자의 결백 증명. 무고한 2명에게 1개씩 (related_suspect_id = 그 무고한 사람)
   - 모순: 누군가의 거짓 진술을 반박. 최소 1개는 범인의 알리바이를 깨야 함
   - 미스리드: 무고한 사람을 의심하게 만드는 함정 (related_suspect_id = 무고한 사람)
4. decisive_evidence_id는 role이 "결정적"인 단서 중 하나입니다.
5. 범인의 evidence_effects에서 decisive_evidence_id의 값은 30~45입니다.
6. evidence_effects는 그 용의자를 압박하는 단서 ID와 압박도 증가량(5~45)입니다.
7. 범인의 forbidden에는 반드시 "자신이 범인이라는 사실"을 넣습니다.
   무고한 용의자의 forbidden에는 범인 관련 문장을 넣지 말고, 그 사람이 숨기고 싶은 개인 비밀을 넣습니다.
8. description은 플레이어에게 공개되는 짧은 소개(직업 + 진술)이며 범인을 암시하지 않습니다.
9. 단서의 desc는 플레이어가 보는 설명이며 role 이름을 직접 쓰지 않습니다.
10. 단서의 name과 desc에는 "결정적", "정황", "알리바이", "모순", "미스리드", "범인" 같은 단어를 쓰지 않습니다.
    단서 이름은 물건이나 기록의 이름만 씁니다. (나쁜 예: "지민재의 알리바이" / 좋은 예: "주방 출입 기록")
11. 단서 설명에 범인의 이름을 직접 쓰지 않습니다. 플레이어가 심문과 증거 조합으로 범인을 추리해야 합니다.
12. 단서의 desc는 role과 맞아야 합니다. 정황·결정적 단서가 오히려 범인의 알리바이를 뒷받침하면 안 됩니다.
13. 자연스럽고 맞춤법이 맞는 한국어로 씁니다.
14. culprit_id는 사용자가 지정한 번호를 그대로 씁니다. (예시 JSON의 번호를 따라 하지 않음)
15. 모든 용의자의 pressure_level은 0입니다.
16. 단서 이름에는 사람 이름을 넣지 않습니다. 결정적·정황 단서 설명에도 범인 이름을 직접 쓰지 않고 직업·소지품·습관으로 간접적으로 가리킵니다.
17. 범인을 가리키는 결정적·정황·모순 단서는 모두 범인의 evidence_effects에 넣고,
    무고한 사람을 의심하게 만드는 미스리드·모순 단서는 그 사람의 evidence_effects에 넣습니다.
18. 세 용의자의 speech_style은 서로 확실히 다르게 만듭니다. (예: 격식체 냉정형 / 반말 섞인 다혈질형 / 말줄임표 많은 소심형)

[JSON 구조]
{{
  "title": "사건 제목",
  "case_summary": "플레이어에게 보여 줄 사건 개요 1~2문장",
  "victim": "피해자 이름과 신분",
  "location": "사건 장소",
  "time_of_death": "사망 추정 시각",
  "truth": "실제로 무슨 일이 있었는지 (플레이어에게 비공개)",
  "culprit_id": 1,
  "decisive_evidence_id": "E01",
  "suspects": [
    {{
      "suspect_id": 1,
      "name": "이름",
      "job": "직업 또는 피해자와의 관계",
      "personality": "성격",
      "speech_style": {{
        "honorific": "격식체 존댓말 / 해요체 / 반말 섞임 중 하나와 설명",
        "sentence": "문장 길이와 리듬",
        "habit": "자주 쓰는 말버릇",
        "evasion": "곤란한 질문을 피하는 방식",
        "under_pressure": "압박받을 때 말투 변화",
        "examples": ["이 사람이 할 법한 대사 1", "대사 2"]
      }},
      "description": "공개 소개",
      "alibi": "본인이 주장하는 알리바이",
      "public": ["물어보면 말해 주는 정보"],
      "private": ["숨기는 비밀"],
      "forbidden": ["절대 말하면 안 되는 정보"],
      "evidence_effects": {{"E03": 20}},
      "pressure_level": 0
    }}
  ],
  "evidences": [
    {{
      "evidence_id": "E01",
      "name": "단서 이름",
      "desc": "단서 설명",
      "found_at": "발견 장소",
      "role": "결정적",
      "related_suspect_id": 1
    }}
  ]
}}
"""


# 규칙 검사기가 못 잡는 '이야기 품질'을 보는 검토 AI의 지시문
REVIEW_PROMPT = """
당신은 추리게임의 '사건 검토 AI'입니다. 다른 AI가 만든 사건을 읽고 게임을 망칠 만한 심각한 문제만 찾습니다.
입력은 두 부분입니다.
- player_view: 플레이어가 실제로 보는 공개 정보 (사건 개요, 용의자 소개, 단서 이름·설명)
- answer_sheet: 플레이어에게 숨겨진 정답지 (범인, 진실, 단서 역할, 용의자 비밀). 정답지에 범인 정보가 있는 것은 정상입니다.

[검토 기준]
1. 정답 노출: player_view만 읽고도 추리 없이 범인을 확신할 수 있는가? (예: 단서 이름·설명에 범인 이름과 범행이 함께 적힘)
2. 역할 불일치: 단서 설명이 answer_sheet의 role과 맞지 않는가?
   (예: 정황·결정적 단서가 오히려 범인의 결백을 뒷받침함, 알리바이 단서가 그 사람을 의심하게 만듦)
   ※ 모순 단서가 누군가의 알리바이와 부딪히는 것은 의도된 설계이므로 문제가 아닙니다.
3. 사실 모순: 의도되지 않은 시간·장소·인물 관계 충돌이 있는가?
4. 한국어: 뜻이 통하지 않는 단어, 외국어가 섞인 단어가 있는가?

사소한 취향 문제는 적지 마십시오. 문제는 최대 5개, 단서 ID나 용의자 번호를 붙여 한 문장씩 씁니다.
반드시 아래 JSON으로만 답하십시오. problems는 문자열 목록입니다.
{"pass": true, "problems": []}
"""


def _extract_json(text: str) -> dict:
    """AI 응답에서 JSON 부분만 꺼냅니다. (```json 같은 표시가 섞여 와도 처리)"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON을 찾을 수 없습니다.")
    return json.loads(text[start:end + 1])


def to_server_truth(raw: dict) -> dict:
    """AI가 만든 목록 형태의 사건을 서버가 쓰는 딕셔너리 형태로 바꿉니다."""
    suspects = {}
    for s in raw.get("suspects", []):
        suspect_id = int(s["suspect_id"])
        suspects[suspect_id] = {
            "name": s.get("name", ""),
            "job": s.get("job", ""),
            "personality": s.get("personality", ""),
            "speech_style": s.get("speech_style") or {},
            "description": s.get("description", ""),
            "alibi": s.get("alibi", ""),
            "knowledge": {
                "public": s.get("public", []),
                "private": s.get("private", []),
                "forbidden": s.get("forbidden", []),
            },
            "evidence_effects": {
                str(e_id): v for e_id, v in (s.get("evidence_effects") or {}).items()
            },
            "pressure_level": s.get("pressure_level", 0),
        }

    evidence_db = {}
    for e in raw.get("evidences", []):
        related = e.get("related_suspect_id")
        evidence_db[str(e["evidence_id"])] = {
            "name": e.get("name", ""),
            "desc": e.get("desc", ""),
            "found_at": e.get("found_at", ""),
            "role": e.get("role", ""),
            "related_suspect_id": int(related) if related is not None else None,
        }

    return {
        "title": raw.get("title", ""),
        "case_summary": raw.get("case_summary", ""),
        "victim": raw.get("victim", ""),
        "location": raw.get("location", ""),
        "time_of_death": raw.get("time_of_death", ""),
        "truth": raw.get("truth", ""),
        "culprit_id": int(raw.get("culprit_id", 0)),
        "decisive_evidence_id": str(raw.get("decisive_evidence_id", "")),
        "suspects": suspects,
        "evidence_db": evidence_db,
    }


def _call_ai(messages: list, temperature: float = 0.9, kind: str = "사건 생성") -> str:
    # 호출할 때마다 usage_counter가 횟수를 기록함
    # 사건 JSON은 길어서(약 4천~8천 토큰) 모델 기본 출력 한도에 걸리면 중간에 잘림 → 한도를 직접 지정
    max_tokens = int(os.getenv("CASE_MAX_TOKENS", "16000"))
    try:
        response = counted_call(kind, lambda: client.chat.completions.create(
            model=CASE_MODEL_NAME,
            response_format={"type": "json_object"},
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ))
    except Exception:
        # JSON 모드를 지원하지 않는 모델이면 일반 모드로 한 번 더 시도
        response = counted_call(kind, lambda: client.chat.completions.create(
            model=CASE_MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ))
    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        # 잘린 JSON을 파싱하면 'Expecting , delimiter' 같은 알기 어려운 오류가 나므로 원인을 직접 알려 줌
        raise ValueError("AI 응답이 출력 한도에서 잘렸습니다. (.env의 CASE_MAX_TOKENS를 늘리거나 단서 설명을 짧게)")
    return choice.message.content or ""


def review_case(case: dict) -> list[str] | None:
    """
    검토 AI가 사건의 이야기 문제를 찾습니다.
    문제 목록을 반환하고, 문제가 없으면 빈 리스트,
    검토 AI 호출 자체가 실패하면 None을 반환합니다.
    """
    # 플레이어가 보는 정보와 숨겨진 정답지를 나눠서 보여 줌
    review_input = {
        "player_view": {
            "case_summary": case["case_summary"],
            "suspects": {s_id: {"name": s["name"], "description": s["description"]}
                         for s_id, s in case["suspects"].items()},
            "clues": {e_id: {"name": e["name"], "desc": e["desc"]}
                      for e_id, e in case["evidence_db"].items()},
        },
        "answer_sheet": {
            "culprit_id": case["culprit_id"],
            "truth": case.get("truth", ""),
            "suspects": {s_id: {"alibi": s["alibi"], "private": s["knowledge"]["private"]}
                         for s_id, s in case["suspects"].items()},
            "clue_roles": {e_id: {"role": e["role"], "related_suspect_id": e["related_suspect_id"]}
                           for e_id, e in case["evidence_db"].items()},
        },
    }
    case_text = json.dumps(review_input, ensure_ascii=False, default=str)
    try:
        content = _call_ai(
            [
                {"role": "system", "content": REVIEW_PROMPT},
                {"role": "user", "content": case_text},
            ],
            temperature=0.2,
            kind="사건 검토",
        )
        result = _extract_json(content)
    except Exception:
        return None

    problems = [str(p) for p in result.get("problems", []) if str(p).strip()]
    if result.get("pass") is True and not problems:
        return []
    return problems or ["검토 AI가 통과시키지 않았지만 이유를 적지 않았습니다."]


def generate_case(case_type: str | None = None, place: str | None = None,
                  culprit_id: int | None = None) -> dict:
    """
    AI로 사건을 만들고 두 단계로 확인합니다.
      1단계 규칙 검사기: 용의자 수, 단서 역할 태그 등 (실패하면 반드시 다시 생성)
      2단계 검토 AI: 정답 노출, 역할 불일치, 모순, 어색한 한국어
    문제가 있으면 오류 목록을 생성 AI에게 돌려주고 고치게 합니다. (최대 MAX_ATTEMPTS번)
    끝까지 검토를 통과하지 못하면, 규칙은 통과한 가장 최근 사건에 검토 지적을 review_notes로 붙여 저장합니다.
    결과: {"success", "case", "file", "attempts"} 형태의 딕셔너리
    """
    case_type = case_type or random.choice(CASE_TYPES)
    place = place or random.choice(PLACES)
    # 범인 번호는 서버가 무작위로 정함 (AI에게 맡기면 예시 JSON을 따라 거의 항상 2번이 범인이 됨)
    culprit_id = culprit_id or random.choice([1, 2, 3])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"사건 유형: {case_type}\n장소: {place}\n"
                                    f"범인: suspect_id {culprit_id}번 (culprit_id = {culprit_id})\n"
                                    "위 조건으로 새 사건을 만들어 주십시오."},
    ]
    attempts = []
    backup = None   # 규칙은 통과했지만 검토 지적이 남은 가장 최근 사건 (예비용)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content = _call_ai(messages)
            case = to_server_truth(_extract_json(content))
            errors = validate_generated_case(case)
            if not errors:
                # 형식이 맞으면 내용 품질 검사 (AI 호출 없음). [경고]는 재생성 사유에서 제외
                errors, _warnings = split_warnings(check_case_quality(case, expected_culprit_id=culprit_id))
        except Exception as e:
            content = ""
            case = None
            errors = [f"AI 응답 처리 실패: {e}"]

        # 규칙 검사를 통과한 사건만 검토 AI에게 보냄
        review = "규칙 검사 실패로 건너뜀"
        if not errors:
            problems = review_case(case)
            if problems is None:
                review = "검토 AI 호출 실패로 건너뜀"
            elif not problems:
                review = "통과"
            else:
                review = f"문제 {len(problems)}개"
                backup = (case, problems)
                errors = [f"[AI 검토] {p}" for p in problems]

        attempts.append({"attempt": attempt, "errors": errors, "review": review})

        if not errors:
            file_path = save_case(case)
            return {"success": True, "case": case, "file": file_path.name, "attempts": attempts}

        # 검사기·검토 AI가 찾은 문제를 생성 AI에게 알려 주고 고치게 함
        if content:
            messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": "검사에서 아래 문제가 나왔습니다. 모두 고쳐서 전체 JSON을 다시 보내 주십시오.\n- "
                       + "\n- ".join(errors),
        })

    # 끝까지 완벽한 사건이 없으면, 규칙은 지킨 예비 사건을 검토 지적과 함께 저장
    if backup:
        case, problems = backup
        case["review_notes"] = problems
        file_path = save_case(case)
        return {"success": True, "case": case, "file": file_path.name, "attempts": attempts}

    return {"success": False, "case": None, "file": None, "attempts": attempts}


def save_case(case: dict) -> Path:
    CASES_DIR.mkdir(exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    file_path = CASES_DIR / f"case_{stamp}.json"
    number = 2
    # 같은 초에 저장해도 덮어쓰지 않도록 (old 폴더로 옮긴 파일 이름과도 겹치지 않게)
    while file_path.exists() or (OLD_CASES_DIR / file_path.name).exists():
        file_path = CASES_DIR / f"case_{stamp}_{number:02d}.json"
        number += 1
    file_path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    archive_old_cases()
    return file_path


def archive_old_cases() -> list[str]:
    """사건이 MAX_ACTIVE_CASES개를 넘으면 오래된 것부터 cases/old 폴더로 옮깁니다. (삭제하지 않음)"""
    files = list_case_files()   # 파일 이름의 날짜·시각 순서 = 오래된 순서
    moved = []
    if len(files) <= MAX_ACTIVE_CASES:
        return moved

    OLD_CASES_DIR.mkdir(exist_ok=True)
    for file_path in files[:len(files) - MAX_ACTIVE_CASES]:
        target = OLD_CASES_DIR / file_path.name
        number = 2
        while target.exists():   # old 폴더의 파일을 덮어쓰지 않음
            target = OLD_CASES_DIR / f"{file_path.stem}_old{number}.json"
            number += 1
        shutil.move(str(file_path), str(target))
        moved.append(file_path.name)
    return moved


def mark_played(file_path: Path) -> None:
    """게임에 한 번 쓰인 사건에 '플레이함' 표시를 남깁니다."""
    try:
        case = json.loads(file_path.read_text(encoding="utf-8"))
        case["played"] = True
        file_path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass   # 표시를 못 남겨도 게임 진행에는 문제 없음


def load_case(file_path: Path) -> dict:
    """저장된 사건을 읽습니다. JSON은 키가 문자열이라 용의자 ID를 숫자로 되돌립니다."""
    case = json.loads(file_path.read_text(encoding="utf-8"))
    case["suspects"] = {int(s_id): s for s_id, s in case["suspects"].items()}
    return case


def list_case_files() -> list[Path]:
    if not CASES_DIR.exists():
        return []
    return sorted(CASES_DIR.glob("case_*.json"))


# 터미널에서 직접 실행하면 사건을 하나 만들어 결과를 보여 줍니다.
#   python case_generator.py
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"사건 생성 중... (모델: {CASE_MODEL_NAME})")
    result = generate_case()

    for a in result["attempts"]:
        status = "통과" if not a["errors"] else f"문제 {len(a['errors'])}개"
        print(f"  시도 {a['attempt']}: {status} (AI 검토: {a['review']})")
        for error in a["errors"]:
            print(f"    - {error}")

    if result["success"]:
        case = result["case"]
        print(f"\n✅ 저장됨: cases/{result['file']}")
        for note in case.get("review_notes", []):
            print(f"  ⚠ 남은 검토 지적: {note}")
        print(f"제목: {case['title']}")
        print(f"개요: {case['case_summary']}")
        for s_id, s in case["suspects"].items():
            print(f"  용의자 {s_id}: {s['name']} ({s['job']})")
        print(f"단서 {len(case['evidence_db'])}개")
    else:
        print("\n❌ 사건 생성 실패 (서버는 기본 호텔 사건을 사용합니다)")
