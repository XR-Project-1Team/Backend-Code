"""
사건 품질 검사기 (AI 담당 추가분)

validator.py는 '형식' (용의자 3명, 역할 태그 개수 등)을 봅니다.
이 파일은 형식은 맞지만 게임을 망치는 '내용' 문제를 규칙으로 잡습니다.
AI 검토(REVIEW_PROMPT)보다 먼저 돌리면 AI 호출 횟수도 아낄 수 있습니다.

사용:
    from case_quality import check_case_quality
    errors = check_case_quality(case)                 # 생성 직후 검사
    errors = check_case_quality(case, expected_culprit_id=3)  # 서버가 정한 범인 확인
"""
import re
from typing import Optional

ROLE_WORDS = ("결정적", "정황", "알리바이", "모순", "미스리드")
SPOILER_WORDS = ROLE_WORDS + ("범인", "진범", "무고한", "함정", "용의자 1", "용의자 2", "용의자 3")

# '자신이 범인'류 문장 (무고한 사람의 forbidden에 들어가면 안 됨)
CULPRIT_SELF_PATTERN = re.compile(r"(자신이|내가|제가)\s*범인")

# 용의자 맞춤 질문의 카테고리 (증거제시는 버튼으로 하므로 제외)
QUESTION_CATEGORIES = ("관계", "알리바이", "감정")

# 조사 구역 개수 규칙
MIN_AREAS, MAX_AREAS = 3, 5
MAX_CLUES_PER_AREA = 4

# 한국어 품질: 한글 음절이 아닌 이상한 조합 / 반복 오타 패턴 (가벼운 휴리스틱)
GARBLED_PATTERN = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]{2,}|[\u4e00-\u9fff]|[\u3040-\u30ff]")


def _texts_of_suspect(s: dict) -> str:
    k = s.get("knowledge", {})
    parts = [s.get("description", ""), s.get("alibi", ""), s.get("personality", "")]
    for key in ("public", "private", "forbidden"):
        parts += [str(x) for x in k.get(key, [])]
    return " ".join(parts)


def check_case_quality(case: dict, expected_culprit_id: Optional[int] = None) -> list[str]:
    errors: list[str] = []
    suspects = case.get("suspects", {})
    evidence_db = case.get("evidence_db", {})
    culprit_id = case.get("culprit_id")
    if culprit_id not in suspects:
        return ["범인 ID가 용의자 목록에 없어 품질 검사를 건너뜁니다."]
    culprit = suspects[culprit_id]
    culprit_name = culprit.get("name", "")
    innocent_ids = [i for i in suspects if i != culprit_id]

    # 1. 서버가 정한 범인과 AI가 만든 범인이 같은지 (범인이 항상 2번으로 쏠리는 문제 방지)
    if expected_culprit_id is not None and culprit_id != expected_culprit_id:
        errors.append(
            f"범인은 용의자 {expected_culprit_id}이어야 하는데 culprit_id가 {culprit_id}입니다."
        )

    # 2. 시작 압박도는 모두 0 (게임 시작부터 자백 직전이면 안 됨)
    for s_id, s in suspects.items():
        if s.get("pressure_level", 0) != 0:
            errors.append(
                f"용의자 {s_id}의 시작 압박도가 {s.get('pressure_level')}입니다. 모든 용의자는 0에서 시작해야 합니다."
            )

    # 3. 무고한 사람의 forbidden에 '자신이 범인이라는 사실'이 있으면 AI가 범인처럼 연기함
    for s_id in innocent_ids:
        for f in suspects[s_id].get("knowledge", {}).get("forbidden", []):
            if CULPRIT_SELF_PATTERN.search(str(f)):
                errors.append(
                    f"무고한 용의자 {s_id}의 forbidden에 '{f}'가 있습니다. 무고한 사람은 개인 비밀만 숨겨야 합니다."
                )

    # 4. 무고한 사람의 forbidden이 비어 있으면 심문할 거리가 없음
    for s_id in innocent_ids:
        if not suspects[s_id].get("knowledge", {}).get("forbidden"):
            errors.append(f"무고한 용의자 {s_id}의 forbidden(숨기는 개인 비밀)이 비어 있습니다.")

    # 5. 같은 문장이 private와 forbidden에 동시에 → 중압박에서 털어놓을지 숨길지 AI가 혼란
    for s_id, s in suspects.items():
        k = s.get("knowledge", {})
        overlap = {str(x).strip().rstrip(".") for x in k.get("private", [])} & {
            str(x).strip().rstrip(".") for x in k.get("forbidden", [])
        }
        for o in overlap:
            errors.append(f"용의자 {s_id}의 private와 forbidden에 같은 내용 '{o}'이(가) 있습니다.")

    # 6. 단서 이름·설명의 정답 노출
    for e_id, e in evidence_db.items():
        name, desc = str(e.get("name", "")), str(e.get("desc", ""))
        for w in SPOILER_WORDS:
            if w in desc:
                errors.append(f"단서 {e_id}의 설명에 '{w}'라는 단어가 있어 정답이 드러납니다.")
        if culprit_name and culprit_name in name:
            errors.append(f"단서 {e_id}의 이름에 범인 이름 '{culprit_name}'이(가) 들어 있습니다.")
        if culprit_name and culprit_name in desc and e.get("role") in ("결정적", "정황"):
            errors.append(
                f"{e.get('role')} 단서 {e_id}의 설명에 범인 이름 '{culprit_name}'이(가) 직접 적혀 있습니다. "
                "(고치는 법: '작가가 즐겨 쓰는 만년필'처럼 간접적으로 가리키기)"
            )

    # 7. 단서와 압박도 연결: 범인을 가리키는 단서는 범인의 evidence_effects에 있어야 함
    culprit_effects = culprit.get("evidence_effects", {})
    for e_id, e in evidence_db.items():
        related = e.get("related_suspect_id")
        if related == culprit_id and e.get("role") in ("결정적", "정황", "모순"):
            if e_id not in culprit_effects:
                errors.append(f"범인을 가리키는 단서 {e_id}가 범인의 evidence_effects에 없습니다.")
        if related in innocent_ids and e.get("role") in ("미스리드", "모순"):
            if e_id not in suspects[related].get("evidence_effects", {}):
                errors.append(
                    f"용의자 {related}를 의심하게 만드는 단서 {e_id}가 그 사람의 evidence_effects에 없습니다."
                )

    # 8. 단서가 가리키는 대상과 설명 속 인물이 다르면 역할 불일치 가능성
    for e_id, e in evidence_db.items():
        related = e.get("related_suspect_id")
        desc = str(e.get("desc", "")) + str(e.get("name", ""))
        mentioned = [i for i, s in suspects.items() if s.get("name") and s["name"] in desc]
        if mentioned and related not in mentioned:
            names = ", ".join(suspects[i]["name"] for i in mentioned)
            errors.append(
                f"단서 {e_id}는 용의자 {related}와 연결되어 있지만 설명에는 {names}만 등장합니다."
            )

    # 9. 무고한 사람의 최대 압박이 범인보다 크면 '진짜 범인'처럼 보임
    culprit_total = sum(culprit_effects.values())
    for s_id in innocent_ids:
        total = sum(suspects[s_id].get("evidence_effects", {}).values())
        if total >= culprit_total:
            errors.append(
                f"무고한 용의자 {s_id}의 증거 압박 합계({total})가 범인({culprit_total})보다 크거나 같습니다."
            )

    # 10. 공개 소개(description)에 범인 암시 단어
    for s_id, s in suspects.items():
        for w in ("범인", "살해", "죽였"):
            if w in s.get("description", ""):
                errors.append(f"용의자 {s_id}의 공개 소개에 '{w}'가 들어 있습니다.")

    # 11. 깨진 글자(자모 단독, 한자·일본어 섞임)
    all_text = " ".join(
        [case.get("title", ""), case.get("case_summary", "")]
        + [_texts_of_suspect(s) for s in suspects.values()]
        + [str(e.get("name", "")) + " " + str(e.get("desc", "")) for e in evidence_db.values()]
    )
    garbled = sorted(set(GARBLED_PATTERN.findall(all_text)))
    if garbled:
        errors.append(f"깨진 글자나 외국 문자가 섞여 있습니다: {', '.join(garbled[:5])}")

    # 12. 조사 구역(area): 3~5개, 구역당 단서 1~4개, 사람 이름 금지, 결정적 단서가 한 구역에 몰리면 안 됨
    areas: dict[str, list[str]] = {}
    for e_id, e in evidence_db.items():
        area = str(e.get("area") or "").strip()
        if not area:
            errors.append(f"단서 {e_id}에 조사 구역(area)이 없습니다.")
            continue
        areas.setdefault(area, []).append(e_id)
    if areas:
        if not MIN_AREAS <= len(areas) <= MAX_AREAS:
            errors.append(f"조사 구역이 {len(areas)}개입니다. {MIN_AREAS}~{MAX_AREAS}개여야 합니다.")
        for area, ids in areas.items():
            if len(ids) > MAX_CLUES_PER_AREA:
                errors.append(f"조사 구역 '{area}'에 단서가 {len(ids)}개입니다. 한 구역에 {MAX_CLUES_PER_AREA}개까지입니다.")
            for s in suspects.values():
                if s.get("name") and s["name"] in area:
                    errors.append(f"조사 구역 이름 '{area}'에 용의자 이름 '{s['name']}'이(가) 들어 있습니다.")
        decisive_areas = {str(e.get("area") or "").strip() for e in evidence_db.values() if e.get("role") == "결정적"}
        decisive_count = sum(1 for e in evidence_db.values() if e.get("role") == "결정적")
        if decisive_count >= 2 and len(decisive_areas) == 1:
            errors.append("결정적 단서가 모두 한 구역에 있습니다. 구역을 나눠야 조사하는 재미가 생깁니다.")

    # 13. 수사 브리핑: 게임 시작 화면에 그대로 나가므로 비어 있거나 정답을 흘리면 안 됨
    briefing = str(case.get("briefing") or "").strip()
    if not briefing:
        errors.append("수사 브리핑(briefing)이 비어 있습니다.")
    else:
        for w in SPOILER_WORDS:
            if w in briefing:
                errors.append(f"수사 브리핑에 '{w}'라는 단어가 있어 정답이 드러날 수 있습니다.")
        for s_id, s in suspects.items():
            if s.get("name") and s["name"] in briefing:
                errors.append(f"수사 브리핑에 용의자 {s_id}의 이름 '{s['name']}'이(가) 들어 있습니다.")

    # 14. 용의자 맞춤 질문: 없으면 질문 틀로 대신하므로 경고만. 정답·단서 이름을 흘리면 오류
    clue_names = [str(e.get("name", "")) for e in evidence_db.values() if e.get("name")]
    for s_id, s in suspects.items():
        questions = s.get("questions") or []
        if not questions:
            errors.append(f"[경고] 용의자 {s_id}에게 맞춤 질문(questions)이 없습니다. 질문 틀로 대신합니다.")
        for q in questions:
            text = str(q.get("text", ""))
            if q.get("category") not in QUESTION_CATEGORIES:
                errors.append(f"용의자 {s_id}의 질문 '{text}'의 카테고리 '{q.get('category')}'는 관계/알리바이/감정이 아닙니다.")
            for w in SPOILER_WORDS:
                if w in text:
                    errors.append(f"용의자 {s_id}의 질문 '{text}'에 '{w}'라는 단어가 있어 정답이 드러날 수 있습니다.")
            for name in clue_names:
                if name in text:
                    errors.append(f"용의자 {s_id}의 질문 '{text}'에 아직 못 찾은 단서 이름 '{name}'이(가) 들어 있습니다.")

    # 15. 단서 질문: 없으면 질문 틀로 대신하므로 경고만. 정답 노출 단어·범인 이름은 오류
    for e_id, e in evidence_db.items():
        text = str(e.get("question") or "").strip()
        if not text:
            errors.append(f"[경고] 단서 {e_id}에 단서 질문(question)이 없습니다. 질문 틀로 대신합니다.")
            continue
        for w in SPOILER_WORDS:
            if w in text:
                errors.append(f"단서 {e_id}의 질문 '{text}'에 '{w}'라는 단어가 있어 정답이 드러날 수 있습니다.")
        if culprit_name and culprit_name in text:
            errors.append(f"단서 {e_id}의 질문에 범인 이름 '{culprit_name}'이(가) 들어 있습니다.")

    # 16. 말투 정보 (persona.py가 쓰는 speech_style) - 없으면 경고만
    for s_id, s in suspects.items():
        if not s.get("speech_style"):
            errors.append(f"[경고] 용의자 {s_id}에게 speech_style(말투 설정)이 없습니다. 기본 말투로 대체됩니다.")

    return errors


def split_warnings(errors: list[str]) -> tuple[list[str], list[str]]:
    """[경고]로 시작하는 항목은 재생성 사유에서 뺍니다."""
    warnings = [e for e in errors if e.startswith("[경고]")]
    hard = [e for e in errors if not e.startswith("[경고]")]
    return hard, warnings
