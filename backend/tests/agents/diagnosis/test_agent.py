import asyncio
import json

import httpx
import pytest

from app.agents.diagnosis.agent import (
    apply_confidence_filter,
    diagnose_with_model,
    rule_diagnose,
    validate_diagnosis,
)
from app.agents.diagnosis.prompting import load_template
from app.agents.diagnosis.schemas import DiagnosisItem, DiagnosisResult, EvidenceType
from app.core.config import Settings
from app.core.model_client import DeepSeekClient, ModelFailure


def reqs(*texts: str) -> list[dict]:
    return [
        {
            "id": f"R{index}",
            "text": text,
            "priority": "required",
            "category": "skill",
            "quote": text,
        }
        for index, text in enumerate(texts, start=1)
    ]


def test_rule_diagnosis_matches_strengths_and_gaps():
    result = rule_diagnose(
        "熟悉 Python，负责推荐系统开发，接口 QPS 提升 30%。", reqs("熟悉 Python", "熟悉 Redis 缓存")
    )
    assert {item.requirement_id for item in result.gaps} == {"R2"}
    (strength,) = result.strengths
    assert strength.requirement_id == "R1"
    assert strength.evidence_type == EvidenceType.TASK_VERIFIED
    assert strength.evidence_excerpt in "熟悉 Python，负责推荐系统开发，接口 QPS 提升 30%。"


def test_confidence_filter_moves_low_confidence_to_pending():
    result = DiagnosisResult(
        strengths=[
            DiagnosisItem(
                requirement_id="R1",
                claim_content="c",
                matched_requirement="熟悉 Python",
                evidence_type=EvidenceType.TASK_VERIFIED,
                evidence_excerpt="Python",
                confidence_score=0.9,
            ),
            DiagnosisItem(
                requirement_id="R2",
                claim_content="c",
                matched_requirement="熟悉 Docker",
                evidence_type=EvidenceType.SELF_CLAIMED,
                evidence_excerpt="Docker",
                confidence_score=0.6,
            ),
        ]
    )
    filtered = apply_confidence_filter(result)
    assert [item.requirement_id for item in filtered.strengths] == ["R1"]
    assert [item.requirement_id for item in filtered.pending_verification] == ["R2"]


def test_validate_diagnosis_rejects_fabrication():
    requirements = reqs("熟悉 Python")
    resume = "熟悉 Python。"
    with pytest.raises(ValueError):
        validate_diagnosis(
            {
                "strengths": [
                    {
                        "requirement_id": "R1",
                        "claim_content": "c",
                        "matched_requirement": "熟悉 Python",
                        "evidence_type": "task_verified",
                        "evidence_excerpt": "不存在的片段",
                        "confidence_score": 0.9,
                    }
                ]
            },
            resume,
            requirements,
        )
    with pytest.raises(ValueError):
        validate_diagnosis(
            {
                "strengths": [
                    {
                        "requirement_id": "R1",
                        "claim_content": "c",
                        "matched_requirement": "不存在的伪要求",
                        "evidence_type": "task_verified",
                        "evidence_excerpt": "熟悉 Python",
                        "confidence_score": 0.9,
                    }
                ]
            },
            resume,
            requirements,
        )
    result = validate_diagnosis(
        {
            "gaps": [
                {
                    "requirement_id": "R1",
                    "claim_content": "c",
                    "matched_requirement": "熟悉 Python",
                    "evidence_type": "task_verified",
                    "evidence_excerpt": "熟悉 Python",
                    "confidence_score": 0.9,
                }
            ]
        },
        resume,
        requirements,
    )
    assert result.gaps[0].evidence_type is None and result.gaps[0].evidence_excerpt is None


def model_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


VALID = {
    "schema_version": 1,
    "summary": "",
    "strengths": [
        {
            "requirement_id": "R1",
            "claim_content": "c",
            "matched_requirement": "熟悉 Python",
            "evidence_type": "task_verified",
            "evidence_excerpt": "熟悉 Python",
            "confidence_score": 0.9,
        }
    ],
    "gaps": [],
    "pending_verification": [],
}


def content_of(request: httpx.Request) -> str:
    return json.loads(request.content)["messages"][1]["content"]


def test_fix_loop_reprompts_and_succeeds():
    seen: list[httpx.Request] = []

    def respond(request):
        seen.append(request)
        if len(seen) == 1:
            return model_response("not-json")
        return model_response(json.dumps(VALID))

    transport = httpx.MockTransport(respond)
    client = DeepSeekClient(Settings(_env_file=None, DEEPSEEK_API_KEY="test"), transport)
    result, usage = asyncio.run(
        diagnose_with_model(client, load_template(), "熟悉 Python。", reqs("熟悉 Python"))
    )
    assert result.strengths[0].evidence_type == EvidenceType.TASK_VERIFIED
    assert usage.attempts == 2


def test_fix_loop_is_bounded():
    calls: list[httpx.Request] = []

    def respond(request):
        calls.append(request)
        return model_response("still-not-json")

    transport = httpx.MockTransport(respond)
    client = DeepSeekClient(Settings(_env_file=None, DEEPSEEK_API_KEY="test"), transport)
    with pytest.raises(ModelFailure) as exc:
        asyncio.run(
            diagnose_with_model(client, load_template(), "熟悉 Python。", reqs("熟悉 Python"))
        )
    assert exc.value.code == "invalid_model_output"
    assert exc.value.usage.attempts == 2
    assert len(calls) == 2


def test_unrelated_metrics_do_not_upgrade_skill_evidence():
    result = apply_confidence_filter(
        rule_diagnose("熟悉 Python。\n兴趣：跑步成绩提升 10%。", reqs("熟悉 Python"))
    )
    assert not result.strengths
    assert result.pending_verification[0].evidence_type == EvidenceType.SELF_CLAIMED
    assert "跑步" not in result.pending_verification[0].evidence_excerpt


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_excerpt": None},
        {"evidence_type": None},
        {"requirement_id": "R2"},
    ],
)
def test_strengths_require_evidence_and_matching_requirement_id(changes):
    item = {**VALID["strengths"][0], **changes}
    with pytest.raises(ValueError):
        validate_diagnosis({"strengths": [item]}, "熟悉 Python", reqs("熟悉 Python", "熟悉 SQL"))


def test_invalid_output_never_resets_output_budget():
    calls = []

    def respond(request):
        calls.append(request)
        response = model_response("invalid")
        payload = json.loads(response.content)
        payload["usage"]["completion_tokens"] = 1800
        return httpx.Response(200, json=payload)

    client = DeepSeekClient(
        Settings(_env_file=None, DEEPSEEK_API_KEY="test"), httpx.MockTransport(respond)
    )
    with pytest.raises(ModelFailure) as raised:
        asyncio.run(
            diagnose_with_model(client, load_template(), "熟悉 Python", reqs("熟悉 Python"))
        )
    assert len(calls) == 2
    assert raised.value.usage.completion_tokens == 3600
