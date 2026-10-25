
from validator import validate_case, validate_generated_case


def make_valid_case():
    return {
        "culprit_id": 2,
        "decisive_evidence_id": "E01",
        "suspects": {
            1: {
                "name": "박민수",
                "alibi": "23시에는 로비에 있었다.",
                "knowledge": {
                    "public": [],
                    "private": [],
                    "forbidden": [],
                },
                "evidence_effects": {
                    "E02": 35,
                    "E03": 10,
                },
                "pressure_level": 10,
            },
            2: {
                "name": "이지은",
                "alibi": "23시에는 카페테리아에 있었다.",
                "knowledge": {
                    "public": [],
                    "private": [],
                    "forbidden": [],
                },
                "evidence_effects": {
                    "E01": 40,
                    "E02": 5,
                },
                "pressure_level": 0,
            },
        },
        "evidence_db": {
            "E01": {"name": "깨진 손목시계"},
            "E02": {"name": "도난 장부"},
            "E03": {"name": "카페테리아 CCTV"},
        },
    }


# 테스트 1: 정상적인 사건은 통과해야 합니다.
case_data = make_valid_case()
errors = validate_case(case_data)

assert errors == [], f"정상 사건이 실패했습니다: {errors}"
print("테스트 1 통과: 정상 사건")


# 테스트 2: 존재하지 않는 범인은 오류가 나야 합니다.
case_data = make_valid_case()
case_data["culprit_id"] = 99

errors = validate_case(case_data)

assert any("범인 ID" in error for error in errors), errors
print("테스트 2 통과: 잘못된 범인 ID")


# 테스트 3: 존재하지 않는 결정적 증거는 오류가 나야 합니다.
case_data = make_valid_case()
case_data["decisive_evidence_id"] = "E99"

errors = validate_case(case_data)

assert any("결정적 증거" in error for error in errors), errors
print("테스트 3 통과: 잘못된 결정적 증거")


# 테스트 4: 압박도가 100을 넘으면 오류가 나야 합니다.
case_data = make_valid_case()
case_data["suspects"][2]["pressure_level"] = 120

errors = validate_case(case_data)

assert any("압박도" in error for error in errors), errors
print("테스트 4 통과: 잘못된 압박도")


# 테스트 5: 존재하지 않는 증거 효과 ID는 오류가 나야 합니다.
case_data = make_valid_case()
case_data["suspects"][2]["evidence_effects"]["E99"] = 20

errors = validate_case(case_data)

assert any("E99" in error for error in errors), errors
print("테스트 5 통과: 잘못된 증거 효과")


# --- AI 생성 사건 검사 테스트 ---
def make_suspect(name, job, alibi, effects, forbidden=None):
    return {
        "name": name,
        "job": job,
        "personality": "차분하고 말이 짧다.",
        "description": f"{job}. {alibi}",
        "alibi": alibi,
        "knowledge": {
            "public": ["피해자와 아는 사이다."],
            "private": ["말하고 싶지 않은 비밀이 있다."],
            "forbidden": forbidden or [],
        },
        "evidence_effects": effects,
        "pressure_level": 0,
    }


def make_clue(name, role, related_suspect_id):
    return {
        "name": name,
        "desc": f"{name}에 대한 설명",
        "found_at": "서재",
        "role": role,
        "related_suspect_id": related_suspect_id,
    }


def make_valid_generated_case():
    return {
        "title": "별장 서재 살인사건",
        "case_summary": "별장 서재에서 주인이 숨진 채 발견되었다.",
        "culprit_id": 3,
        "decisive_evidence_id": "E01",
        "suspects": {
            1: make_suspect("가", "정원사", "정원에 있었다.", {"E06": 30}),
            2: make_suspect("나", "요리사", "주방에 있었다.", {"E07": 30}),
            3: make_suspect(
                "다", "조카", "방에서 자고 있었다.",
                {"E01": 40, "E02": 35, "E05": 20},
                forbidden=["자신이 범인이라는 사실"],
            ),
        },
        "evidence_db": {
            "E01": make_clue("피 묻은 장갑", "결정적", 3),
            "E02": make_clue("찢어진 편지", "결정적", 3),
            "E03": make_clue("유산 서류", "정황", 3),
            "E04": make_clue("다툼 목격담", "정황", 3),
            "E05": make_clue("젖은 신발", "모순", 3),
            "E06": make_clue("정원 CCTV", "알리바이", 1),
            "E07": make_clue("주방 영수증", "알리바이", 2),
            "E08": make_clue("깨진 시계", "모순", 1),
            "E09": make_clue("정원사의 칼", "미스리드", 1),
        },
    }


# 테스트 6: 규칙을 지킨 생성 사건은 통과해야 합니다.
errors = validate_generated_case(make_valid_generated_case())

assert errors == [], f"정상 생성 사건이 실패했습니다: {errors}"
print("테스트 6 통과: 정상 생성 사건")


# 테스트 7: 용의자가 3명이 아니면 오류가 나야 합니다.
case_data = make_valid_generated_case()
del case_data["suspects"][1]

errors = validate_generated_case(case_data)

assert any("3명" in error for error in errors), errors
print("테스트 7 통과: 용의자 수 부족")


# 테스트 8: 결정적 단서가 무고한 사람을 가리키면 오류가 나야 합니다.
case_data = make_valid_generated_case()
case_data["evidence_db"]["E02"]["related_suspect_id"] = 1

errors = validate_generated_case(case_data)

assert any("E02" in error and "범인이 아닌" in error for error in errors), errors
print("테스트 8 통과: 결정적 단서가 무고한 사람을 가리킴")


# 테스트 9: 범인의 진술을 깨는 모순 단서가 없으면 오류가 나야 합니다.
case_data = make_valid_generated_case()
case_data["evidence_db"]["E05"]["related_suspect_id"] = 2

errors = validate_generated_case(case_data)

assert any("모순 단서가 없습니다" in error for error in errors), errors
print("테스트 9 통과: 범인 모순 단서 없음")


# 테스트 10: 범인의 발설 금지 정보가 비어 있으면 오류가 나야 합니다.
case_data = make_valid_generated_case()
case_data["suspects"][3]["knowledge"]["forbidden"] = []

errors = validate_generated_case(case_data)

assert any("forbidden" in error for error in errors), errors
print("테스트 10 통과: 범인 발설 금지 정보 없음")


# 테스트 11: 잘못된 역할 태그는 오류가 나야 합니다.
case_data = make_valid_generated_case()
case_data["evidence_db"]["E09"]["role"] = "함정"

errors = validate_generated_case(case_data)

assert any("역할 태그" in error for error in errors), errors
print("테스트 11 통과: 잘못된 역할 태그")


# 테스트 12: 단서 이름에 역할이 드러나면 오류가 나야 합니다.
case_data = make_valid_generated_case()
case_data["evidence_db"]["E06"]["name"] = "정원사의 알리바이"

errors = validate_generated_case(case_data)

assert any("E06" in error and "드러나" in error for error in errors), errors
print("테스트 12 통과: 단서 이름에 역할 노출")


print("\n모든 Validator 테스트를 통과했습니다.")
