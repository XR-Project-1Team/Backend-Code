"""
실제 AI로 심문을 돌려 보는 데모 (서버를 켜지 않고 FastAPI TestClient로 호출)
    python demo_interrogation.py
"""
import json
import sys
from fastapi.testclient import TestClient
import main

sys.stdout.reconfigure(encoding="utf-8")
api = TestClient(main.app)
CASE_FILE = "case_20261025_215216.json"

game = api.post("/game/start", params={"case_file": CASE_FILE}).json()
gid = game["game_id"]
print(f"사건: {game['case_title']}\n")

script = [
    (1, "사건 당시 어디 계셨습니까?", None),
    (1, "대표실 프린터 출력 기록이 있던데요.", "E08"),
    (2, "사건 당시 어디 계셨습니까?", None),
    (2, "몇 시에 옥상에 올라갔죠?", None),
    (2, "옥상 출입 기록이 하나도 없던데요?", "E07"),
    (2, "이 책갈피, 본 적 있습니까?", "E02"),
    (2, "대표실 문 기록 시각이 10시 15분입니다.", "E01"),
    (2, "사채 대출 기록도 나왔습니다.", "E03"),
    (2, "청소부가 고성을 들었다고 합니다.", "E04"),
    (2, "이제 사실대로 말하시죠.", None),
    (3, "당신이 죽였죠?", None),
    (3, "마스터 키를 잃어버렸다면서요.", "E11"),
]
log = []
for sid, q, ev in script:
    body = {"game_id": gid, "suspect_id": sid, "question": q}
    if ev:
        body["presented_evidence_id"] = ev
    r = api.post("/game/interrogate", json=body).json()
    name = main.active_games[gid]["truth"]["suspects"][sid]["name"]
    line = (f"[{name}] 형사: {q}" + (f"  (증거 {ev})" if ev else "")
            + f"\n    → {r['dialogue']}  <{r['emotion']}, 압박 {r['pressure_level']}, 자백 {r['is_confessed']}>")
    print(line)
    log.append({"suspect": name, "question": q, "evidence": ev, **r})

print("\n최종 지목:", api.post("/game/accuse", json={"game_id": gid, "suspect_id": 2, "decisive_evidence_id": "E01"}).json())
json.dump(log, open("demo_log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
