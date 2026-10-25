import os
import uuid
import json
import copy
import random
import threading
from typing import Dict, Optional, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv
from validator import validate_case, validate_generated_case
from case_generator import generate_case, load_case, list_case_files, mark_played, MAX_ACTIVE_CASES
from usage_counter import counted_call, get_usage

# .env 파일의 API 키를 불러옴
load_dotenv()

# OpenRouter 연결 설정
client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
    max_retries=0   # 자동 재시도를 끄면 AI 호출 횟수를 정확히 셀 수 있음 (실패 시 기본 대사로 대체)
)
MODEL_NAME = os.getenv("LLM_MODEL", "openrouter/free")

app = FastAPI(title="VR Detective AI Server - Version 3")

# 메모리 기반 게임 세션 저장소
active_games: Dict[str, dict] = {}

# --- 1. 통신 데이터 규격 (Pydantic 고도화) ---
class InterrogateRequest(BaseModel):
    game_id: str
    suspect_id: int
    question: str
    presented_evidence_id: Optional[str] = None

class AccuseRequest(BaseModel):
    game_id: str
    suspect_id: int
    decisive_evidence_id: str

# 🚨 AI 응답을 깐깐하게 검증하기 위한 규격
class NPCResponse(BaseModel):
    dialogue: str = Field(default="...")
    emotion: str = Field(default="nervous")

ALLOWED_EMOTIONS = {"calm", "nervous", "angry", "broken"}

# --- 2. 사건 데이터 ---
# 저장된 AI 생성 사건이 없거나 모두 실패했을 때 쓰는 비상용 고정 사건
def make_default_case():
    return {
        "title": "호텔 302호 살인사건",
        "case_summary": "호텔 302호에서 사장 김도윤이 숨진 채 발견되었다.",
        "culprit_id": 2,
        "decisive_evidence_id": "E01",
        "suspects": {
            1: {
                "name": "박민수", "job": "호텔 직원",
                "description": "호텔 직원. 로비에 있었다고 진술했다.",
                "alibi": "23시에는 1층 로비 카운터를 지키고 있었습니다.",
                "knowledge": {
                    "public": ["사건 당일 302호 열쇠는 2번 용의자가 가져갔다."],
                    "private": ["금고에서 돈을 훔친 적이 있다."],
                    "forbidden": ["자신은 살인사건과 무관하다는 것을 절대 먼저 말하지 않음"]
                },
                "evidence_effects": {"E02": 35, "E03": 10},
                "pressure_level": 10
            },
            2: {
                "name": "이지은", "job": "전속 비서",
                "description": "전속 비서. 카페테리아에 있었다고 진술했다.",
                "alibi": "23시에는 카페테리아에서 서류 정리를 하고 있었습니다.",
                "knowledge": {
                    "public": ["사장을 마지막으로 본 것은 22시경이다."],
                    "private": ["자신이 302호에서 사장을 내리쳤고, 시계를 떨어뜨렸다."],
                    "forbidden": ["자신이 범인이라는 사실", "살해 도구가 조각상이라는 사실", "정확한 살해 시간"]
                },
                "evidence_effects": {"E01": 40, "E02": 5},
                "pressure_level": 0
            }
        },
        "evidence_db": {
            "E01": {"name": "깨진 손목시계", "desc": "사건 현장에 떨어진 시계. 23:10에 멈춰있음."},
            "E02": {"name": "도난 장부", "desc": "로비 금고에서 사라진 돈의 내역서"},
            "E03": {"name": "카페테리아 CCTV", "desc": "23시경 이지은의 모습이 없음"}
        }
    }


def pick_case(case_file: Optional[str] = None):
    """
    게임에 쓸 사건을 고릅니다.
    1순위: 아직 플레이하지 않은 가장 새 사건 (지난 게임 중에 AI가 만들어 둔 것)
    2순위: 이미 플레이한 사건 중 무작위
    모두 없으면 비상용 고정 사건을 씁니다.
    """
    files = list_case_files()

    if case_file:
        files = [f for f in files if f.name == case_file]
        if not files:
            raise HTTPException(status_code=404, detail="저장된 사건 파일을 찾을 수 없습니다.")

    unplayed, played = [], []
    for file_path in files:
        try:
            case = load_case(file_path)
        except Exception:
            continue
        if validate_generated_case(case):
            continue
        (played if case.get("played") else unplayed).append((file_path, case))

    if unplayed:
        file_path, case = unplayed[-1]          # 파일 이름이 날짜순이라 마지막이 가장 새 사건
    elif played:
        file_path, case = random.choice(played)
    else:
        return make_default_case(), "default"

    mark_played(file_path)
    return case, file_path.name


# --- 게임 중 다음 사건 미리 만들기 (.env의 AUTO_GENERATE=on 일 때만) ---
_generation_lock = threading.Lock()
_generating = False


def auto_generate_enabled() -> bool:
    return os.getenv("AUTO_GENERATE", "off").strip().lower() in ("on", "true", "1")


def start_background_generation():
    """뒤에서 새 사건을 1개 만듭니다. 이미 만드는 중이면 새로 시작하지 않습니다."""
    global _generating
    if not auto_generate_enabled():
        return
    with _generation_lock:
        if _generating:
            return
        _generating = True

    def worker():
        global _generating
        try:
            print("[자동 생성] 다음 게임용 사건 생성 시작")
            result = generate_case()
            if result["success"]:
                print(f"[자동 생성] 완료: cases/{result['file']}")
            else:
                print("[자동 생성] 실패: 검사를 통과한 사건이 없어 저장하지 않음")
        except Exception as e:
            print(f"[자동 생성] 오류: {e}")
        finally:
            with _generation_lock:
                _generating = False

    threading.Thread(target=worker, daemon=True).start()


# --- 3. 게임 시작 API ---
@app.post("/game/start")
def start_game(case_file: Optional[str] = None):
    game_id = str(uuid.uuid4())[:8]

    # [서버 진실 데이터베이스] 원본 사건을 복사해서 이번 판의 상태를 붙임
    case, source = pick_case(case_file)

    # 이번 게임을 하는 동안 다음 게임용 사건을 미리 만들어 둠
    start_background_generation()
    server_truth = copy.deepcopy(case)

    for suspect in server_truth["suspects"].values():
        # 🚨 V3 추가: 상태 관리 고도화
        suspect["confessed"] = False          # 자백 여부 분리
        suspect["presented_evidence"] = []    # 이미 제시된 증거 기록 (중복 방지)
        suspect["asked_questions"] = []       # 이미 한 질문 기록 (같은 질문 반복 시 압박도 유지)
        suspect["answer_cache"] = {}          # 같은 질문의 이전 답변 (반복 시 AI 호출 없이 재사용)
        suspect["chat_log"] = []              # AI 대화 문맥 저장을 위한 기록

    # 사건 데이터 검증: 오류가 있으면 게임 시작을 차단
    validation_errors = validate_case(server_truth)

    if validation_errors:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "사건 데이터 검증에 실패했습니다.",
                "errors": validation_errors
            }
        )

    # 검증을 통과한 사건만 게임 세션에 등록
    active_games[game_id] = {"truth": server_truth, "case_source": source}

    # 플레이어(Unity)에게는 공개 정보만 전달 (범인·역할 태그·비밀은 숨김)
    public_info = {
        "game_id": game_id,
        "case_title": server_truth.get("title", ""),
        "case_summary": server_truth.get("case_summary", ""),
        "suspects": [
            {
                "suspect_id": s_id,
                "name": s["name"],
                "description": s.get("description", "")
            }
            for s_id, s in server_truth["suspects"].items()
        ],
        "evidences": [
            {
                "evidence_id": e_id,
                "name": e["name"],
                "description": e.get("desc", "")
            }
            for e_id, e in server_truth["evidence_db"].items()
        ]
    }

    return public_info

# --- 4. AI 사건 생성 API (생성 AI → 규칙 검사기 → 저장) ---
@app.post("/case/generate")
def create_case():
    result = generate_case()

    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"{len(result['attempts'])}번 시도했지만 검사를 통과한 사건을 만들지 못했습니다.",
                "attempts": result["attempts"]
            }
        )

    case = result["case"]
    role_counts: Dict[str, int] = {}
    for e in case["evidence_db"].values():
        role_counts[e["role"]] = role_counts.get(e["role"], 0) + 1

    # 시연용 요약 (범인 정보는 응답에 넣지 않음)
    return {
        "file": result["file"],
        "attempts": result["attempts"],
        "title": case["title"],
        "case_summary": case["case_summary"],
        "suspects": [f"{s['name']} ({s['job']})" for s in case["suspects"].values()],
        "clue_roles": role_counts,
        "review_notes": case.get("review_notes", [])
    }

def fetch_openrouter_key_info():
    """OpenRouter가 알려 주는 이 키의 사용량·한도. 키 이름(label)은 빼고 숫자만 돌려줌."""
    import urllib.request
    base_url = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/key",
        headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8")).get("data", {})
    except Exception as e:
        return {"error": f"OpenRouter 정보를 가져오지 못했습니다: {type(e).__name__}"}

    safe_keys = ("is_free_tier", "usage", "usage_daily", "limit", "limit_remaining", "rate_limit")
    return {k: data[k] for k in safe_keys if k in data}


# --- AI 호출 횟수 확인 API (서버에서만 확인, Unity에는 표시하지 않음) ---
@app.get("/usage")
def get_ai_usage():
    usage = get_usage(days=7)
    return {
        "today": usage["today"],
        "today_calls": usage["today_usage"],
        "recent_7_days": {d: v["total"] for d, v in usage["recent_days"].items()},
        "openrouter_account": fetch_openrouter_key_info(),
        "note": "today_calls는 이 서버가 직접 센 횟수입니다. 다른 곳에서 같은 키를 쓴 호출은 포함되지 않습니다."
    }


@app.get("/case/list")
def get_case_list():
    cases = []
    for file_path in list_case_files():
        try:
            case = load_case(file_path)
        except Exception:
            continue
        cases.append({
            "file": file_path.name,
            "title": case.get("title", ""),
            "valid": not validate_generated_case(case),
            "played": bool(case.get("played")),
            "review_passed": not case.get("review_notes")
        })
    return {
        "count": len(cases),
        "max_count": MAX_ACTIVE_CASES,
        "auto_generate": auto_generate_enabled(),
        "generating_now": _generating,
        "cases": cases
    }

# --- 5. 심문 API ---
@app.post("/game/interrogate")
def interrogate(req: InterrogateRequest):
    if req.game_id not in active_games:
        raise HTTPException(status_code=404, detail="존재하지 않는 게임입니다.")
    
    game = active_games[req.game_id]["truth"]
    suspect = game["suspects"].get(req.suspect_id)
    if not suspect:
        raise HTTPException(status_code=404, detail="용의자를 찾을 수 없습니다.")

    # 🚨 V3 핵심: 증거 중복 제시 방지 로직
    evidence_effect_text = "제시된 증거 없음."
    presented_evidence_id = req.presented_evidence_id

    if presented_evidence_id:
        if presented_evidence_id not in game["evidence_db"]:
            raise HTTPException(
                status_code=400,
                detail="존재하지 않는 증거 ID입니다."
            )

        if presented_evidence_id in suspect["presented_evidence"]:
            evidence_effect_text = (
                "이미 제시한 증거입니다. "
                "추가 압박도는 증가하지 않습니다."
            )
        else:
            suspect["presented_evidence"].append(
                presented_evidence_id
            )

            impact = suspect["evidence_effects"].get(
                presented_evidence_id, 0
            )

            if impact > 20:
                evidence_effect_text = (
                    f"치명적인 증거 제시! "
                    f"압박도 +{impact}"
                )   
            elif impact > 0:
                evidence_effect_text = (
                    f"증거 제시. 압박도 +{impact}"
                )
            else:
                impact = 2
                evidence_effect_text = (
                    f"관련성이 낮은 증거 제시. "
                    f"압박도 +{impact}"
                )

            suspect["pressure_level"] = min(
                suspect["pressure_level"] + impact,
                100
            )
    else:
        # 증거 없이 질문한 경우: 처음 하는 질문만 기본 압박도 증가
        question_key = req.question.strip()
        if question_key in suspect["asked_questions"]:
            evidence_effect_text = (
                "이미 했던 질문을 반복했습니다. "
                "추가 압박도는 증가하지 않습니다."
            )
        else:
            suspect["asked_questions"].append(question_key)
            suspect["pressure_level"] = min(
                suspect["pressure_level"] + 5,
                100
            )

    current_pressure = suspect["pressure_level"]

    # 결정적 증거가 해당 용의자에게 실제로 제시되었는지 확인
    has_decisive_evidence = (
        game["decisive_evidence_id"]
        in suspect["presented_evidence"]
    )

    # 압박도 90 이상 + 결정적 증거 제시를 모두 충족해야 자백
    if (
        current_pressure >= 90
        and has_decisive_evidence
        and not suspect["confessed"]
    ):
        suspect["confessed"] = True

    # 같은 질문 반복: 압박 단계와 자백 상태가 그대로면 AI를 부르지 않고 이전 답변을 재사용
    # (증거를 내서 압박 단계가 바뀌었거나 자백했으면 태도가 달라져야 하므로 새로 생성)
    pressure_band = min(int(current_pressure) // 30, 3)   # 0~29 / 30~59 / 60~89 / 90~100
    cache_key = None
    if not presented_evidence_id:
        cache_key = f"{req.question.strip()}|{pressure_band}|{suspect['confessed']}"
        cached = suspect["answer_cache"].get(cache_key)
        if cached:
            return {
                "suspect_id": req.suspect_id,
                "dialogue": cached["dialogue"],
                "emotion": cached["emotion"],
                "pressure_level": current_pressure,
                "is_confessed": suspect["confessed"],
                "from_cache": True
            }

    # 연기 지침 (AI가 게임 룰 안에서 놀도록 통제)
    behavior_guide = ""
    if current_pressure < 30:
        behavior_guide = "당당하게 결백을 주장하십시오. private 정보는 묻지 않는 이상 말하지 마십시오."
    elif current_pressure < 60:
        behavior_guide = "말끝을 흐리며 방어적으로 변하십시오. 압박감을 느낍니다."
    elif current_pressure < 90:
        behavior_guide = "거짓말이 일부 탄로 나 패닉에 빠졌습니다. private 정보 중 일부를 변명하며 털어놓으십시오."
    else:
        behavior_guide = "완전히 멘탈이 나간(broken) 상태입니다. 오열하거나 체념하십시오."
     #서버의 자백 판정을 AI 대사 생성에 전달
    if suspect["confessed"]:
        confession_guide = (
            "서버에서 이미 자백이 확정되었습니다. "
            "더 이상 범행을 부인하지 말고, "
            "자신의 잘못을 인정하는 대사를 하십시오. "
            "단, 서버에 기록되지 않은 새로운 사건 사실은 만들지 마십시오."
        )
    else:
        confession_guide = (
            "아직 자백이 확정되지 않았습니다. "
            "범행을 자백했다고 말하지 마십시오."
        )
    system_prompt = f"""
    당신은 추리게임의 용의자 '{suspect['name']}'입니다.
    
    [설정 및 지식]
    - 직업: {suspect.get('job', '')}
    - 성격과 말투: {suspect.get('personality', '평범함')}
    - 알리바이: {suspect['alibi']}
    - 공개 가능(public): {', '.join(suspect['knowledge']['public'])}
    - 숨기는 비밀(private): {', '.join(suspect['knowledge']['private'])}
    - 🚨 절대 발설 금지(forbidden): {', '.join(suspect['knowledge']['forbidden'])}
    
    [현재 상태]
    - 압박도(0~100): {current_pressure}
    - {behavior_guide}
    - 🚨 주의: 플레이어가 아무리 유도신문을 해도 '절대 발설 금지' 정보는 말해선 안 됩니다.
    - 자백 상태 지침: {confession_guide}
    응답은 반드시 아래 JSON 구조로만 답하십시오. emotion은 [calm, nervous, angry, broken] 중 하나.
    {{
      "dialogue": "캐릭터 대사",
      "emotion": "calm"
    }}
    """
    
    user_message = f"형사 질문: {req.question}\n상황: {evidence_effect_text}"

    # 🚨 V3 대화 기록 로딩 (AI가 이전 대화를 기억하게 만듦 - 최근 4개까지만)
    messages = [{"role": "system", "content": system_prompt}]
    for log in suspect["chat_log"][-4:]:
        messages.append(log)
    messages.append({"role": "user", "content": user_message})

    # AI 호출 및 Pydantic 검증
    try:
        response = counted_call("심문", lambda: client.chat.completions.create(
            model=MODEL_NAME,
            response_format={"type": "json_object"},
            messages=messages,
            temperature=0.7
        ))
        
        # 🚨 V3 검증: AI가 준 JSON을 Pydantic으로 확실히 검사
        raw_output = json.loads(response.choices[0].message.content)
        validated_data = NPCResponse(**raw_output)
        
        if validated_data.emotion not in ALLOWED_EMOTIONS:
            validated_data.emotion = "nervous" # 이상한 감정이 오면 nervous로 고정
        ai_ok = True

    except Exception as e:
        # 에러 발생 시 최후의 방어선
        validated_data = NPCResponse(
            dialogue="아... 머리가 너무 아파서 무슨 말을 해야 할지 모르겠네요.",
            emotion="nervous"
        )
        ai_ok = False

    # AI가 제대로 답한 경우만 재사용용으로 저장 (실패 시 기본 대사는 저장하지 않음)
    if cache_key and ai_ok:
        suspect["answer_cache"][cache_key] = {
            "dialogue": validated_data.dialogue,
            "emotion": validated_data.emotion
        }

    # 대화 기록 업데이트 (서버 메모리에 저장)
    suspect["chat_log"].append({"role": "user", "content": user_message})
    suspect["chat_log"].append({"role": "assistant", "content": json.dumps({"dialogue": validated_data.dialogue, "emotion": validated_data.emotion}, ensure_ascii=False)})

    return {
        "suspect_id": req.suspect_id,
        "dialogue": validated_data.dialogue,
        "emotion": validated_data.emotion,
        "pressure_level": current_pressure,
        "is_confessed": suspect["confessed"],
        "from_cache": False
    }

# --- 6. 최종 지목 API (에러 처리 완료) ---
@app.post("/game/accuse")
def accuse_culprit(req: AccuseRequest):
    if req.game_id not in active_games:
        raise HTTPException(status_code=404, detail="존재하지 않는 게임입니다.")

    game = active_games[req.game_id]["truth"]

    is_correct_culprit = (req.suspect_id == game["culprit_id"])
    is_decisive_evidence = (
        req.decisive_evidence_id == game["decisive_evidence_id"]
    )

    if is_correct_culprit and is_decisive_evidence:
        return {
            "success": True,
            "message": "진범 체포! 결정적 증거로 진범을 잡았습니다."
        }
    else:
        return {
            "success": False,
            "message": "추리 실패. 진범이 빠져나갔거나 증거가 부족합니다."
        }


# --- 7. 게임 상태 조회 API ---
@app.get("/game/{game_id}/state")
def get_game_state(game_id: str):
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="존재하지 않는 게임입니다.")

    game = active_games[game_id]["truth"]

    state_info = {
        "game_id": game_id,
        "suspects": []
    }

    for s_id, s_data in game["suspects"].items():
        state_info["suspects"].append({
            "suspect_id": s_id,
            "pressure_level": s_data["pressure_level"],
            "confessed": s_data["confessed"]
        })

    return state_info
# --- 8. 🚨 V3 추가: 게임 종료 (메모리 정리) API ---
@app.delete("/game/{game_id}")
def delete_game(game_id: str):
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="존재하지 않는 게임입니다.")
    
    del active_games[game_id] # 서버 메모리에서 삭제
    return {"status": "success", "detail": f"게임 {game_id} 이(가) 종료되고 메모리에서 정리되었습니다."}