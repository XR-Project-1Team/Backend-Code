"""
용의자 페르소나(성격·말투·답변 방식) 모듈

문제: 지금은 personality 한 줄("차분하고 논리적")만 프롬프트에 넣어서
      세 용의자가 모두 비슷한 AI 말투(정중한 존댓말 + 긴 문장)로 답합니다.

해결: 말투를 '구체적인 규칙'으로 바꿔서 넣습니다.
  - 존댓말/반말, 문장 길이, 말버릇, 회피 방식, 압박받을 때 반응, 예시 대사
  - 사건 JSON에 speech_style이 있으면 그것을 쓰고,
    없으면 personality 문장의 키워드로 가장 가까운 기본 말투를 고릅니다. (기존 사건 파일도 그대로 사용 가능)
"""
from typing import Optional

# 기본 말투 프리셋 (키워드 → 말투 규칙)
STYLE_PRESETS = {
    "냉정형": {
        "keywords": ["차분", "논리", "냉정", "침착", "세련", "단정", "감정을 잘 드러내지"],
        "honorific": "격식체 존댓말(~습니다, ~입니다)",
        "sentence": "짧고 단정한 문장 1~2개. 감탄사를 쓰지 않음",
        "habit": "'정확히 말씀드리면', '기록을 보시면 압니다' 같은 표현",
        "evasion": "사실만 짧게 말하고 질문을 되묻는다 ('그게 사건과 무슨 관계죠?')",
        "under_pressure": "말이 더 짧아지고 같은 사실을 반복한다. 목소리를 높이지 않는다",
        "examples": ["그 시간엔 편집실에 있었습니다. 로그를 확인해 보시죠.", "질문의 의도를 모르겠군요."],
    },
    "다혈질형": {
        "keywords": ["자존심", "격해", "공격", "예민", "목소리가 큰", "다혈질", "화를"],
        "honorific": "해요체와 반말이 섞임. 화나면 반말",
        "sentence": "짧고 끊어지는 문장, 느낌표와 반문이 많음",
        "habit": "'아니, 그러니까요!', '지금 저 의심하는 거예요?'",
        "evasion": "농담이나 화로 화제를 돌린다. 형사를 역으로 몰아붙인다",
        "under_pressure": "언성을 높이다가 말을 더듬고, 결국 말끝이 꺾인다",
        "examples": ["아니, 그러니까 옥상에 있었다니까요!", "증거 있어요? 없으면 그만하시죠."],
    },
    "소심형": {
        "keywords": ["소심", "조용", "겁", "말수가 적", "시선을 피", "내성"],
        "honorific": "공손한 해요체(~요)",
        "sentence": "아주 짧게. 말줄임표(...)와 망설임('저, 그게...')이 많음",
        "habit": "'저... 잘 모르겠어요', '정말이에요...'",
        "evasion": "모른다고 하거나 대답을 미룬다",
        "under_pressure": "울먹이며 묻지 않은 작은 사실까지 털어놓기 시작한다",
        "examples": ["저, 저는 편의점에 다녀왔을 뿐이에요...", "그건... 말씀드리기 좀..."],
    },
    "사교형": {
        "keywords": ["자신감", "설득", "사교", "능청", "유쾌", "농담", "말이 많"],
        "honorific": "부드러운 해요체, 상대를 '형사님'이라고 부름",
        "sentence": "길게 설명하는 편. 이야기를 곁들임",
        "habit": "'형사님도 아시잖아요', '솔직히 말씀드리면요'",
        "evasion": "친근하게 웃으며 다른 이야기로 돌린다",
        "under_pressure": "웃음이 사라지고 말이 빨라지며 앞뒤가 꼬인다",
        "examples": ["형사님, 저랑 그 사람 사이 아시잖아요. 제가 왜 그러겠어요?"],
    },
    "성실형": {
        "keywords": ["성실", "세심", "관찰", "정리정돈", "계획", "꼼꼼"],
        "honorific": "공손한 해요체",
        "sentence": "시간·순서대로 또박또박 설명",
        "habit": "'제가 기억하기로는요', '순서대로 말씀드릴게요'",
        "evasion": "업무 이야기로 돌리고 개인적인 질문은 피한다",
        "under_pressure": "기억이 흔들리며 시간을 고쳐 말하려다 멈춘다",
        "examples": ["제가 기억하기로는 세 시부터 복도 청소를 했어요."],
    },
}
DEFAULT_STYLE = "성실형"


def pick_preset(personality: str) -> str:
    """personality 문장에서 키워드가 가장 많이 맞는 프리셋 이름을 고릅니다."""
    best, best_score = DEFAULT_STYLE, 0
    for name, preset in STYLE_PRESETS.items():
        score = sum(1 for k in preset["keywords"] if k in (personality or ""))
        if score > best_score:
            best, best_score = name, score
    return best


def get_speech_style(suspect: dict) -> dict:
    """사건 JSON의 speech_style이 있으면 우선 사용하고, 빈 칸은 프리셋으로 채웁니다."""
    preset = dict(STYLE_PRESETS[pick_preset(suspect.get("personality", ""))])
    preset.pop("keywords", None)
    custom = suspect.get("speech_style") or {}
    if isinstance(custom, dict):
        for key, value in custom.items():
            if value:
                preset[key] = value
    return preset


def build_persona_block(suspect: dict) -> str:
    """시스템 프롬프트에 넣을 [성격과 말투] 블록"""
    st = get_speech_style(suspect)
    examples = st.get("examples") or []
    if isinstance(examples, str):
        examples = [examples]
    example_lines = "\n".join(f'      · "{e}"' for e in examples[:3])
    return f"""[성격과 말투 - 반드시 이 사람처럼 말할 것]
    - 성격: {suspect.get('personality', '평범함')}
    - 높임말: {st['honorific']}
    - 문장: {st['sentence']}
    - 말버릇: {st['habit']}
    - 곤란한 질문을 피하는 방식: {st['evasion']}
    - 압박받을 때: {st['under_pressure']}
    - 말투 예시 (내용은 따라 하지 말고 말투만 참고):
{example_lines}"""


def behavior_guide(pressure: int, is_culprit: bool, confessed: bool) -> str:
    """
    압박 단계별 연기 지침. 범인과 무고한 사람을 다르게 연기시킵니다.
    (기존 코드는 둘이 같아서, 압박 90의 무고한 사람이 '체념'하며 자백처럼 들리는 문제가 있었음)
    """
    if confessed:
        return "자백이 확정되었습니다. 체념하거나 오열하며 범행을 인정합니다. 사건 진실(truth)에 적힌 범위 안에서만 말합니다."
    if pressure < 30:
        return "여유가 있습니다. 알리바이를 그대로 말하고 결백을 주장합니다. private 정보는 꺼내지 않습니다."
    if pressure < 60:
        return "방어적으로 변합니다. 말끝을 흐리거나 짜증을 냅니다. 알리바이의 시간·장소는 절대 바꾸지 않습니다."
    if pressure < 90:
        if is_culprit:
            return ("거짓말이 흔들리고 있습니다. 범행과 관계없는 private 비밀(돈, 관계 등)을 털어놓아 시선을 돌리려 합니다. "
                    "범행 자체는 끝까지 부인합니다.")
        return "억울함이 폭발합니다. 숨기던 개인 비밀(private)을 변명하듯 털어놓지만, 살인과는 무관하다고 강하게 말합니다."
    if is_culprit:
        return "궁지에 몰려 정신이 무너지기 직전입니다. 말이 엉키고 감정이 격해지지만, 결정적 증거 전까지는 범행을 인정하지 않습니다."
    return "지쳐서 무너졌습니다. 울먹이며 '저는 정말 안 죽였다'고 호소합니다. 범행을 인정하는 말은 절대 하지 않습니다."
