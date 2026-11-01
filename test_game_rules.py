"""
게임 규칙 테스트 (AI 호출 없음)
질문 카테고리 · 바이탈 리딩 · 범인 지목(오답 기회·힌트·등급)

    python test_game_rules.py
"""
import os
import sys
import copy
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
os.environ["AUTO_GENERATE"] = "off"   # 테스트 중 사건 자동 생성(AI 호출) 방지

from fastapi.testclient import TestClient
from case_generator import load_case
from game_rules import (resolve_category, judge_vital, judge_accusation,
                        new_accuse_state, MAX_WRONG_ACCUSATIONS,
                        normalize_question, key_clues_for, pressure_cap, raise_pressure,
                        new_investigation_state, investigate_area)
from case_quality import check_case_quality, split_warnings
from question_bank import question_list, clue_questions, MAX_QUESTIONS_PER_CATEGORY
from interrogation import check_dialogue
import main

CASE_FILE = "case_20261026_165921.json"   # 범인 1번, 결정적 증거 E01
CASE = load_case(Path(__file__).parent / "cases" / CASE_FILE)


def fresh_case():
    return copy.deepcopy(CASE)


# 테스트 1: 질문 카테고리
assert resolve_category("감정", "아무 질문", None) == "감정"
assert resolve_category(None, "아무 질문", "E01") == "증거제시"
assert resolve_category(None, "사건 당시 어디에 있었습니까?", None) == "알리바이"
assert resolve_category(None, "피해자와는 어떤 관계였습니까?", None) == "관계"
assert resolve_category(None, "피해자를 미워했나요?", None) == "감정"
assert resolve_category("이상한값", "그냥 질문", None) == "관계"
print("테스트 1 통과: 질문 카테고리")

# 테스트 2: 바이탈 - 범인
c = fresh_case()
assert judge_vital(c, 1, "증거제시", "E01", 40, False) == "거짓"      # 자기를 가리키는 결정적 단서
assert judge_vital(c, 1, "증거제시", "E05", 40, False) == "긴장"      # 남의 알리바이 단서
assert judge_vital(c, 1, "알리바이", None, 10, False) == "긴장"
assert judge_vital(c, 1, "알리바이", None, 70, False) == "거짓"
assert judge_vital(c, 1, "관계", None, 10, False) == "정상"
assert judge_vital(c, 1, "증거제시", "E01", 95, True) == "정상"       # 자백 뒤에는 진실
print("테스트 2 통과: 바이탈 리딩 (범인)")

# 테스트 3: 바이탈 - 무고한 사람 (레드헤링)
assert judge_vital(c, 2, "증거제시", "E04", 10, False) == "거짓"      # 미스리드 = 개인 비밀
assert judge_vital(c, 2, "증거제시", "E05", 10, False) == "정상"      # 자기 알리바이 단서
assert judge_vital(c, 3, "증거제시", "E07", 10, False) == "거짓"      # 모순 = 개인 비밀
assert judge_vital(c, 2, "알리바이", None, 80, False) == "정상"       # 알리바이는 사실
print("테스트 3 통과: 바이탈 리딩 (무고한 사람)")

# 테스트 4: 범인도 모르는 범인 (culprit_unaware) → 신호 공백
c = fresh_case()
c["culprit_unaware"] = True
assert judge_vital(c, 1, "증거제시", "E01", 40, False) == "신호 공백"
assert judge_vital(c, 1, "알리바이", None, 10, False) == "긴장"
print("테스트 4 통과: 신호 공백")

# 테스트 5: 오답 → 힌트 → 정답, 등급 B
c = fresh_case()
state = new_accuse_state()
r = judge_accusation(c, state, 2, "E04")
assert not r["success"] and not r["game_over"], r
assert r["remaining_chances"] == MAX_WRONG_ACCUSATIONS - 1 and r["rejected_suspects"] == [2], r
assert "문서 파쇄실 출입 기록표" in r["hint"], r["hint"]          # 2번의 알리바이 단서로 힌트
r = judge_accusation(c, state, 1, "E01")
assert r["success"] and r["game_over"] and r["grade"] == "B", r
print("테스트 5 통과: 오답 뒤 정답 (등급 B)")

# 테스트 6: 범인은 맞고 증거가 틀림 → 기각 목록에는 안 들어감
c = fresh_case()
state = new_accuse_state()
r = judge_accusation(c, state, 1, "E02")
assert not r["success"] and r["rejected_suspects"] == [], r
assert "범인은 맞습니다" in r["hint"], r["hint"]
print("테스트 6 통과: 증거만 틀림")

# 테스트 7: 3번 틀리면 미해결 엔딩 D, 그 뒤 지목은 막힘
c = fresh_case()
state = new_accuse_state()
for _ in range(MAX_WRONG_ACCUSATIONS):
    r = judge_accusation(c, state, 3, "E07")
assert r["game_over"] and r["grade"] == "D" and r["remaining_chances"] == 0, r
r = judge_accusation(c, state, 1, "E01")
assert not r["success"] and "이미 끝난" in r["message"], r
print("테스트 7 통과: 미해결 엔딩")

# 테스트 8: 서버 API로 지목 (AI 호출 없는 경로) - 유니티가 쓰던 칸도 그대로 있는지
main.mark_played = lambda file_path: None   # 테스트가 실제 사건 파일에 '플레이함'을 남기지 않게
api = TestClient(main.app)


def investigate_all(game_id, areas):
    """모든 구역을 조사해 단서를 다 찾음 (조사와 상관없는 테스트용)"""
    for a in areas:
        api.post("/game/investigate", json={"game_id": game_id, "area_id": a["area_id"]})


start = api.post(f"/game/start?case_file={CASE_FILE}").json()
assert len(start["suspects"]) == 3 and start["game_id"]
investigate_all(start["game_id"], start["areas"])
r = api.post("/game/accuse", json={"game_id": start["game_id"], "suspect_id": 3,
                                   "decisive_evidence_id": "E07"}).json()
assert {"success", "message"} <= r.keys() and r["success"] is False and r["game_over"] is False, r
r = api.post("/game/accuse", json={"game_id": start["game_id"], "suspect_id": 1,
                                   "decisive_evidence_id": "E01"}).json()
assert r["success"] is True and r["grade"] == "B", r
assert api.post("/game/accuse", json={"game_id": start["game_id"], "suspect_id": 9,
                                      "decisive_evidence_id": "E01"}).status_code == 404
api.delete(f"/game/{start['game_id']}")
print("테스트 8 통과: 지목 API")

# 테스트 9: 증거 관문 규칙 (핵심 단서, 천장)
assert normalize_question("어디 있었어요 ?") == normalize_question("어디  있었어요?!")
c = fresh_case()
assert key_clues_for(c, 1) == {"E01", "E02", "E03", "E08", "E09", "E10"}   # 범인: 결정적·정황·모순
assert key_clues_for(c, 2) == {"E04"} and key_clues_for(c, 3) == {"E07"}  # 무고한 사람: 미스리드·모순
c["suspects"][1]["presented_evidence"] = []
assert pressure_cap(c, 1) == 29
c["suspects"][1]["presented_evidence"] = ["E05", "E02"]                   # E05는 남의 단서라 안 셈
assert pressure_cap(c, 1) == 59
c["suspects"][1]["presented_evidence"] = ["E02", "E03", "E09"]
assert pressure_cap(c, 1) == 89
assert raise_pressure(27, 5, 29) == 29 and raise_pressure(44, 5, 29) == 44
print("테스트 9 통과: 증거 관문 규칙")

# 테스트 10: 서버 API로 증거 관문 따라가기 (AI 대신 가짜 대사)
main.generate_dialogue = lambda *args, **kwargs: {
    "dialogue": "모르겠어요.", "emotion": "calm", "ai_ok": True, "problems": [], "fixed": False}
start = api.post(f"/game/start?case_file={CASE_FILE}").json()
gid = start["game_id"]
investigate_all(gid, start["areas"])


def ask(question, evidence=None, suspect=1):
    return api.post("/game/interrogate", json={"game_id": gid, "suspect_id": suspect, "question": question,
                                               "presented_evidence_id": evidence})


assert ask("   ").status_code == 400                                        # 빈 질문
r = ask("어디 있었어요?").json()
assert r["pressure_level"] == 5 and r["pressure_cap"] == 29 and not r["need_evidence"], r
assert ask("어디 있었어요 ?").json()["pressure_level"] == 5                 # 띄어쓰기만 다름 → 반복
for i in range(10):
    r = ask(f"질문 {i}").json()
assert r["pressure_level"] == 29 and r["need_evidence"], r                 # 질문만으로는 29에서 멈춤
r = ask("이거 보세요", "E02").json()                                         # 정황 +15
assert r["pressure_level"] == 44 and r["pressure_cap"] == 59, r
for i in range(10, 20):
    r = ask(f"질문 {i}").json()
assert r["pressure_level"] == 59, r
r = ask("이건요?", "E05").json()                                             # 남의 알리바이 단서 = 헛짚기 -5
assert r["pressure_level"] == 59 - main.WRONG_EVIDENCE_PENALTY, r
r = ask("이건요?", "E05").json()                                             # 같은 증거를 다시 내밀면 변화 없음
assert r["pressure_level"] == 54, r
r = ask("이건요?", "E03").json()                                             # 모순 +20
assert r["pressure_level"] == 74 and r["pressure_cap"] == 89, r
for i in range(20, 30):
    r = ask(f"질문 {i}").json()
assert r["pressure_level"] == 89 and not r["is_confessed"], r              # 90은 질문으로 못 넘음
r = ask("이게 결정적 증거입니다", "E01").json()                              # 결정적 +35
assert r["pressure_level"] == 100 and r["is_confessed"] and not r["need_evidence"], r
state = api.get(f"/game/{gid}/state").json()
assert state["suspects"][0]["pressure_cap"] == 89, state
api.post("/game/accuse", json={"game_id": gid, "suspect_id": 1, "decisive_evidence_id": "E01"})
assert ask("한 가지만 더").status_code == 409                               # 끝난 게임은 심문 막음
api.delete(f"/game/{gid}")
print("테스트 10 통과: 증거 관문 API")

# 테스트 11: 조사 구역 규칙
c = fresh_case()
inv = new_investigation_state(c)
assert inv["enabled"] and inv["found"] == []
assert [a["name"] for a in inv["areas"]] == ["5층 테라스", "신소재공학 연구실", "행정실·보안 기록", "검시 결과"]
r = investigate_area(inv, "A1")
assert not r["already"] and r["new_ids"] == ["E01", "E02", "E09"], r
r = investigate_area(inv, "A1")
assert r["already"] and r["new_ids"] == [], r
assert investigate_area(inv, "A9") is None
hotel = new_investigation_state(main.make_default_case())                  # 구역 없는 사건 → 처음부터 전부 공개
assert not hotel["enabled"] and hotel["found"] == ["E01", "E02", "E03"]
r = judge_accusation(c, new_accuse_state(), 2, "E04", found=["E04"])       # 못 찾은 알리바이 단서는 구역으로 힌트
assert "「행정실·보안 기록」" in r["hint"] and "문서 파쇄실" not in r["hint"], r["hint"]
assert not split_warnings(check_case_quality(c))[0]                         # 지금 사건은 품질 문제 없음
for e in c["evidence_db"].values():
    e["area"] = "5층 테라스"
hard = split_warnings(check_case_quality(c))[0]
assert any("조사 구역이 1개" in h for h in hard) and any("한 구역에" in h for h in hard), hard
print("테스트 11 통과: 조사 구역 규칙")

# 테스트 12: 조사 API
start = api.post(f"/game/start?case_file={CASE_FILE}").json()
gid = start["game_id"]
assert start["evidences"] == [] and start["investigation"] is True, start
assert [a["area_id"] for a in start["areas"]] == ["A1", "A2", "A3", "A4"]
assert ask("이걸 보세요", "E01").status_code == 400                          # 못 찾은 단서 제시는 거절
r = api.post("/game/accuse", json={"game_id": gid, "suspect_id": 1, "decisive_evidence_id": "E01"})
assert r.status_code == 400                                                 # 못 찾은 단서로 지목도 거절
r = api.post("/game/investigate", json={"game_id": gid, "area_id": "A1"}).json()
assert [e["evidence_id"] for e in r["found_evidences"]] == ["E01", "E02", "E09"], r
assert len(r["evidences"]) == 3 and "3개" in r["message"] and r["areas"][0]["investigated"], r
assert "role" not in r["found_evidences"][0]                                # 역할 태그는 숨김
r = api.post("/game/investigate", json={"game_id": gid, "area_id": "A1"}).json()
assert r["already_investigated"] and "이미" in r["message"], r
assert api.post("/game/investigate", json={"game_id": gid, "area_id": "A9"}).status_code == 404
assert ask("이걸 보세요", "E01").status_code == 200                          # 찾은 뒤에는 제시 가능
r = api.post("/game/accuse", json={"game_id": gid, "suspect_id": 1, "decisive_evidence_id": "E01"}).json()
assert r["success"] and r["grade"] == "A", r                               # 거절된 지목은 오답 횟수에 안 들어감
state = api.get(f"/game/{gid}/state").json()
assert state["found_evidence_ids"] == ["E01", "E02", "E09"], state
api.delete(f"/game/{gid}")
print("테스트 12 통과: 조사 API")

# 테스트 13: 사건 브리핑
b = api.post(f"/game/start?case_file={CASE_FILE}").json()["briefing"]
assert b["title"] == CASE["title"] and b["text"] == CASE["briefing"] and len(b["suspects"]) == 3, b
assert b["suspects"][0].startswith("강도진 (박사과정 수석연구원) - "), b["suspects"]
assert "role" not in json.dumps(b, ensure_ascii=False) and CASE["truth"] not in json.dumps(b, ensure_ascii=False)
assert main.build_briefing(main.make_default_case())["text"] == main.make_default_case()["case_summary"]  # 브리핑 글 없으면 개요
c = fresh_case()
c["briefing"] = ""
assert any("브리핑" in h for h in split_warnings(check_case_quality(c))[0])
c["briefing"] = "강도진이 범인으로 보입니다."
hard = split_warnings(check_case_quality(c))[0]
assert any("'범인'" in h for h in hard) and any("강도진" in h for h in hard), hard
print("테스트 13 통과: 사건 브리핑")

# 테스트 14: 카테고리별 질문 목록 (질문 틀 + 사건별 AI 질문)
c = fresh_case()
lists = {x["category"]: x["questions"] for x in question_list(c, 1)}
assert list(lists) == ["관계", "알리바이", "감정"]
assert lists["관계"][0] == "서현우와는 어떤 사이였습니까?", lists["관계"]                  # 받침 없음 → 와
assert "박태준과는 어떤 사이입니까?" in lists["관계"] and "윤세아와는 어떤 사이입니까?" in lists["관계"]
assert "강도진" not in " ".join(lists["관계"])                                              # 자기 이름은 안 나옴
assert lists["알리바이"][0] == "사건 당시(21:30 ~ 22:00)에 어디에 있었습니까?", lists["알리바이"]
assert lists["감정"][0] == "서현우를 원망한 적이 있습니까?", lists["감정"]
c["suspects"][1]["questions"] = [
    {"category": "알리바이", "text": "컴퓨터실에서 논문을 고친 건 몇 시부터입니까?"},
    {"category": "알리바이", "text": "그 시간에 무엇을 하고 있었습니까 ?"},               # 질문 틀과 겹침 → 한 번만
]
alibi = {x["category"]: x["questions"] for x in question_list(c, 1)}["알리바이"]
assert alibi[0] == "컴퓨터실에서 논문을 고친 건 몇 시부터입니까?" and len(alibi) == MAX_QUESTIONS_PER_CATEGORY, alibi
assert sum("무엇을 하고 있었습니까" in q for q in alibi) == 1, alibi
hotel = {x["category"]: x["questions"] for x in question_list(main.make_default_case(), 2)}
assert hotel["관계"][0] == "피해자와는 어떤 사이였습니까?" and hotel["알리바이"][0] == "사건 당시에 어디에 있었습니까?"
qs = api.post(f"/game/start?case_file={CASE_FILE}").json()["questions"]
assert [q["suspect_id"] for q in qs] == [1, 2, 3] and len(qs[0]["categories"]) == 3, qs
c["suspects"][1]["questions"] = [{"category": "증거", "text": "E01 책상 위 메모는 뭡니까?"},
                                 {"category": "감정", "text": "당신이 범인입니까?"}]
hard = split_warnings(check_case_quality(c))[0]
assert any("카테고리" in h for h in hard) and any("'범인'" in h for h in hard), hard
print("테스트 14 통과: 질문 목록")

# 테스트 15: 단서 질문 (찾은 단서를 말로 떠보기)
c = fresh_case()
assert clue_questions(c, ["E05"]) == [{"clue_id": "E05", "text": CASE["evidence_db"]["E05"]["question"]}]
c["evidence_db"]["E05"]["question"] = ""
assert clue_questions(c, ["E05"])[0]["text"] == "「문서 파쇄실 출입 기록표」에 대해 들은 적이 있습니까?"   # 질문 없으면 틀
c = fresh_case()
assert judge_vital(c, 1, "단서", "E01", 10, False) == "긴장"     # 범인 + 자기를 가리키는 단서, 압박 낮음
assert judge_vital(c, 1, "단서", "E01", 40, False) == "거짓"     # 압박 30 이상
assert judge_vital(c, 1, "단서", "E05", 40, False) == "정상"     # 남의 알리바이 단서
assert judge_vital(c, 2, "단서", "E04", 10, False) == "긴장"     # 무고한 사람의 비밀은 말로는 긴장까지
assert judge_vital(c, 2, "단서", "E05", 10, False) == "정상"
q = CASE["evidence_db"]["E08"]["question"]
assert check_dialogue(c, 1, "그 분석서가 뭐 어쨌다는 겁니까?", q, None, False)          # 형사가 안 꺼낸 결정적 증거를 먼저 말함
assert not check_dialogue(c, 1, "그 분석서가 뭐 어쨌다는 겁니까?", q, None, False, "E08")  # 형사가 말로 꺼냈으면 허용
start = api.post(f"/game/start?case_file={CASE_FILE}").json()
gid = start["game_id"]
assert start["clue_questions"] == [], start["clue_questions"]
r = api.post("/game/interrogate", json={"game_id": gid, "suspect_id": 1, "question": "아무 질문", "clue_id": "E01"})
assert r.status_code == 400                                                  # 못 찾은 단서로는 질문 못 함
r = api.post("/game/investigate", json={"game_id": gid, "area_id": "A1"}).json()
assert [q["clue_id"] for q in r["new_clue_questions"]] == ["E01", "E02", "E09"], r["new_clue_questions"]
assert len(r["clue_questions"]) == 3
r = api.post("/game/investigate", json={"game_id": gid, "area_id": "A1"}).json()
assert r["new_clue_questions"] == [] and len(r["clue_questions"]) == 3       # 다시 조사해도 새 질문 없음
q = CASE["evidence_db"]["E01"]["question"]
r = api.post("/game/interrogate", json={"game_id": gid, "suspect_id": 1, "question": q, "clue_id": "E01"}).json()
assert r["question_category"] == "단서" and r["vital"] == "긴장" and r["pressure_level"] == 5, r   # 말로 묻기는 +5
api.delete(f"/game/{gid}")
c = fresh_case()
c["evidence_db"]["E01"]["question"] = "범인은 장갑을 꼈습니까?"
assert any("E01의 질문" in h for h in split_warnings(check_case_quality(c))[0])
assert not split_warnings(check_case_quality(fresh_case()))[0]               # 지금 사건은 문제 없음
print("테스트 15 통과: 단서 질문")

print("\n모든 게임 규칙 테스트를 통과했습니다.")
