"""Deterministic practice coach; no model calls or claims of skill verification."""

from app.agents.contracts import AgentKind, AgentRequest, AgentResult, Evidence


def first_question(role: str, experience: str) -> str:
    return (
        f"面向{role}，请展开这段经历「{experience[:100]}」："
        "当时的目标是什么？你个人负责什么，采取了哪些具体行动？"
    )


def follow_up(answer: str, round_number: int) -> str:
    if round_number == 2:
        return (
            f"你提到「{answer[:100]}」。请选一个关键技术决策，"
            "说明备选方案、取舍原因，以及你如何验证这个决定。"
        )
    return (
        f"针对你刚才提到的「{answer[:100]}」，结果如何？"
        "请给出测试或指标依据，并说明一次失败、局限和下一步改进。"
    )


def review(request: AgentRequest) -> AgentResult:
    turns = request.context["turns"]
    checks = [
        (
            "个人行动",
            ("我负责", "我实现", "我设计", "我排查", "我编写"),
            "用一个具体案例说明个人职责与实际行动。",
        ),
        (
            "技术取舍",
            ("取舍", "相比", "对比", "备选", "权衡"),
            "比较至少两种方案，说明约束和取舍理由。",
        ),
        (
            "结果验证",
            ("测试", "指标", "延迟", "覆盖率", "吞吐", "验证"),
            "补充验证方法、结果及可核实的数据来源。",
        ),
        (
            "反思改进",
            ("改进", "失败", "局限", "不足", "下次"),
            "说明一次失败或局限，以及下一步改进。",
        ),
    ]
    dimensions, training_items, evidence = [], [], []
    for name, markers, suggestion in checks:
        match = next(
            (
                (index, turn["answer"])
                for index, turn in enumerate(turns, 1)
                if any(marker in turn["answer"] for marker in markers)
            ),
            None,
        )
        excerpt = None
        if match:
            index, answer = match
            position = min(answer.index(marker) for marker in markers if marker in answer)
            excerpt = answer[max(0, position - 20) : position + 100]
            evidence.append(
                Evidence(source=f"interview:{request.task_id}:round:{index}", excerpt=excerpt)
            )
        else:
            training_items.append(
                {
                    "skill": name,
                    "task": suggestion,
                    "source_task_id": request.task_id,
                    "status": "pending",
                }
            )
        dimensions.append(
            {
                "name": name,
                "score": int(match is not None),
                "basis": excerpt or "本次回答未命中该表达维度的规则线索",
                "suggestion": suggestion,
            }
        )
    return AgentResult(
        task_id=request.task_id,
        agent=AgentKind.INTERVIEW,
        status="completed",
        summary="三轮文字面试已完成；请结合回答原文复盘表达并补充证据。",
        evidence=evidence,
        data={
            "evaluation_mode": "rules-v1",
            "score": sum(d["score"] for d in dimensions),
            "max_score": 4,
            "dimensions": dimensions,
            "training_items": training_items,
            "notice": "评分仅检查中文表达线索，不判断技术正确性，不代表真实能力或招聘结论。"
            "待训练项已保存在本次复盘中，尚未同步到共享能力档案。",
        },
    )
