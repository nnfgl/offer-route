"""Shared DeepSeek JSON client; no SDK, prompts or secrets are exposed to browsers."""

import asyncio
import json
from collections.abc import Callable
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings

T = TypeVar("T")


class ModelUsage(BaseModel):
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelFailure(Exception):
    def __init__(self, code: str, message: str, usage: ModelUsage | None = None):
        self.code, self.message = code, message
        self.usage = usage or ModelUsage()
        super().__init__(message)


class DeepSeekClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings, self.transport = settings, transport

    async def complete_json(
        self, system: str, content: str, validate: Callable[[dict], T]
    ) -> tuple[T, ModelUsage]:
        settings, usage = self.settings, ModelUsage()
        key = settings.deepseek_api_key.get_secret_value()
        if not key:
            raise ModelFailure("model_not_configured", "尚未配置 DeepSeek 密钥，请联系项目管理员")
        last_code, last_message = "model_unavailable", "模型服务暂时不可用，请稍后重试"
        reserved = 0
        try:
            # An overall deadline includes connection, body reads, parsing and retry waits.
            async with asyncio.timeout(settings.model_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=settings.model_timeout_seconds,
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    for attempt in range(settings.model_max_attempts):
                        if (
                            reserved + settings.model_max_output_tokens
                            > settings.model_output_budget
                        ):
                            raise ModelFailure(
                                "model_budget_exceeded", "本次分析达到模型用量上限", usage
                            )
                        reserved += settings.model_max_output_tokens
                        usage.attempts += 1
                        try:
                            response = await client.post(
                                "https://api.deepseek.com/chat/completions",
                                headers={"Authorization": f"Bearer {key}"},
                                json={
                                    "model": settings.deepseek_model,
                                    "messages": [
                                        {"role": "system", "content": system},
                                        {"role": "user", "content": content},
                                    ],
                                    "response_format": {"type": "json_object"},
                                    "thinking": {"type": "disabled"},
                                    "max_tokens": settings.model_max_output_tokens,
                                    "stream": False,
                                },
                            )
                            if response.status_code in (401, 402, 403):
                                raise ModelFailure(
                                    "model_access_denied",
                                    "模型账户配置或余额异常，请联系项目管理员",
                                    usage,
                                )
                            if response.status_code == 429 or response.status_code >= 500:
                                last_code, last_message = "model_busy", "模型服务繁忙，请稍后重试"
                            elif response.status_code != 200:
                                raise ModelFailure(
                                    "model_request_rejected",
                                    "模型服务拒绝了请求，请检查服务配置",
                                    usage,
                                )
                            else:
                                body = response.json()
                                reported = body.get("usage") or {}
                                usage.prompt_tokens += max(0, int(reported.get("prompt_tokens", 0)))
                                usage.completion_tokens += max(
                                    0, int(reported.get("completion_tokens", 0))
                                )
                                choice = body["choices"][0]
                                if choice.get("finish_reason") != "stop":
                                    raise ValueError("Incomplete model output")
                                payload = json.loads(choice["message"]["content"])
                                return validate(payload), usage
                        except httpx.TimeoutException:
                            last_code, last_message = "model_timeout", "模型响应超时，请稍后重试"
                        except httpx.RequestError:
                            last_code, last_message = (
                                "model_unavailable",
                                "无法连接模型服务，请稍后重试",
                            )
                        except (
                            ValueError,
                            KeyError,
                            IndexError,
                            TypeError,
                            AttributeError,
                            OverflowError,
                            ValidationError,
                        ):
                            last_code = "invalid_model_output"
                            last_message = "模型结果缺少有效原文依据，请补充岗位描述后重试"
                        if attempt + 1 < settings.model_max_attempts:
                            await asyncio.sleep(0.2 * (attempt + 1))
        except TimeoutError as exc:
            raise ModelFailure("model_timeout", "模型响应超时，请稍后重试", usage) from exc
        raise ModelFailure(last_code, last_message, usage)
