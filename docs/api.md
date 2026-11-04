# API v1

开发 API 基址：`http://127.0.0.1:8000/api/v1`，交互文档：`/docs`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /health | 健康检查 |
| POST | /auth/register | 邮箱、密码、称呼注册并登录 |
| POST | /auth/login | 邮箱与密码登录 |
| GET | /auth/me | 当前用户、CSRF token；未登录返回 401 |
| POST | /auth/logout | 撤销会话；成功 204 |
| GET | /workspace | 需要登录，岗位分析为 available，其余为 planned |
| GET | /jobs/capabilities | 当前分析方式与配置是否可用，不返回密钥 |
| POST | /jobs/analyses | 创建并执行当前用户的岗位分析任务，返回 201 |
| GET | /jobs/analyses | 当前用户最近 20 条摘要，不含招聘正文 |
| GET | /jobs/analyses/{task_id} | 当前用户任务详情；不存在或无权访问均为 404 |

注册请求：

```json
{"email":"you@example.com","password":"a-long-unique-password","display_name":"小林"}
```

注册与登录响应（注册 201，登录 200）：

```json
{"user":{"id":"uuid","email":"you@example.com","display_name":"小林"},"csrf_token":"random-value"}
```

服务端设置 `offer_session` HttpOnly Cookie；前端不接触令牌。
密码长度 10–128 字符，称呼去除首尾空格后 1–40 字符。邮箱统一为小写。

所有 POST 必须携带允许的 `Origin`，且使用 JSON。
退出及后续登录态写操作另需 `X-CSRF-Token`，取自登录响应或 `/auth/me`。
浏览器 fetch 使用 `credentials: include`。脚本调用也需显式 Origin 和 Cookie。

错误示例：

```json
{"error":{"code":"invalid_credentials","message":"邮箱或密码错误"}}
```

常用状态：401 未登录/凭据错误、403 来源或 CSRF 错误、409 邮箱不可用、
422 输入错误、429 请求频繁（带 Retry-After）。验证错误不回显密码。

岗位分析请求：

```json
{"title":"Python 后端开发","source_text":"任职要求：熟悉 Python 和 SQL，具备 Git 团队协作经验。"}
```

title 去除首尾空格后 2–120 字符，source_text 为 20–20000 字符，额外字段被拒绝。
不接受前端指定 user_id 或 provider；提供者由后端配置决定。
详情包含 id、title、source_text、provider、status、created_at、requirements、trace、
result、usage 和可空 error。result 复用 AgentResult，状态 completed / needs_input / failed。
任务创建成功但模型处理失败时仍返回 201，任务 status=failed，错误位于 task.error，
历史记录保留失败原因；HTTP 401/403/422/429 等仍使用公共 error 格式。
每项 requirement 包含 text、priority、category、quote、source_start、source_end、source_line。
优先级为 required / preferred / unspecified；引用偏移按 Python Unicode 码点计数，
起点包含、终点不包含，行号从 1 开始。前端使用 Array.from 后切片，避免 emoji 偏移。

分析超时、无密钥、限额、空白 JSON、截断、无原文依据等返回稳定的任务错误码。
后续 Agent 的接入约定见 [岗位分析模块](job-analysis.md)。
