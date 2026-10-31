"""能力诊断 Agent 核心逻辑：证据核验、置信度过滤、本地规则基线与模型调用修复。

复用公共 model_client 的 DeepSeekClient.complete_json；
llm 返回非法 JSON / 结构不符时用 fix_json_prompt 自我修正（最多 2 次）。
"""

import re

from app.agents.diagnosis.prompting import render_fix_prompt, render_user_prompt
from app.agents.diagnosis.schemas import DiagnosisItem, DiagnosisResult, EvidenceType
from app.core.model_client import DeepSeekClient, ModelFailure, ModelUsage

CONFIDENCE_THRESHOLD = 0.7
FIX_LIMIT = 2

# 本地规则基线的保守关键词信号（仅作为离线兜底，复杂语义仍需 DeepSeek 与人工核对）。
_TASK_HINTS = (
    "提升", "降低", "增长", "减少", "%", "倍", "日活", "月活", "转化率",
    "通过率", "获奖", "测试通过", "上线", "指标", "压测", "吞吐",
)
_PORTFOLIO_HINTS = (
    "github", "gitlab", "gitee", "开源", "仓库", "作品集", "portfolio", "demo",
    "项目", "https://", "http://", ".com", ".io", ".cn", "论文", "专利",
)
_SKIP_KEYWORDS = {
    "熟悉", "掌握", "了解", "精通", "擅长", "具备", "具有", "负责", "参与", "能够", "可以",
    "要求", "优先", "使用", "用过", "经验", "能力", "相关", "以上", "以及", "并有", "至少",
    "一种", "框架", "技术", "工具", "优先考虑", "加分", "熟悉者",
}


def _matched_requirement_valid(matched: str, job_requirements: list[dict]) -> bool:
    for req in job_requirements:
        if matched == req["text"] or matched in req["quote"]:
            return True
    return False


def validate_diagnosis(
    payload: dict, resume_text: str, job_requirements: list[dict]
) -> DiagnosisResult:
    """Pydantic 结构校验 + 反幻觉逐字核验；能力缺口统一归一无证据字段。"""
    result = DiagnosisResult.model_validate(payload)
    valid_ids = {req["id"] for req in job_requirements}

    def check(item: DiagnosisItem, bucket: str) -> DiagnosisItem:
        if item.requirement_id is not None and item.requirement_id not in valid_ids:
            raise ValueError("Requirement id does not exist in the job requirements")
        if not _matched_requirement_valid(item.matched_requirement, job_requirements):
            raise ValueError("Matched requirement does not exist in the job requirements")
        if bucket == "gaps":
            return item.model_copy(update={"evidence_type": None, "evidence_excerpt": None})
        if item.evidence_excerpt and item.evidence_excerpt not in resume_text:
            raise ValueError("Evidence excerpt does not exist in the resume")
        return item

    return DiagnosisResult(
        schema_version=result.schema_version,
        summary=result.summary,
        strengths=[check(item, "strengths") for item in result.strengths],
        gaps=[check(item, "gaps") for item in result.gaps],
        pending_verification=[
            check(item, "pending_verification") for item in result.pending_verification
        ],
    )


def apply_confidence_filter(
    result: DiagnosisResult, threshold: float = CONFIDENCE_THRESHOLD
) -> DiagnosisResult:
    """confidence_score < threshold 的 strengths/gaps 迁入待验证项（待人工确认）。"""
    strengths, gaps, pending = [], [], list(result.pending_verification)
    for item in result.strengths:
        (pending if item.confidence_score < threshold else strengths).append(item)
    for item in result.gaps:
        (pending if item.confidence_score < threshold else gaps).append(item)
    return result.model_copy(
        update={"strengths": strengths, "gaps": gaps, "pending_verification": pending}
    )


def build_summary(result: DiagnosisResult) -> str:
    parts = []
    if result.strengths:
        parts.append(f"{len(result.strengths)} 项优势")
    if result.gaps:
        parts.append(f"{len(result.gaps)} 项能力缺口")
    if result.pending_verification:
        parts.append(f"{len(result.pending_verification)} 项待验证")
    return "、".join(parts) if parts else "未从简历中识别到可诊断信息"


def _keywords(*texts: str) -> list[str]:
    tokens: set[str] = set()
    for text in texts:
        if not text:
            continue
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]*|[\u4e00-\u9fff]{2,}", text):
            low = token.lower() if token.isascii() else token
            if low in _SKIP_KEYWORDS:
                continue
            tokens.add(low)
            if not token.isascii():
                for index in range(len(token) - 1):
                    bigram = token[index : index + 2]
                    if bigram not in _SKIP_KEYWORDS:
                        tokens.add(bigram)
    return sorted(tokens, key=len, reverse=True)


def _locate(resume_text: str, tokens: list[str]) -> tuple[str | None, int]:
    """大小写无关地在简历中定位关键词，返回原始词与起始位置。"""
    for token in tokens:
        if token.isascii():
            match = re.search(re.escape(token), resume_text, re.IGNORECASE)
            if match:
                return token, match.start()
        elif token in resume_text:
            return token, resume_text.index(token)
    return None, -1


def rule_diagnose(resume_text: str, job_requirements: list[dict]) -> DiagnosisResult:
    """保守本地基线：按关键词在简历中是否命中区分优势/缺口，证据分类走后置过滤。
    复杂语义与隐含要求仍需要人工核对；规则结果不标记为 AI 分析。"""
    strengths: list[DiagnosisItem] = []
    gaps: list[DiagnosisItem] = []
    for req in job_requirements:
        matched_requirement = req["text"] or req["quote"]
        hit, start = _locate(resume_text, _keywords(req["text"], req["quote"]))
        if hit is None:
            gaps.append(
                DiagnosisItem(
                    requirement_id=req["id"],
                    claim_content="未在简历中找到相关证据",
                    matched_requirement=matched_requirement,
                    evidence_type=None,
                    evidence_excerpt=None,
                    confidence_score=0.9,
                )
            )
            continue
        excerpt = resume_text[max(0, start - 16) : start + len(hit) + 32]
        if any(hint in resume_text for hint in _TASK_HINTS):
            kind, confidence = EvidenceType.TASK_VERIFIED, 0.92
        elif any(hint in resume_text for hint in _PORTFOLIO_HINTS):
            kind, confidence = EvidenceType.PORTFOLIO_SUPPORTED, 0.82
        else:
            kind, confidence = EvidenceType.SELF_CLAIMED, 0.62
        strengths.append(
            DiagnosisItem(
                requirement_id=req["id"],
                claim_content=f"简历中包含与「{req['text']}」匹配的内容",
                matched_requirement=matched_requirement,
                evidence_type=kind,
                evidence_excerpt=excerpt,
                confidence_score=confidence,
            )
        )
    result = DiagnosisResult(strengths=strengths, gaps=gaps)
    return result


def _merge_usage(base: ModelUsage, extra: ModelUsage) -> ModelUsage:
    return ModelUsage(
        attempts=base.attempts + extra.attempts,
        prompt_tokens=base.prompt_tokens + extra.prompt_tokens,
        completion_tokens=base.completion_tokens + extra.completion_tokens,
    )


async def diagnose_with_model(
    client: DeepSeekClient,
    template: dict,
    resume_text: str,
    job_requirements: list[dict],
) -> tuple[DiagnosisResult, ModelUsage]:
    """DeepSeek 路径；非法 JSON/结构不符时改用 fix_json_prompt 修正，最多 FIX_LIMIT 次。"""
    validate = lambda payload: validate_diagnosis(payload, resume_text, job_requirements)  # noqa: E731
    system = template["system_prompt"]
    content = render_user_prompt(template, resume_text, job_requirements)
    usage = ModelUsage()
    last_exc: ModelFailure | None = None
    for attempt in range(FIX_LIMIT + 1):
        try:
            result, used = await client.complete_json(system, content, validate)
            return result, _merge_usage(usage, used)
        except ModelFailure as exc:
            usage = _merge_usage(usage, exc.usage)
            last_exc = exc
            if exc.code != "invalid_model_output" or attempt >= FIX_LIMIT:
                raise ModelFailure(exc.code, exc.message, usage) from exc
            content = render_fix_prompt(template, resume_text, job_requirements)
    raise ModelFailure(last_exc.code, last_exc.message, usage)  # pragma: no cover