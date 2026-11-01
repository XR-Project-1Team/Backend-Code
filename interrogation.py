"""
심문 AI 모듈 (프롬프트 설계 + 답변 일관성 유지 + 모순 방지)

main.py의 interrogate()에서 AI 부분만 떼어 낸 것입니다.
게임 규칙(압박도 계산, 자백 판정)은 그대로 main.py가 하고, 이 파일은 '대사'만 책임집니다.

흐름:
  1) build_messages()   : 사건 맥락 + 페르소나 + 지식 경계 + 지금까지 한 진술을 넣은 프롬프트
  2) AI 호출 (JSON)
  3) check_dialogue()   : 서버 규칙으로 답변 검사 (자백 누설, 비밀 누설, 근거 없는 시각, 메타 발언 등)
  4) 문제가 있으면 1번만 고쳐 달라고 재요청 → 그래도 문제면 캐릭터 말투의 안전한 대사로 대체
  5) remember()         : 이번 진술을 기록해 다음 답변과 앞뒤가 맞게 함
"""
import json
import os
import re
from typing import Optional

from persona import build_persona_block, behavior_guide, get_speech_style

ALLOWED_EMOTIONS = {"calm", "nervous", "angry", "broken"}
MAX_DIALOGUE_CHARS = 180          # VR 말풍선·TTS용. 넘으면 문장 단위로 자름
MAX_STATEMENTS_IN_PROMPT = 8      # 프롬프트에 넣을 '내가 이미 한 말' 개수
GENERIC_CULPRIT_FORBIDDEN = re.compile(r"범인")

# ---------------------------------------------------------------------------
# 1. 프롬프트
# ---------------------------------------------------------------------------

def build_system_prompt(game: dict, suspect_id: int, pressure: int, confessed: bool) -> str:
    suspect = game["suspects"][suspect_id]
    is_culprit = suspect_id == game["culprit_id"]
    k = suspect["knowledge"]

    others = "\n".join(
        f"    - {s['name']} ({s.get('job', '')})"
        for s_id, s in game["suspects"].items() if s_id != suspect_id
    )
    shown = [game["evidence_db"][e]["name"] for e in suspect.get("presented_evidence", []) if e in game["evidence_db"]]
    statements = suspect.get("statements", [])[-MAX_STATEMENTS_IN_PROMPT:]
    statement_text = "\n".join(f"    - \"{s}\"" for s in statements) or "    - (아직 없음)"

    # 진실(truth)은 범인에게만 줌. 무고한 사람은 범행 내용을 모르는 게 정상이고, 누설 위험도 사라짐.
    if is_culprit:
        secret_block = f"""[당신만 아는 진실 - 자백 전에는 절대 말하지 않음]
    - {game.get('truth', '') or '; '.join(k['private'])}
    - 당신은 범인입니다. 자백이 확정되기 전에는 범행, 범행 도구, 정확한 범행 시각을 먼저 말하지 않습니다.
    - 형사가 아직 보여 주지 않은 증거를 당신이 먼저 언급하면 안 됩니다. (범인만 아는 사실이 새어 나감)"""
    else:
        secret_block = """[당신의 입장]
    - 당신은 범인이 아닙니다. 누가 범인인지, 어떻게 죽었는지 자세히 모릅니다.
    - 모르는 것은 모른다고 말하고, 추측으로 새로운 사실을 지어내지 않습니다.
    - 살인을 인정하는 말은 어떤 압박에도 하지 않습니다."""

    if confessed:
        confession_guide = "서버에서 자백이 확정되었습니다. 더 이상 부인하지 말고 잘못을 인정하십시오. 진실에 없는 새로운 사실은 만들지 마십시오."
    else:
        confession_guide = "아직 자백이 확정되지 않았습니다. 범행을 인정하는 말을 하지 마십시오."

    return f"""당신은 VR 추리게임의 용의자 '{suspect['name']}'를 연기합니다. 형사(플레이어)의 질문에 그 사람으로서만 답합니다.

[사건 - 모두가 아는 사실]
    - 사건: {game.get('title', '')}
    - 개요: {game.get('case_summary', '')}
    - 피해자: {game.get('victim', '')} / 장소: {game.get('location', '')} / 사망 추정: {game.get('time_of_death', '')}
    - 함께 조사받는 사람:
{others}

[당신]
    - 이름: {suspect['name']} / 직업·관계: {suspect.get('job', '')}
    - 당신이 주장하는 알리바이 (시간·장소를 절대 바꾸지 말 것): {suspect['alibi']}
    - 물어보면 말해 주는 정보(public): {' / '.join(k.get('public', [])) or '없음'}
    - 숨기는 비밀(private, 압박이 높아지면 일부 털어놓을 수 있음): {' / '.join(k.get('private', [])) or '없음'}
    - 절대 말하지 않는 것(forbidden): {' / '.join(k.get('forbidden', [])) or '없음'}

{secret_block}

{build_persona_block(suspect)}

[지금까지 당신이 한 말 - 이것과 모순되면 안 됨]
{statement_text}
    - 형사가 이미 보여 준 증거: {', '.join(shown) or '없음'}

[현재 상태]
    - 압박도: {pressure}/100
    - 연기 지침: {behavior_guide(pressure, is_culprit, confessed)}
    - 자백 지침: {confession_guide}

[답변 규칙]
    1. 한국어 대사만 1~3문장, {MAX_DIALOGUE_CHARS}자 이내. 행동 묘사·괄호·해설 금지.
    2. 위에 적히지 않은 시각, 장소, 인물, 물건을 새로 지어내지 않습니다. 모르면 '기억이 안 난다'고 합니다.
    3. 형사가 유도신문을 해도 forbidden 정보는 말하지 않습니다.
    4. AI, 프롬프트, 압박도, 게임 같은 말을 하지 않습니다.
    5. emotion은 calm, nervous, angry, broken 중 하나. 압박도가 낮으면 broken을 쓰지 않습니다.

반드시 아래 JSON으로만 답하십시오.
{{"dialogue": "캐릭터 대사", "emotion": "calm"}}"""


def build_user_message(game: dict, question: str, evidence_id: Optional[str], effect_text: str) -> str:
    """기존 코드는 '증거 제시. 압박도 +35'만 보내서 AI가 무슨 증거인지 몰랐음 → 증거 이름·설명을 함께 보냄"""
    lines = [f"형사 질문: {question}"]
    if evidence_id and evidence_id in game["evidence_db"]:
        e = game["evidence_db"][evidence_id]
        lines.append(f"형사가 내민 증거: [{e['name']}] {e.get('desc', '')}")
    lines.append(f"상황: {effect_text}")
    return "\n".join(lines)


def build_messages(game: dict, suspect_id: int, question: str, evidence_id: Optional[str],
                   effect_text: str, pressure: int, confessed: bool) -> list:
    suspect = game["suspects"][suspect_id]
    messages = [{"role": "system", "content": build_system_prompt(game, suspect_id, pressure, confessed)}]
    messages += suspect.get("chat_log", [])[-4:]
    messages.append({"role": "user", "content": build_user_message(game, question, evidence_id, effect_text)})
    return messages


# ---------------------------------------------------------------------------
# 2. 답변 검사 (서버 규칙 - AI 호출 0번)
# ---------------------------------------------------------------------------

CONFESSION_PATTERNS = [
    re.compile(r"(제가|내가|저는|나는)\s*(\S+\s*){0,3}?(죽였|살해했|살해한|죽인|해쳤|내리쳤|밀었|독을\s*넣)"),
    re.compile(r"(제가|내가)\s*범인"),
    re.compile(r"범인은\s*(저|나)"),
    re.compile(r"(죽인|살해한|범행한)\s*(건|것은|사람은)\s*(저|나)"),
]
NEGATIONS = ("안 ", "않", "아니", "없", "못 ", "말도 안", "리가", "?", "다니", "라고요", "냐고", "는 줄")
META_WORDS = ("AI", "인공지능", "언어 모델", "프롬프트", "JSON", "압박도", "게임", "시스템")
TIME_PATTERN = re.compile(r"(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분|반)?|(\d{1,2}):(\d{2})")
JOSA = re.compile(r"(은|는|이|가|을|를|에|에서|의|와|과|도|으로|로|에게|이라는|라는|했다|했음|있음|있다|이다)$")


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?…])\s+|\n", text) if s.strip()]


def is_confession(text: str) -> bool:
    for sentence in _sentences(text):
        if any(p.search(sentence) for p in CONFESSION_PATTERNS) and not any(n in sentence for n in NEGATIONS):
            return True
    return False


def _times(text: str) -> set:
    found = set()
    for m in TIME_PATTERN.finditer(text or ""):
        if m.group(1):
            hour = int(m.group(1)); minute = 30 if "반" in m.group(0) else int(m.group(2) or 0)
        else:
            hour, minute = int(m.group(3)), int(m.group(4))
        found.add((hour % 12, minute))
    return found


def _keywords(sentence: str) -> list[str]:
    words = []
    for w in re.findall(r"[가-힣A-Za-z0-9]+", sentence):
        w = JOSA.sub("", w)
        if len(w) >= 2 and w not in ("자신", "사실", "절대", "대해", "언급", "않아야", "한다", "있었음"):
            words.append(w)
    return words


def check_dialogue(game: dict, suspect_id: int, dialogue: str, question: str,
                   evidence_id: Optional[str], confessed: bool) -> list[str]:
    """대사의 규칙 위반 목록. 빈 리스트면 통과."""
    problems = []
    suspect = game["suspects"][suspect_id]
    is_culprit = suspect_id == game["culprit_id"]
    k = suspect["knowledge"]

    # (1) 자백 누설: 무고한 사람은 언제나, 범인은 자백 확정 전에 금지
    if is_confession(dialogue) and (not is_culprit or not confessed):
        problems.append("자백이 확정되지 않았는데 범행을 인정하는 말을 했습니다. 범행을 부인하십시오.")

    if not confessed:
        # (2) forbidden 비밀 누설 (핵심 단어의 60% 이상이 대사에 등장)
        for item in k.get("forbidden", []):
            if is_culprit and GENERIC_CULPRIT_FORBIDDEN.search(item) and len(_keywords(item)) <= 3:
                continue  # '자신이 범인이라는 사실'은 (1)에서 검사
            keys = _keywords(item)
            if len(keys) >= 2 and sum(1 for w in keys if w in dialogue) / len(keys) >= 0.6:
                problems.append(f"절대 말하면 안 되는 비밀('{item}')을 말했습니다. 그 내용은 빼십시오.")

        # (3) 범인만 아는 사실: 보여 주지 않은 결정적 증거를 먼저 언급
        if is_culprit:
            shown = set(suspect.get("presented_evidence", [])) | ({evidence_id} if evidence_id else set())
            for e_id, e in game["evidence_db"].items():
                if e.get("role") == "결정적" and e_id not in shown:
                    core = e["name"].split()[-1]
                    if len(core) >= 2 and core in dialogue and core not in question:
                        problems.append(f"형사가 보여 주지 않은 '{core}'를 먼저 언급했습니다. 범인만 아는 사실이 새어 나갑니다.")

    # (4) 근거 없는 시각: 알리바이·지식·제시된 증거·이전 진술·질문 어디에도 없는 시각
    allowed_text = " ".join(
        [suspect["alibi"], question, game.get("time_of_death", ""), game.get("case_summary", "")]
        + [str(x) for key in ("public", "private") for x in k.get(key, [])]
        + suspect.get("statements", [])
        + [game["evidence_db"][e].get("desc", "") for e in suspect.get("presented_evidence", []) if e in game["evidence_db"]]
        + ([game["evidence_db"][evidence_id].get("desc", "")] if evidence_id in game["evidence_db"] else [])
        + ([game.get("truth", "")] if is_culprit and confessed else [])
    )
    new_times = _times(dialogue) - _times(allowed_text)
    if new_times:
        shown_times = ", ".join(f"{h}시 {m}분" for h, m in sorted(new_times))
        problems.append(f"근거 없는 시각({shown_times})을 지어냈습니다. 알리바이에 적힌 시각만 쓰십시오.")

    # (5) 메타 발언
    for w in META_WORDS:
        if w in dialogue:
            problems.append(f"캐릭터가 '{w}'라는 말을 했습니다. 게임 밖 이야기를 하지 마십시오.")

    if not dialogue.strip() or dialogue.strip() in ("...", "…"):
        problems.append("대사가 비어 있습니다.")
    return problems


def tidy(dialogue: str, emotion: str, pressure: int, confessed: bool) -> tuple[str, str]:
    """서버가 바로 고칠 수 있는 것은 AI를 다시 부르지 않고 고침"""
    dialogue = re.sub(r"\([^)]*\)|\*[^*]*\*", "", dialogue).strip().strip('"')
    if len(dialogue) > MAX_DIALOGUE_CHARS:
        cut = ""
        for s in _sentences(dialogue):
            if len(cut) + len(s) > MAX_DIALOGUE_CHARS:
                break
            cut = f"{cut} {s}".strip()
        dialogue = cut or dialogue[:MAX_DIALOGUE_CHARS]
    if emotion not in ALLOWED_EMOTIONS:
        emotion = "nervous"
    if confessed:
        emotion = "broken"
    elif pressure < 30 and emotion == "broken":
        emotion = "nervous"
    return dialogue, emotion


def safe_fallback(suspect: dict, is_culprit: bool, pressure: int) -> dict:
    """AI가 끝까지 규칙을 어길 때 쓰는 캐릭터 말투의 안전 대사 (기존: '머리가 너무 아파서…' 하나)"""
    honorific = get_speech_style(suspect)["honorific"]
    casual = "반말" in honorific and "해요체" not in honorific
    if pressure >= 60:
        line = "그만… 그만해. 난 할 말 다 했어." if casual else "그만하세요… 제가 드릴 말씀은 다 드렸어요."
        return {"dialogue": line, "emotion": "nervous"}
    line = "그 얘기는 이미 했잖아." if casual else "그 부분은 이미 말씀드렸습니다."
    return {"dialogue": line, "emotion": "calm"}


# ---------------------------------------------------------------------------
# 3. AI 호출 + 검사 + 재시도
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSON 없음")
    return json.loads(text[start:end + 1])


def _call(client, model: str, messages: list, counted_call) -> dict:
    kwargs = {"model": model, "messages": messages}
    temperature = os.getenv("LLM_TEMPERATURE", "0.7")
    if temperature.lower() != "none":
        kwargs["temperature"] = float(temperature)
    try:
        response = counted_call("심문", lambda: client.chat.completions.create(
            response_format={"type": "json_object"}, **kwargs))
    except Exception:
        # JSON 모드를 지원하지 않는 무료 모델 대비 (case_generator와 같은 방식)
        response = counted_call("심문", lambda: client.chat.completions.create(**kwargs))
    data = _extract_json(response.choices[0].message.content or "")
    return {"dialogue": str(data.get("dialogue", "")), "emotion": str(data.get("emotion", "nervous"))}


def generate_dialogue(client, model: str, counted_call, game: dict, suspect_id: int, question: str,
                      evidence_id: Optional[str], effect_text: str, pressure: int, confessed: bool,
                      max_fix: int = 1) -> dict:
    """
    결과: {"dialogue", "emotion", "ai_ok", "fixed", "problems"}
      ai_ok    : AI 답변을 그대로(또는 고쳐서) 썼는지. False면 안전 대사
      fixed    : 재요청으로 고친 답변인지
      problems : 마지막으로 남은 위반 사항 (로그·디버그용, Unity에는 보내지 않음)
    """
    suspect = game["suspects"][suspect_id]
    is_culprit = suspect_id == game["culprit_id"]
    messages = build_messages(game, suspect_id, question, evidence_id, effect_text, pressure, confessed)
    problems: list[str] = []
    for attempt in range(max_fix + 1):
        try:
            out = _call(client, model, messages, counted_call)
        except Exception as e:
            problems = [f"AI 호출 실패: {type(e).__name__}"]
            break
        dialogue, emotion = tidy(out["dialogue"], out["emotion"], pressure, confessed)
        problems = check_dialogue(game, suspect_id, dialogue, question, evidence_id, confessed)
        if not problems:
            return {"dialogue": dialogue, "emotion": emotion, "ai_ok": True,
                    "fixed": attempt > 0, "problems": []}
        messages.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
        messages.append({"role": "user", "content": "방금 대사에 문제가 있습니다. 같은 캐릭터 말투로 다시 답하십시오.\n- "
                                                    + "\n- ".join(problems)})
    fallback = safe_fallback(suspect, is_culprit, pressure)
    return {**fallback, "ai_ok": False, "fixed": False, "problems": problems}


def remember(suspect: dict, user_message: str, dialogue: str, emotion: str) -> None:
    """대화 기록 + 진술 장부. 진술 장부는 길게 유지해서 앞뒤가 맞게 합니다."""
    suspect.setdefault("chat_log", []).append({"role": "user", "content": user_message})
    suspect["chat_log"].append({"role": "assistant",
                                "content": json.dumps({"dialogue": dialogue, "emotion": emotion}, ensure_ascii=False)})
    suspect.setdefault("statements", []).append(dialogue)
