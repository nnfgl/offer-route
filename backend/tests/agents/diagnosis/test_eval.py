from pathlib import Path

from evaluate import evaluate, load_cases


def test_golden_eval_metrics():
    cases = load_cases(Path(__file__).parent / "golden.json")
    metrics = evaluate(cases)
    print("\n[diagnosis eval]", metrics)
    assert metrics["cases"] >= 5
    assert metrics["format_compliance_rate"] == 1.0
    assert metrics["hallucination_rate"] == 0.0
    assert metrics["classification_accuracy"] >= 0.7