
from typing import Any


# 단서 역할 태그와 사건당 허용 개수 (최소, 최대)
CLUE_ROLE_LIMITS = {
    "결정적": (2, 3),   # 범인만 가리키는 단서
    "정황": (2, 3),     # 범인 쪽으로 기울게 하는 단서
    "알리바이": (2, 2), # 무고한 용의자 2명의 결백 증명 (1명당 1개)
    "모순": (2, 3),     # 특정 거짓 진술을 반박하는 단서
    "미스리드": (1, 2), # 무고한 사람을 의심하게 만드는 함정
}

SUSPECT_COUNT = 3
MIN_CLUES = 9
MAX_CLUES = 12


def validate_case(server_truth: dict) -> list[str]:
    """
    사건 데이터가 기본 규칙을 만족하는지 검사합니다.
    문제가 없으면 빈 리스트를 반환하고,
    문제가 있으면 오류 메시지 목록을 반환합니다.
    """
    errors: list[str] = []

    # 1. 필수 데이터 확인
    required_keys = {
        "culprit_id",
        "decisive_evidence_id",
        "suspects",
        "evidence_db",
    }

    for key in required_keys:
        if key not in server_truth:
            errors.append(f"필수 데이터가 없습니다: {key}")

    # 필수 데이터가 없으면 아래 검사를 진행할 수 없습니다.
    if errors:
        return errors

    suspects = server_truth["suspects"]
    evidence_db = server_truth["evidence_db"]
    culprit_id = server_truth["culprit_id"]
    decisive_evidence_id = server_truth["decisive_evidence_id"]

    # 2. 용의자와 증거 목록이 올바른 자료형인지 확인
    if not isinstance(suspects, dict) or not suspects:
        errors.append("suspects는 비어 있지 않은 딕셔너리여야 합니다.")
        return errors

    if not isinstance(evidence_db, dict) or not evidence_db:
        errors.append("evidence_db는 비어 있지 않은 딕셔너리여야 합니다.")
        return errors

    # 3. 범인 ID가 실제 용의자인지 확인
    if culprit_id not in suspects:
        errors.append(
            f"범인 ID {culprit_id}가 용의자 목록에 없습니다."
        )

    # 4. 결정적 증거가 실제로 존재하는지 확인
    if decisive_evidence_id not in evidence_db:
        errors.append(
            f"결정적 증거 {decisive_evidence_id}가 증거 목록에 없습니다."
        )

    # 5. 각 용의자의 필수 정보 및 압박도 확인
    for suspect_id, suspect in suspects.items():
        if not isinstance(suspect, dict):
            errors.append(f"용의자 {suspect_id}의 데이터가 올바르지 않습니다.")
            continue

        for key in (
            "name",
            "alibi",
            "knowledge",
            "evidence_effects",
            "pressure_level",
        ):
            if key not in suspect:
                errors.append(
                    f"용의자 {suspect_id}에게 필수 항목 {key}가 없습니다."
                )

        pressure = suspect.get("pressure_level")

        if (
            isinstance(pressure, bool)
            or not isinstance(pressure, (int, float))
            or not 0 <= pressure <= 100
        ):
            errors.append(
                f"용의자 {suspect_id}의 압박도는 0~100 사이의 숫자여야 합니다."
            )

        # 6. 증거 효과가 실제 증거 ID와 연결되는지 확인
        effects = suspect.get("evidence_effects")

        if not isinstance(effects, dict):
            errors.append(
                f"용의자 {suspect_id}의 evidence_effects가 딕셔너리가 아닙니다."
            )
            continue

        for evidence_id, impact in effects.items():
            if evidence_id not in evidence_db:
                errors.append(
                    f"용의자 {suspect_id}의 증거 효과에 "
                    f"존재하지 않는 증거 {evidence_id}가 있습니다."
                )

            if (
                isinstance(impact, bool)
                or not isinstance(impact, (int, float))
                or impact < 0
            ):
                errors.append(
                    f"용의자 {suspect_id}의 증거 {evidence_id} "
                    "압박도 효과는 0 이상의 숫자여야 합니다."
                )

    return errors


def _is_filled_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_generated_case(server_truth: dict) -> list[str]:
    """
    AI가 생성한 사건을 검사합니다.
    validate_case()의 기본 검사에 더해
    용의자 수, 단서 역할 태그, 범인과 단서의 연결 관계를 확인합니다.
    """
    # 1. 기본 검사를 먼저 통과해야 합니다.
    errors = validate_case(server_truth)
    if errors:
        return errors

    suspects = server_truth["suspects"]
    evidence_db = server_truth["evidence_db"]
    culprit_id = server_truth["culprit_id"]
    decisive_evidence_id = server_truth["decisive_evidence_id"]
    innocent_ids = [s_id for s_id in suspects if s_id != culprit_id]

    # 2. 사건 개요 확인
    for key in ("title", "case_summary"):
        if not _is_filled_text(server_truth.get(key)):
            errors.append(f"사건 정보 {key}가 비어 있습니다.")

    # 3. 용의자는 정확히 3명
    if len(suspects) != SUSPECT_COUNT:
        errors.append(
            f"용의자는 {SUSPECT_COUNT}명이어야 합니다. (현재 {len(suspects)}명)"
        )

    # 4. 용의자별 설정이 비어 있지 않은지 확인
    for suspect_id, suspect in suspects.items():
        for key in ("name", "job", "personality", "description", "alibi"):
            if not _is_filled_text(suspect.get(key)):
                errors.append(f"용의자 {suspect_id}의 {key}가 비어 있습니다.")

        knowledge = suspect.get("knowledge")
        if not isinstance(knowledge, dict):
            errors.append(f"용의자 {suspect_id}의 knowledge가 딕셔너리가 아닙니다.")
            continue

        for key in ("public", "private"):
            if not knowledge.get(key):
                errors.append(f"용의자 {suspect_id}의 {key} 정보가 비어 있습니다.")

    # 5. 범인은 자신이 범인이라는 사실을 발설 금지로 가져야 합니다.
    culprit_knowledge = suspects[culprit_id].get("knowledge", {})
    if not culprit_knowledge.get("forbidden"):
        errors.append("범인의 forbidden(발설 금지) 정보가 비어 있습니다.")

    # 6. 단서 개수 확인
    if not MIN_CLUES <= len(evidence_db) <= MAX_CLUES:
        errors.append(
            f"단서는 {MIN_CLUES}~{MAX_CLUES}개여야 합니다. (현재 {len(evidence_db)}개)"
        )

    # 7. 단서별 필수 항목과 역할 태그 확인
    role_counts = {role: 0 for role in CLUE_ROLE_LIMITS}
    alibi_targets: list[int] = []
    culprit_contradiction = False

    for evidence_id, evidence in evidence_db.items():
        if not isinstance(evidence, dict):
            errors.append(f"단서 {evidence_id}의 데이터가 올바르지 않습니다.")
            continue

        for key in ("name", "desc", "found_at"):
            if not _is_filled_text(evidence.get(key)):
                errors.append(f"단서 {evidence_id}의 {key}가 비어 있습니다.")

        # 단서 이름에 역할 태그가 드러나면 정답이 보이므로 금지
        clue_name = evidence.get("name") or ""
        for hidden_word in (*CLUE_ROLE_LIMITS, "범인"):
            if isinstance(clue_name, str) and hidden_word in clue_name:
                errors.append(
                    f"단서 {evidence_id}의 이름 '{clue_name}'에 '{hidden_word}'가 드러나 있습니다."
                )

        role = evidence.get("role")
        if role not in CLUE_ROLE_LIMITS:
            errors.append(
                f"단서 {evidence_id}의 역할 태그 '{role}'가 올바르지 않습니다."
            )
            continue
        role_counts[role] += 1

        related_id = evidence.get("related_suspect_id")
        if related_id not in suspects:
            errors.append(
                f"단서 {evidence_id}의 관련 용의자 {related_id}가 용의자 목록에 없습니다."
            )
            continue

        # 결정적·정황 단서는 범인을 가리켜야 합니다.
        if role in ("결정적", "정황") and related_id != culprit_id:
            errors.append(
                f"{role} 단서 {evidence_id}가 범인이 아닌 용의자 {related_id}를 가리킵니다. "
                f"(고치는 법: 범인 {culprit_id}를 가리키는 내용으로 바꾸고 related_suspect_id를 {culprit_id}로)"
            )

        # 알리바이·미스리드 단서는 무고한 용의자와 연결되어야 합니다.
        if role in ("알리바이", "미스리드") and related_id == culprit_id:
            errors.append(
                f"{role} 단서 {evidence_id}가 범인과 연결되어 있습니다. "
                "(고치는 법: 무고한 용의자와 연결된 내용으로 바꾸기)"
            )

        if role == "알리바이":
            alibi_targets.append(related_id)

        if role == "모순" and related_id == culprit_id:
            culprit_contradiction = True

    # 8. 역할 태그별 개수 확인
    for role, (low, high) in CLUE_ROLE_LIMITS.items():
        count = role_counts[role]
        if not low <= count <= high:
            errors.append(
                f"{role} 단서는 {low}~{high}개여야 합니다. (현재 {count}개)"
            )

    # 9. 무고한 용의자마다 알리바이 단서가 1개씩 있어야 합니다.
    for innocent_id in innocent_ids:
        if alibi_targets.count(innocent_id) != 1:
            errors.append(
                f"무고한 용의자 {innocent_id}의 알리바이 단서는 1개여야 합니다."
            )

    # 10. 범인의 거짓 진술을 깨는 모순 단서가 있어야 합니다.
    if not culprit_contradiction:
        errors.append("범인의 진술을 반박하는 모순 단서가 없습니다.")

    # 11. 결정적 증거는 '결정적' 태그여야 하고, 범인을 충분히 압박해야 합니다.
    decisive = evidence_db.get(decisive_evidence_id, {})
    if decisive.get("role") != "결정적":
        errors.append(
            f"결정적 증거 {decisive_evidence_id}의 역할 태그가 '결정적'이 아닙니다."
        )

    culprit_effects = suspects[culprit_id].get("evidence_effects", {})
    if culprit_effects.get(decisive_evidence_id, 0) < 30:
        errors.append(
            f"범인에게 결정적 증거 {decisive_evidence_id}의 압박도 효과는 30 이상이어야 합니다."
        )

    return errors
