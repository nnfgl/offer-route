from app.agents.contracts import AgentKind, AgentRequest, AgentResult, Evidence
from app.agents.training.schemas import CreateTask


class TrainingAgent:
    """Internal orchestration adapter. user_id must come from authenticated backend code."""

    def __init__(self, service):
        self.service = service

    def run(self, request: AgentRequest) -> AgentResult:
        data = CreateTask.model_validate(request.context)
        task = self.service.create(data, request.user_id)
        gap = task.task_payload.diagnosis_evidence
        return AgentResult(
            task_id=request.task_id,
            agent=AgentKind.TRAINING,
            status="completed",
            summary="训练题已生成，用户训练进度仍为 planned，尚无任务验证证据。",
            evidence=[Evidence(source=gap.source, excerpt=gap.excerpt)],
            data={"schema_version": 1, "training_task": task.model_dump()},
        )

    def result(self, request_id: str, submission_id: str, user_id: str) -> AgentResult:
        submission = self.service.repository.submission(submission_id, user_id)
        return AgentResult(
            task_id=request_id,
            agent=AgentKind.TRAINING,
            status="failed"
            if submission.status == "error"
            else ("needs_input" if submission.status == "pending" else "completed"),
            summary=submission.evaluation_payload.feedback,
            evidence=[
                Evidence(source=item.source, excerpt=item.excerpt)
                for item in submission.evaluation_payload.evidence
            ],
            data={"schema_version": 1, "submission": submission.model_dump()},
        )
