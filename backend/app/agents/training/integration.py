"""Adapt persisted B diagnoses to C inputs without accepting browser evidence."""

import json
import re

from fastapi import HTTPException
from pydantic import ValidationError

from app.agents.diagnosis.schemas import DiagnosisResult
from app.agents.training.schemas import DiagnosisPayload, Gap


def diagnosis_gaps(database, diagnosis: dict, user_id: str) -> list[Gap]:
    payload = json.loads(diagnosis["result_payload"])
    try:
        # Retain the explicitly versioned C experimental input contract.
        return DiagnosisPayload.model_validate(payload).gaps
    except ValidationError:
        if not {"schema_version", "gaps"} <= payload.keys():
            raise ValueError("Missing diagnosis result contract")
        result = DiagnosisResult.model_validate(payload)
    with database.connect() as connection:
        job = connection.execute(
            "SELECT source_text, payload FROM job_analysis_tasks WHERE id=? AND user_id=?",
            (diagnosis["job_analysis_id"], user_id),
        ).fetchone()
    if job is None:
        raise HTTPException(404, {"code": "job_not_found", "message": "关联岗位不存在"})
    requirements = json.loads(job["payload"]).get("requirements", [])
    gaps = []
    for item in result.gaps:
        matches = [
            req
            for req in requirements
            if (not item.requirement_id or req["id"] == item.requirement_id)
            and (
                item.matched_requirement == req["text"] or item.matched_requirement in req["quote"]
            )
        ]
        if len(matches) != 1:
            raise ValueError("Diagnosis requirement does not match its parent job")
        req = matches[0]
        excerpt = req["quote"]
        start = req.get("source_start", job["source_text"].find(excerpt))
        if start < 0 or job["source_text"][start : start + len(excerpt)] != excerpt:
            raise ValueError("Diagnosis requirement evidence is not verbatim")
        is_sql = re.search(r"\bsql\b|mysql|postgres|数据库|关系型|join", req["text"], re.I)
        gaps.append(
            Gap(
                requirement_id=req["id"],
                skill_id="sql.join_aggregation" if is_sql else "unsupported",
                description=item.matched_requirement,
                source=f"job_analysis:{diagnosis['job_analysis_id']}",
                excerpt=excerpt,
                start=start,
                end=start + len(excerpt),
            )
        )
    return gaps
