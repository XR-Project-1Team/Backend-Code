import sys
import json
import threading
from datetime import date, timedelta
from pathlib import Path

# AI 호출 횟수를 날짜별로 저장하는 파일 (서버를 껐다 켜도 유지)
USAGE_FILE = Path(__file__).parent / "ai_usage.json"
KEEP_DAYS = 30

_lock = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_ai_call(kind: str, ok: bool) -> None:
    """AI 호출 1번을 기록합니다. kind 예: 심문, 사건 생성, 사건 검토"""
    today = date.today().isoformat()
    with _lock:
        data = _load()
        day = data.setdefault(today, {"total": 0, "failed": 0, "by_kind": {}})
        day["total"] += 1
        if not ok:
            day["failed"] += 1
        day["by_kind"][kind] = day["by_kind"].get(kind, 0) + 1

        # 오래된 기록은 정리 (최근 KEEP_DAYS일만 보관)
        oldest = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        data = {d: v for d, v in data.items() if d >= oldest}

        USAGE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def counted_call(kind: str, func):
    """func()를 실행하면서 성공·실패를 기록합니다. 실패하면 오류를 그대로 다시 던집니다."""
    try:
        result = func()
    except Exception:
        record_ai_call(kind, ok=False)
        raise
    record_ai_call(kind, ok=True)
    return result


def get_usage(days: int = 7) -> dict:
    """오늘과 최근 며칠의 호출 기록을 돌려줍니다."""
    data = _load()
    today = date.today().isoformat()
    empty = {"total": 0, "failed": 0, "by_kind": {}}
    recent = {}
    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        recent[d] = data.get(d, empty)
    return {"today": today, "today_usage": data.get(today, empty), "recent_days": recent}


# 터미널에서 바로 확인:  python usage_counter.py
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    usage = get_usage()
    t = usage["today_usage"]
    print(f"오늘({usage['today']}) AI 호출: {t['total']}번 (실패 {t['failed']}번)")
    for kind, count in t["by_kind"].items():
        print(f"  - {kind}: {count}번")
    print("\n최근 7일:")
    for d, v in usage["recent_days"].items():
        print(f"  {d}: {v['total']}번")
