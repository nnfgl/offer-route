import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.agents.training.exercises import CASES
from app.agents.training.settings import TrainingSettings


@dataclass(frozen=True)
class CheckResult:
    status: str
    code: str
    feedback: str
    checked_cases: int = 0
    passed_cases: int = 0
    duration_ms: int = 0


class SQLRunner:
    def __init__(self, settings: TrainingSettings):
        self.settings = settings

    def check(self, sql: str) -> CheckResult:
        started = time.monotonic()
        passed = 0
        for index, case in enumerate(CASES, 1):
            result = self._case(sql, case)
            duration = int((time.monotonic() - started) * 1000)
            code = result["code"]
            if code != "ok":
                system_error = code in {"execution_timeout", "sandbox_unavailable", "runner_error"}
                return CheckResult(
                    "error" if system_error else "failed",
                    code,
                    "校验未完成，请检查执行限制或稍后重试；本次不作能力判断。"
                    if system_error
                    else "SQL 语法、操作权限或输出范围不符合题目要求，请修改后再提交。",
                    index,
                    passed,
                    duration,
                )
            try:
                same = Counter(map(tuple, result["rows"])) == Counter(case.expected)
            except (TypeError, ValueError):
                same = False
            if not same:
                return CheckResult(
                    "failed",
                    "answer_mismatch",
                    "结果未通过。检查 LEFT JOIN、已付款筛选、空值、计数和列顺序；不要硬编码结果。",
                    index,
                    passed,
                    duration,
                )
            passed += 1
        return CheckResult(
            "passed",
            "passed",
            "通过本题全部测试；该证据仅覆盖本题验证的 SQL 能力。",
            len(CASES),
            passed,
            int((time.monotonic() - started) * 1000),
        )

    def _case(self, sql, case):
        payload = {
            "sql": sql,
            "customers": case.customers,
            "orders": case.orders,
            "timeout": self.settings.sql_timeout_seconds,
            "max_rows": self.settings.sql_max_rows,
            "max_steps": self.settings.sql_max_steps,
        }
        # Never inherit database/model credentials or the application's Python import path.
        environment = {
            key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ
        }
        try:
            with tempfile.TemporaryDirectory(prefix="offer-training-sql-") as directory:
                process = subprocess.run(
                    [sys.executable, "-I", "-S", str(Path(__file__).with_name("sql_worker.py"))],
                    input=json.dumps(payload, ensure_ascii=True),
                    capture_output=True,
                    text=True,
                    timeout=self.settings.sql_timeout_seconds + 1,
                    env=environment,
                    cwd=directory,
                    close_fds=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            if process.returncode or len(process.stdout) > 256000:
                return {"code": "runner_error"}
            result = json.loads(process.stdout)
            if not isinstance(result, dict) or "code" not in result:
                return {"code": "runner_error"}
            return result
        except subprocess.TimeoutExpired:
            return {"code": "execution_timeout"}
        except (OSError, ValueError):
            return {"code": "runner_error"}
