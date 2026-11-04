"""离线评测本地规则基线，计算任务要求的三个指标。

- 格式合规率：输出能否通过结果 JSON 往返与反幻觉逐字核验；
- 证据分类准确率：line 基线对每条要求的判定（缺口 / 三类证据）与标准答案一致的比例；
- 幻觉率：输出中存在「简历里没有的证据片段」或「岗位里不存在的匹配要求」的比例。

运行方式（在 backend 目录）：
    python -m pytest tests/agents/diagnosis/test_eval.py -s
    或 python tests/agents/diagnosis/evaluate.py（需能 import app）
"""

import json
from pathlib import Path

from app.agents.diagnosis.agent import apply_confidence_filter, rule_diagnose, validate_diagnosis
from app.agents.diagnosis.schemas import DiagnosisResult


def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def _predicted_verdicts(result: DiagnosisResult) -> dict[str, str | None]:
    verdicts: dict[str, str | None] = {}
    for item in result.gaps:
        verdicts[item.requirement_id] = None
    for item in result.strengths + result.pending_verification:
        verdicts[item.requirement_id] = item.evidence_type.value if item.evidence_type else None
    return verdicts


def _is_hallucinated(item, resume_text: str, requirements: list[dict]) -> bool:
    if item.evidence_excerpt and item.evidence_excerpt not in resume_text:
        return True
    text = item.matched_requirement
    if not any(text == req["text"] or text in req["quote"] for req in requirements):
        return True
    return False


def evaluate(cases: list[dict]) -> dict:
    format_ok = 0
    total_items = 0
    hallucinated = 0
    total_requirements = 0
    agreements = 0
    for case in cases:
        resume = case["resume_text"]
        requirements = case["job_requirements"]
        result = apply_confidence_filter(rule_diagnose(resume, requirements))
        try:
            dumped = result.model_dump_json()
            DiagnosisResult.model_validate_json(dumped)
            validate_diagnosis(json.loads(dumped), resume, requirements)
            format_ok += 1
        except Exception:
            pass
        for item in result.strengths + result.gaps + result.pending_verification:
            total_items += 1
            if _is_hallucinated(item, resume, requirements):
                hallucinated += 1
        predicted = _predicted_verdicts(result)
        for entry in case["golden"]:
            total_requirements += 1
            if entry["evidence_type"] == predicted.get(entry["requirement_id"], None):
                agreements += 1
    return {
        "cases": len(cases),
        "format_compliance_rate": round(format_ok / len(cases), 4),
        "hallucination_rate": round(hallucinated / total_items, 4),
        "classification_accuracy": round(agreements / total_requirements, 4),
        "agreements": agreements,
        "total_requirements": total_requirements,
    }


def main() -> None:
    cases = load_cases(Path(__file__).parent / "golden.json")
    print(json.dumps(evaluate(cases), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()