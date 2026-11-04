"""载入并渲染能力诊断提示词模板（resume_diagnosis.yaml）。

只面向后端；Jinja2 变量仅来自后端结构化输入，绝不发送到浏览器。
"""

import json
from functools import lru_cache
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

_PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "resume_diagnosis.yaml"


@lru_cache(maxsize=1)
def load_template() -> dict:
    """加载 YAML 模板；进程内缓存一份，避免每次诊断重复读盘解析。"""
    return yaml.safe_load(_PROMPT_FILE.read_text(encoding="utf-8"))


def _environment() -> Environment:
    # StrictUndefined：模板引用未提供变量时立即报错，避免静默渲染成空串。
    return Environment(undefined=StrictUndefined, autoescape=False)


def render_user_prompt(template: dict, resume_text: str, job_requirements: list[dict]) -> str:
    return (
        _environment()
        .from_string(template["user_prompt_template"])
        .render(resume_text=resume_text, job_requirements=job_requirements)
    )


def render_fix_prompt(template: dict, resume_text: str, job_requirements: list[dict]) -> str:
    return (
        _environment()
        .from_string(template["fix_json_prompt"])
        .render(
            output_schema=json.dumps(template["output_schema"], ensure_ascii=False, indent=2),
            job_requirements=job_requirements,
            resume_text=resume_text,
        )
    )