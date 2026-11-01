"""
질문 목록 모듈 (AI 호출 없음)

용의자마다 카테고리(관계 / 알리바이 / 감정)별 질문 목록을 만듭니다.
  1순위: 사건을 만들 때 AI가 함께 써 둔 그 용의자 맞춤 질문 (suspect["questions"])
  2순위: 서버의 질문 틀에 사건 정보(피해자 이름, 사망 추정 시각, 다른 용의자)를 채운 질문
게임 중에 AI가 질문을 만들지 않으므로 AI 호출이 늘지 않습니다.
"""
from game_rules import normalize_question

QUESTION_LIST_CATEGORIES = ("관계", "알리바이", "감정")   # 증거제시는 [증거 제시] 버튼으로 함
MAX_QUESTIONS_PER_CATEGORY = 6

# {victim_wa} = "서현우와" 처럼 받침에 맞는 조사가 붙은 이름
QUESTION_TEMPLATES = {
    "관계": [
        "{victim_wa}는 어떤 사이였습니까?",
        "{victim_eun} 어떤 사람이었습니까?",
        "{victim_wa} 마지막으로 이야기한 게 언제입니까?",
        "{other1_wa}는 어떤 사이입니까?",
        "{other2_wa}는 어떤 사이입니까?",
    ],
    "알리바이": [
        "사건 당시{time}에 어디에 있었습니까?",
        "그 시간에 무엇을 하고 있었습니까?",
        "그 시간에 당신을 본 사람이 있습니까?",
        "그날 밤 사건 현장 근처에 간 적이 있습니까?",
        "그날 언제 그곳을 떠났습니까?",
    ],
    "감정": [
        "{victim_eul} 원망한 적이 있습니까?",
        "{victim_wa} 크게 다툰 적이 있습니까?",
        "{victim_ege} 약점을 잡힌 적이 있습니까?",
        "{victim_eui} 죽음을 듣고 어떤 기분이 들었습니까?",
        "요즘 가장 두려운 게 무엇입니까?",
    ],
}


def _has_batchim(word: str) -> bool:
    last = word[-1] if word else ""
    return "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0


def _josa(word: str, without_batchim: str, with_batchim: str) -> str:
    """받침 유무에 맞는 조사를 붙임 (서현우와 / 박태준과)"""
    return word + (with_batchim if _has_batchim(word) else without_batchim)


def _person_name(text: str, default: str) -> str:
    """'서현우 (52세, 주임교수)' → '서현우'"""
    name = str(text or "").split("(")[0].strip()
    return name or default


def template_questions(game: dict, suspect_id: int) -> dict:
    """질문 틀에 사건 정보를 채움"""
    victim = _person_name(game.get("victim"), "피해자")
    others = [s["name"] for s_id, s in game["suspects"].items() if s_id != suspect_id] + ["다른 사람", "다른 사람"]
    time = str(game.get("time_of_death") or "").strip()
    values = {
        "victim_wa": _josa(victim, "와", "과"),
        "victim_eun": _josa(victim, "는", "은"),
        "victim_eul": _josa(victim, "를", "을"),
        "victim_ege": victim + "에게",
        "victim_eui": victim + "의",
        "other1_wa": _josa(others[0], "와", "과"),
        "other2_wa": _josa(others[1], "와", "과"),
        "time": f"({time})" if time else "",
    }
    return {category: [t.format(**values) for t in templates]
            for category, templates in QUESTION_TEMPLATES.items()}


def clue_questions(game: dict, evidence_ids: list) -> list:
    """
    찾은 단서마다 열리는 '단서 질문' (단서를 보여 주지 않고 말로 떠보기). 세 용의자 누구에게나 물을 수 있음
    1순위: 사건을 만들 때 AI가 단서마다 써 둔 질문, 2순위: 질문 틀
    [{"clue_id": "E01", "text": "..."}, ...]
    """
    result = []
    for e_id in evidence_ids:
        clue = game["evidence_db"].get(e_id)
        if not clue:
            continue
        text = str(clue.get("question") or "").strip() or f"「{clue.get('name', e_id)}」에 대해 들은 적이 있습니까?"
        result.append({"clue_id": e_id, "text": text})
    return result


def question_list(game: dict, suspect_id: int) -> list:
    """
    Unity에 보내는 한 용의자의 질문 목록
    [{"category": "관계", "questions": [...]}, ...]  (AI 맞춤 질문 먼저, 겹치는 질문은 한 번만)
    """
    ai_questions = game["suspects"][suspect_id].get("questions") or []
    templates = template_questions(game, suspect_id)
    result = []
    for category in QUESTION_LIST_CATEGORIES:
        picked, seen = [], set()
        candidates = [q.get("text", "") for q in ai_questions if q.get("category") == category] + templates[category]
        for text in candidates:
            key = normalize_question(text)
            if key and key not in seen:
                seen.add(key)
                picked.append(text.strip())
        result.append({"category": category, "questions": picked[:MAX_QUESTIONS_PER_CATEGORY]})
    return result
