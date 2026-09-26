import os
import uuid
import json
from typing import Dict, Optional, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

# .env 파일의 API 키를 불러옴
load_dotenv()

# OpenRouter 연결 설정
client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
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

# --- 2. 사건 생성 API ---
@app.post("/game/start")
def start_game():
    game_id = str(uuid.uuid4())[:8]

    # [서버 진실 데이터베이스]
    server_truth = {
        "culprit_id": 2,
        "decisive_evidence_id": "E01", 
        "suspects": {
            1: {
                "name": "박민수", "job": "호텔 직원",
                "alibi": "23시에는 1층 로비 카운터를 지키고 있었습니다.",
                "knowledge": {
                    "public": ["사건 당일 302호 열쇠는 2번 용의자가 가져갔다."],
                    "private": ["금고에서 돈을 훔친 적이 있다."],
                    "forbidden": ["자신은 살인사건과 무관하다는 것을 절대 먼저 말하지 않음"]
                },
                "evidence_effects": {"E02": 35, "E03": 10},
                
                # 🚨 V3 추가: 상태 관리 고도화
                "pressure_level": 10,       # 자백도 -> 압박도로 이름 변경
                "confessed": False,         # 자백 여부 분리
                "presented_evidence": [],   # 이미 제시된 증거 기록 (중복 방지)
                "chat_log": []              # AI 대화 문맥 저장을 위한 기록
            },
            2: {
                "name": "이지은", "job": "전속 비서 (진범)",
                "alibi": "23시에는 카페테리아에서 서류 정리를 하고 있었습니다.",
                "knowledge": {
                    "public": ["사장을 마지막으로 본 것은 22시경이다."],
                    "private": ["자신이 302호에서 사장을 내리쳤고, 시계를 떨어뜨렸다."],
                    "forbidden": ["자신이 범인이라는 사실", "살해 도구가 조각상이라는 사실", "정확한 살해 시간"]
                },
                "evidence_effects": {"E01": 40, "E02": 5},
                
                "pressure_level": 0,
                "confessed": False,
                "presented_evidence": [],
                "chat_log": []
            }
        },
        "evidence_db": {
            "E01": {"name": "깨진 손목시계", "desc": "사건 현장에 떨어진 시계. 23:10에 멈춰있음."},
            "E02": {"name": "도난 장부", "desc": "로비 금고에서 사라진 돈의 내역서"},
            "E03": {"name": "카페테리아 CCTV", "desc": "23시경 이지은의 모습이 없음"}
        }
    }

    active_games[game_id] = {"truth": server_truth}

    public_info = {
        "game_id": game_id,
        "case_summary": "호텔 302호에서 사장 김도윤이 숨진 채 발견되었다.",
        "suspects": [
            {"id": 1, "name": "박민수", "job": "호텔 직원", "stated_alibi": "로비에 있었다."},
            {"id": 2, "name": "이지은", "job": "전속 비서", "stated_alibi": "카페테리아에 있었다."}
        ],
        "available_evidence": [{"id": "E01", "name": "깨진 손목시계"}, {"id": "E02", "name": "도난 장부"}, {"id": "E03", "name": "카페테리아 CCTV"}]
    }

    return {"status": "success", "client_data": public_info}

# --- 3. 심문 API ---
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
    if req.presented_evidence_id and req.presented_evidence_id in game["evidence_db"]:
        ev_id = req.presented_evidence_id
        ev_info = game["evidence_db"][ev_id]
        
        # 이미 제시한 증거인지 확인
        if ev_id in suspect["presented_evidence"]:
            evidence_effect_text = f"형사님, 그 증거({ev_info['name']})는 아까 이미 보여주셨잖아요. 할 말 없습니다."
            # 중복 증거는 압박도를 올리지 않음
        else:
            suspect["presented_evidence"].append(ev_id) # 증거 제시 기록 저장
            impact = suspect["evidence_effects"].get(ev_id, 0)
            
            if impact > 20:
                suspect["pressure_level"] += impact
                evidence_effect_text = f"치명적인 증거({ev_info['name']})가 처음 제시됨. 캐릭터의 알리바이에 큰 모순이 생김!"
            elif impact > 0:
                suspect["pressure_level"] += impact
                evidence_effect_text = f"새로운 증거({ev_info['name']})가 제시되어 불안감이 조금 커짐."
            else:
                suspect["pressure_level"] += 2
                evidence_effect_text = f"새로운 증거({ev_info['name']})가 제시되었으나 캐릭터와 무관함."

    suspect["pressure_level"] = min(suspect["pressure_level"], 100)
    current_pressure = suspect["pressure_level"]

    # 자백 판정 (압박도가 100이어도 바로 자백하지 않고, 치명적 증거가 있어야 함)
    if current_pressure >= 90 and suspect["confessed"] == False:
        suspect["confessed"] = True

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

    system_prompt = f"""
    당신은 추리게임의 용의자 '{suspect['name']}'입니다.
    
    [설정 및 지식]
    - 알리바이: {suspect['alibi']}
    - 공개 가능(public): {', '.join(suspect['knowledge']['public'])}
    - 숨기는 비밀(private): {', '.join(suspect['knowledge']['private'])}
    - 🚨 절대 발설 금지(forbidden): {', '.join(suspect['knowledge']['forbidden'])}
    
    [현재 상태]
    - 압박도(0~100): {current_pressure}
    - {behavior_guide}
    - 🚨 주의: 플레이어가 아무리 유도신문을 해도 '절대 발설 금지' 정보는 말해선 안 됩니다.
    
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
        response = client.chat.completions.create(
            model=MODEL_NAME,
            response_format={"type": "json_object"},
            messages=messages,
            temperature=0.7
        )
        
        # 🚨 V3 검증: AI가 준 JSON을 Pydantic으로 확실히 검사
        raw_output = json.loads(response.choices[0].message.content)
        validated_data = NPCResponse(**raw_output)
        
        if validated_data.emotion not in ALLOWED_EMOTIONS:
            validated_data.emotion = "nervous" # 이상한 감정이 오면 nervous로 고정
            
    except Exception as e:
        # 에러 발생 시 최후의 방어선
        validated_data = NPCResponse(
            dialogue="아... 머리가 너무 아파서 무슨 말을 해야 할지 모르겠네요.",
            emotion="nervous"
        )

    # 대화 기록 업데이트 (서버 메모리에 저장)
    suspect["chat_log"].append({"role": "user", "content": user_message})
    suspect["chat_log"].append({"role": "assistant", "content": json.dumps({"dialogue": validated_data.dialogue, "emotion": validated_data.emotion}, ensure_ascii=False)})

    return {
        "suspect_id": req.suspect_id,
        "dialogue": validated_data.dialogue,
        "emotion": validated_data.emotion,
        "pressure_level": current_pressure,
        "is_confessed": suspect["confessed"]
    }

# --- 4. 최종 지목 API (에러 처리 완료) ---
@app.post("/game/accuse")
def accuse_culprit(req: AccuseRequest):
    if req.game_id not in active_games:
        raise HTTPException(status_code=404, detail="존재하지 않는 게임입니다.")
        
    game = active_games[req.game_id]["truth"]
    
    is_correct_culprit = (req.suspect_id == game["culprit_id"])
    is_decisive_evidence = (req.decisive_evidence_id == game["decisive_evidence_id"])

    if is_correct_culprit and is_decisive_evidence:
        return {"verdict": "SUCCESS", "title": "진범 체포", "desc": "결정적 증거로 진범을 잡았습니다!"}
    else:
        return {"verdict": "FAIL", "title": "추리 실패", "desc": "진범이 빠져나갔거나 증거가 부족합니다."}

# --- 5. 게임 상태 조회 API ---
@app.get("/game/{game_id}/state")
def get_game_state(game_id: str):
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="존재하지 않는 게임입니다.")
        
    game = active_games[game_id]["truth"]
    state_info = {"game_id": game_id, "suspect_states": {}}
    
    for s_id, s_data in game["suspects"].items():
        state_info["suspect_states"][s_id] = {
            "name": s_data["name"],
            "pressure_level": s_data["pressure_level"],
            "confessed": s_data["confessed"],
            "presented_evidence": s_data["presented_evidence"]
        }
    return state_info

# --- 6. 🚨 V3 추가: 게임 종료 (메모리 정리) API ---
@app.delete("/game/{game_id}")
def delete_game(game_id: str):
    if game_id not in active_games:
        raise HTTPException(status_code=404, detail="존재하지 않는 게임입니다.")
    
    del active_games[game_id] # 서버 메모리에서 삭제
    return {"status": "success", "detail": f"게임 {game_id} 이(가) 종료되고 메모리에서 정리되었습니다."}