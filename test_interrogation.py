"""
심문 AI 검사 테스트 (AI 호출 없음)
    python test_interrogation.py
"""
import copy
import json
from pathlib import Path

from case_generator import load_case
from case_quality import check_case_quality, split_warnings
from interrogation import check_dialogue, is_confession, tidy, generate_dialogue, build_system_prompt
from persona import pick_preset

CASE = load_case(Path(__file__).parent / "cases" / "case_20261025_215216.json")  # 범인 2 이준호


def fresh_game():
    g = copy.deepcopy(CASE)
    for s in g["suspects"].values():
        s.update(presented_evidence=[], statements=[], chat_log=[], confessed=False)
    return g


# 1. 자백 문장 감지 (부정문은 자백 아님)
assert is_confession("네... 제가 대표님을 죽였습니다.")
assert is_confession("범인은 저예요.")
assert not is_confession("제가 죽였다고요? 말도 안 돼요!")
assert not is_confession("저는 절대 안 죽였어요.")
print("테스트 1 통과: 자백 문장 감지")

# 2. 자백 전 범인이 범행 인정 → 위반 / 자백 확정 후 → 허용
g = fresh_game()
assert check_dialogue(g, 2, "그래, 내가 그 녀석을 내리쳤어.", "솔직히 말해", None, confessed=False)
assert not check_dialogue(g, 2, "그래, 내가 그 녀석을 내리쳤어.", "솔직히 말해", None, confessed=True)
print("테스트 2 통과: 자백 확정 전후 구분")

# 3. 무고한 사람은 어떤 상황에도 자백 금지
assert check_dialogue(g, 3, "제가 죽였어요...", "네가 죽였지?", None, confessed=True)
print("테스트 3 통과: 무고한 용의자 자백 차단")

# 4. forbidden 비밀 누설 감지 (최민서: 공금 횡령)
problems = check_dialogue(g, 1, "사실 제가 회사 공금을 횡령해서 대표에게 약점 잡혀 있었습니다.", "숨기는 거 있죠?", None, False)
assert any("비밀" in p for p in problems), problems
print("테스트 4 통과: 비밀 누설 감지")

# 5. 근거 없는 시각 감지 (알리바이: 10시 10분~20분 옥상)
assert not check_dialogue(g, 2, "10시 10분부터 옥상에 있었다니까요!", "어디 있었죠?", None, False)
problems = check_dialogue(g, 2, "11시 40분쯤 집에 갔어요.", "어디 있었죠?", None, False)
assert any("시각" in p for p in problems), problems
print("테스트 5 통과: 근거 없는 시각 감지")

# 6. 범인이 보여 주지 않은 결정적 증거를 먼저 언급 → 위반, 제시 후 → 허용
problems = check_dialogue(g, 2, "책갈피 따위로 사람이 죽어요?", "대표실에서 뭐 했어요?", None, False)
assert any("책갈피" in p for p in problems), problems
assert not check_dialogue(g, 2, "책갈피 따위로 사람이 죽어요?", "이거 보세요", "E02", False)
print("테스트 6 통과: 범인만 아는 사실 누설 감지")

# 7. 메타 발언, 괄호 행동 묘사 제거, 감정 보정
assert check_dialogue(g, 3, "저는 AI라서 모르겠어요.", "누구야?", None, False)
d, e = tidy("(눈을 피하며) 저는 몰라요.", "broken", pressure=10, confessed=False)
assert d == "저는 몰라요." and e == "nervous", (d, e)
print("테스트 7 통과: 메타 발언 차단 및 대사 정리")

# 8. 진실(truth)은 범인 프롬프트에만 들어감
assert "청동 책갈피" in build_system_prompt(g, 2, 0, False)
assert "청동 책갈피" not in build_system_prompt(g, 1, 0, False)
print("테스트 8 통과: 무고한 용의자에게 진실 비공개")

# 9. 말투 프리셋이 용의자마다 다르게 선택됨
presets = [pick_preset(s["personality"]) for s in CASE["suspects"].values()]
assert len(set(presets)) == 3, presets
print(f"테스트 9 통과: 말투 프리셋 {presets}")


# 10. 재시도 흐름: 1번째 답변이 규칙 위반 → 2번째 답변 채택
class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = 0
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        text = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        msg = type("M", (), {"content": json.dumps(text, ensure_ascii=False)})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


no_count = lambda kind, f: f()
fake = FakeClient([{"dialogue": "내가 죽였어.", "emotion": "broken"},
                   {"dialogue": "아니, 옥상에 있었다니까요!", "emotion": "angry"}])
r = generate_dialogue(fake, "m", no_count, fresh_game(), 2, "죽였지?", None, "", 40, False)
assert r["ai_ok"] and r["fixed"] and fake.calls == 2 and "옥상" in r["dialogue"], r
fake = FakeClient([{"dialogue": "내가 죽였어.", "emotion": "broken"}])
r = generate_dialogue(fake, "m", no_count, fresh_game(), 2, "죽였지?", None, "", 40, False)
assert not r["ai_ok"] and "죽였" not in r["dialogue"], r
print("테스트 10 통과: 위반 시 1번 재요청 → 실패 시 안전 대사")

# 11. 사건 품질 검사기: 시작 압박도 75, 무고한 사람의 '자신이 범인' 감지
bad = load_case(Path(__file__).parent / "cases" / "case_20261025_211252.json")
hard, _ = split_warnings(check_case_quality(bad))
assert any("시작 압박도가 75" in e for e in hard)
bad = load_case(Path(__file__).parent / "cases" / "case_20261025_210324.json")
hard, _ = split_warnings(check_case_quality(bad, expected_culprit_id=3))
assert any("자신이 범인이라는 사실" in e for e in hard) and any("범인은 용의자 3" in e for e in hard)
print("테스트 11 통과: 사건 품질 검사")

print("\n모든 심문 AI 테스트를 통과했습니다.")
