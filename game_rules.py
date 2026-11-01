"""
게임 규칙 모듈 (AI 호출 없음)

- 질문 카테고리: 관계 / 알리바이 / 감정 / 증거제시
- 바이탈 리딩: 대답마다 정상 / 긴장 / 거짓 / 신호 공백 판정 (기획안 「마인드브레이크」의 레조넌스 고글)
- 범인 지목: 오답 기회, 기각된 용의자, 서버가 만드는 힌트, 엔딩 등급
- 증거 관문: 질문만으로 올릴 수 있는 압박도에 천장을 두고, 핵심 증거를 내야 천장이 올라감
- 현장 조사: 단서를 구역(area)별로 묶고, 구역을 조사해야 그 단서를 쓸 수 있음

판정은 사건의 진실(범인, 단서 역할)과 질문 종류만 보고 서버가 정합니다.
AI가 지어내는 값이 아니라서 같은 상황이면 항상 같은 결과가 나옵니다.
"""
import re
from typing import Optional

QUESTION_CATEGORIES = ("관계", "알리바이", "감정", "증거제시")

# 질문 문장으로 종류를 짐작할 때 쓰는 단어 (Unity가 종류를 보내지 않을 때만 사용)
CATEGORY_KEYWORDS = {
    "알리바이": ("어디", "몇 시", "시간", "그때", "당시", "알리바이", "무엇을 하", "뭘 하", "나온", "들어간"),
    "감정": ("미워", "원망", "싫", "화가", "죽이고 싶", "감정", "기분", "약점", "협박", "두려", "무서"),
    "관계": ("관계", "사이", "알게", "아는 사이", "어떤 사람", "친했", "피해자와", "상담"),
}

VITAL_STATES = ("정상", "긴장", "거짓", "신호 공백")

# 범인을 가리키는 단서 / 그 사람의 개인 비밀을 건드리는 단서
CULPRIT_CLUE_ROLES = ("결정적", "정황", "모순")
SECRET_CLUE_ROLES = ("미스리드", "모순")

MAX_WRONG_ACCUSATIONS = 3   # 3번 틀리면 미해결 엔딩
GRADE_BY_WRONG = {0: "A", 1: "B", 2: "C"}

# 그 사람에게 낸 핵심 증거가 0 / 1 / 2개 이상일 때 질문으로 올릴 수 있는 최대 압박도
# (말투 단계 0~29 여유 / 30~59 방어 / 60~89 흔들림 / 90~ 붕괴의 끝값. 90 이상은 증거로만)
PRESSURE_CAP_BY_KEY_CLUES = (29, 59, 89)


# ---------------------------------------------------------------------------
# 1. 질문 카테고리
# ---------------------------------------------------------------------------

def resolve_category(category: Optional[str], question: str, evidence_id: Optional[str]) -> str:
    """Unity가 보낸 종류가 있으면 그대로, 없으면 증거 여부와 질문 문장으로 짐작"""
    if category in QUESTION_CATEGORIES:
        return category
    if evidence_id:
        return "증거제시"
    for name, words in CATEGORY_KEYWORDS.items():
        if any(w in question for w in words):
            return name
    return "관계"


def normalize_question(question: str) -> str:
    """띄어쓰기·문장부호만 다른 질문은 같은 질문으로 봄 (반복 질문 판정·답변 재사용용)"""
    return re.sub(r"[\s?？!！.。,，~…]+", "", question)


# ---------------------------------------------------------------------------
# 1-2. 증거 관문 (압박도 천장)
# ---------------------------------------------------------------------------

def key_clues_for(game: dict, suspect_id: int) -> set:
    """
    그 사람을 가리키는 핵심 단서
    - 범인: 자기를 가리키는 결정적·정황·모순 단서
    - 무고한 사람: 자기 비밀을 건드리는 미스리드·모순 단서
    """
    roles = CULPRIT_CLUE_ROLES if suspect_id == game["culprit_id"] else SECRET_CLUE_ROLES
    keys = {e_id for e_id, e in game["evidence_db"].items()
            if e.get("related_suspect_id") == suspect_id and e.get("role") in roles}
    if not keys:
        # 역할 태그가 없는 사건(비상용 호텔 사건)은 압박도 표에 있는 단서를 핵심으로 봄
        effects = game["suspects"][suspect_id].get("evidence_effects", {})
        keys = {e_id for e_id, value in effects.items() if value > 0}
    return keys


def pressure_cap(game: dict, suspect_id: int) -> int:
    """지금 질문(과 관계없는 증거)으로 올릴 수 있는 최대 압박도"""
    presented = set(game["suspects"][suspect_id].get("presented_evidence", []))
    shown = len(key_clues_for(game, suspect_id) & presented)
    return PRESSURE_CAP_BY_KEY_CLUES[min(shown, len(PRESSURE_CAP_BY_KEY_CLUES) - 1)]


def raise_pressure(current: int, amount: int, cap: int) -> int:
    """천장까지만 올림. 핵심 증거로 이미 천장 위에 있으면 그대로"""
    if current >= cap:
        return current
    return min(current + amount, cap)


# ---------------------------------------------------------------------------
# 2. 바이탈 리딩
# ---------------------------------------------------------------------------

def judge_vital(game: dict, suspect_id: int, category: str, evidence_id: Optional[str],
                pressure: int, confessed: bool) -> str:
    """
    정상: 진실 / 긴장: 진실이나 불안 / 거짓: 숨기는 것이 있음 / 신호 공백: 기억 자체가 없음

    - 범인은 알리바이·감정에서 긴장하다가, 자기를 가리키는 증거 앞에서 거짓 반응
    - 무고한 사람도 개인 비밀(미스리드·모순 단서)을 건드리면 거짓 반응 → 레드헤링
    - 사건에 "culprit_unaware": true 가 있으면 범인은 거짓 대신 신호 공백 (범인 본인도 모르는 사건)
    """
    suspect = game["suspects"][suspect_id]
    is_culprit = suspect_id == game["culprit_id"]
    has_secret = bool(suspect.get("knowledge", {}).get("private"))

    if confessed:
        return "정상"   # 자백한 뒤에는 진실을 말함

    clue = game["evidence_db"].get(evidence_id) if evidence_id else None
    about_me = bool(clue) and clue.get("related_suspect_id") == suspect_id

    if is_culprit:
        if category == "증거제시":
            state = "거짓" if about_me and clue.get("role") in CULPRIT_CLUE_ROLES else "긴장"
        elif category == "알리바이":
            state = "긴장" if pressure < 60 else "거짓"
        elif category == "감정":
            state = "긴장" if pressure < 30 else "거짓"
        else:
            state = "정상"
        if state == "거짓" and game.get("culprit_unaware"):
            state = "신호 공백"
        return state

    # 무고한 사람
    if category == "증거제시":
        if about_me and clue.get("role") in SECRET_CLUE_ROLES:
            return "거짓"      # 살인과 무관한 개인 비밀을 숨김
        return "정상"
    if category == "감정":
        return "긴장" if pressure >= 30 or has_secret else "정상"
    if category == "관계":
        return "긴장" if has_secret and pressure >= 30 else "정상"
    return "정상"              # 알리바이는 사실


# ---------------------------------------------------------------------------
# 3. 범인 지목 (오답 기회 · 힌트 · 등급)
# ---------------------------------------------------------------------------

def new_accuse_state() -> dict:
    return {"wrong_count": 0, "rejected_suspects": [], "finished": False, "result": None}


def _hint_for_wrong(game: dict, suspect_id: int, evidence_id: str, found: Optional[list] = None) -> str:
    """틀린 이유에 맞춰 서버가 힌트를 만듦 (정답을 직접 말하지는 않음)"""
    culprit_id = game["culprit_id"]
    evidence_db = game["evidence_db"]
    name = game["suspects"].get(suspect_id, {}).get("name", f"용의자 {suspect_id}")

    if suspect_id != culprit_id:
        alibi_ids = [e_id for e_id, e in evidence_db.items()
                     if e.get("role") == "알리바이" and e.get("related_suspect_id") == suspect_id]
        if alibi_ids:
            clue = evidence_db[alibi_ids[0]]
            if found is not None and alibi_ids[0] not in found and clue.get("area"):
                # 아직 못 찾은 단서는 이름 대신 조사할 구역을 알려 줌
                return f"{name}의 알리바이를 뒷받침하는 단서가 있습니다. 「{clue['area']}」을(를) 조사해 보세요."
            return f"{name}의 알리바이를 뒷받침하는 단서가 있습니다. '{clue['name']}'를 다시 확인해 보세요."
        return f"{name}의 수상한 반응이 '어떤 질문'에서 나왔는지 다시 살펴보세요. 살인과 무관한 비밀일 수 있습니다."

    chosen = evidence_db.get(evidence_id)
    if chosen and chosen.get("related_suspect_id") == culprit_id:
        return "범인은 맞습니다. 하지만 그 단서만으로는 부족합니다. 범인만 가리키는 더 확실한 증거를 찾아보세요."
    return "범인은 맞습니다. 하지만 고른 단서가 이 사람과 직접 연결되지 않습니다."


def judge_accusation(game: dict, accuse_state: dict, suspect_id: int, evidence_id: str,
                     found: Optional[list] = None) -> dict:
    """
    범인 + 결정적 증거가 둘 다 맞으면 정답. 틀리면 기회가 남아 있는 한 다시 도전.
    결과 칸: success, message, game_over, wrong_count, remaining_chances, rejected_suspects, hint, grade
    found: 플레이어가 찾은 단서 ID 목록 (힌트에서 못 찾은 단서 이름을 말하지 않으려고 씀)
    """
    if accuse_state["finished"]:
        return {**accuse_state["result"], "message": "이미 끝난 게임입니다. 새 게임을 시작하세요."}

    correct = suspect_id == game["culprit_id"] and evidence_id == game["decisive_evidence_id"]

    if correct:
        grade = GRADE_BY_WRONG.get(accuse_state["wrong_count"], "C")
        result = {
            "success": True,
            "message": "진범 체포! 결정적 증거로 진범을 잡았습니다.",
            "game_over": True,
            "hint": "",
            "grade": grade,
        }
    else:
        accuse_state["wrong_count"] += 1
        if suspect_id != game["culprit_id"] and suspect_id not in accuse_state["rejected_suspects"]:
            accuse_state["rejected_suspects"].append(suspect_id)
        remaining = MAX_WRONG_ACCUSATIONS - accuse_state["wrong_count"]
        if remaining > 0:
            result = {
                "success": False,
                "message": f"기소 기각. 다시 추리하세요. (남은 기회 {remaining}번)",
                "game_over": False,
                "hint": _hint_for_wrong(game, suspect_id, evidence_id, found),
                "grade": "",
            }
        else:
            result = {
                "success": False,
                "message": "추리 실패. 사건은 미결로 남았습니다.",
                "game_over": True,
                "hint": "",
                "grade": "D",
            }

    result.update({
        "wrong_count": accuse_state["wrong_count"],
        "remaining_chances": max(MAX_WRONG_ACCUSATIONS - accuse_state["wrong_count"], 0),
        "rejected_suspects": list(accuse_state["rejected_suspects"]),
    })
    if result["game_over"]:
        accuse_state["finished"] = True
        accuse_state["result"] = dict(result)
    return result


# ---------------------------------------------------------------------------
# 4. 현장 조사 (구역별 단서 찾기)
# ---------------------------------------------------------------------------

def has_areas(game: dict) -> bool:
    """단서마다 구역(area)이 있는 사건만 조사 방식을 씀. 예전 사건은 처음부터 단서를 전부 공개"""
    clues = list(game["evidence_db"].values())
    return bool(clues) and all(str(e.get("area") or "").strip() for e in clues)


def new_investigation_state(game: dict) -> dict:
    """구역 목록(A1, A2 ... 단서에 처음 나온 순서)과 찾은 단서·조사한 구역 기록"""
    if not has_areas(game):
        return {"enabled": False, "areas": [], "found": list(game["evidence_db"]), "investigated": []}

    areas = []
    for e_id, e in game["evidence_db"].items():
        name = e["area"].strip()
        area = next((a for a in areas if a["name"] == name), None)
        if not area:
            area = {"area_id": f"A{len(areas) + 1}", "name": name, "evidence_ids": []}
            areas.append(area)
        area["evidence_ids"].append(e_id)
    return {"enabled": True, "areas": areas, "found": [], "investigated": []}


def public_areas(investigation: dict) -> list:
    """Unity에 보내는 구역 목록 (어떤 단서가 있는지는 숨김)"""
    return [{"area_id": a["area_id"], "name": a["name"],
             "investigated": a["area_id"] in investigation["investigated"]}
            for a in investigation["areas"]]


def investigate_area(investigation: dict, area_id: str) -> Optional[dict]:
    """구역을 조사해 그 구역의 단서를 찾음. 없는 구역이면 None"""
    area = next((a for a in investigation["areas"] if a["area_id"] == area_id), None)
    if not area:
        return None
    already = area_id in investigation["investigated"]
    if not already:
        investigation["investigated"].append(area_id)
    new_ids = [e_id for e_id in area["evidence_ids"] if e_id not in investigation["found"]]
    investigation["found"].extend(new_ids)
    return {"area": area, "already": already, "new_ids": new_ids}
