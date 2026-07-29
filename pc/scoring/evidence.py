# pc/scoring/evidence.py
"""
스코어링 근거(Evidence) JSON 빌더 모듈
(SCORING_V2_DESIGN.md §13, P1-AC10).
"""
import json
from typing import Dict, Any

def build_evidence_json(
    complex_code: str,
    area_type: str,
    peer_group_key: str,
    peer_group_n: int,
    block_scores: Dict[str, float],
    factor_z_maps: Dict[str, Dict[str, float]],
    raw_score: float,
    base_score: float,
    risk_multiplier: float,
    market_score: float,
    gate_status: str,
    gate_reason: Any
) -> str:
    """
    UI 및 모달 팝업에서 조회할 수 있는 근거 딕셔너리를 JSON 문자열로 직렬화한다.
    """
    data = {
        "target": {
            "complex_code": complex_code,
            "area_type": area_type
        },
        "peer_group": {
            "key": peer_group_key,
            "sample_count": peer_group_n
        },
        "blocks": {
            "A_value": round(block_scores.get("A", 0.0), 3),
            "B_flow": round(block_scores.get("B", 0.0), 3),
            "C_location": round(block_scores.get("C", 0.0), 3),
            "D_quality": round(block_scores.get("D", 0.0), 3)
        },
        "factors": {
            k: {fk: round(fv, 3) for fk, fv in v.items()}
            for k, v in factor_z_maps.items()
        },
        "summary": {
            "raw_score": round(raw_score, 3),
            "base_score": round(base_score, 1),
            "risk_multiplier": round(risk_multiplier, 2),
            "market_score": round(market_score, 1),
            "gate_status": gate_status,
            "gate_reason": gate_reason
        }
    }
    return json.dumps(data, ensure_ascii=False)
