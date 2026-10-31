# API v1

开发 API 基址：`http://127.0.0.1:8000/api/v1`，交互文档：`/docs`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /health | 健康检查 |
| POST | /auth/register | 邮箱、密码、称呼注册并登录 |
| POST | /auth/login | 邮箱与密码登录 |
| GET | /auth/me | 当前用户、CSRF token；未登录返回 401 |
| POST | /auth/logout | 撤销会话；成功 204 |
| GET | /workspace | 需要登录，返回用户与四个待开发模块 |

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

岗位、诊断和训练当前只有内部协议。模拟面试已开放以下 API，均需要登录。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /interviews | 创建三轮面试（201） |
| GET | /interviews | 当前用户最近 50 条记录，按创建时间降序 |
| GET | /interviews/{id} | 恢复自己的面试及复盘 |
| POST | /interviews/{id}/answers | 提交当前轮回答，第三轮生成复盘 |

创建请求：`{"role":"Python 后端工程师","experience":"开发校园图书借阅系统，负责后端接口。"}`。
岗位去除首尾空格后 1–100 字，经历 10–5000 字。
回答请求：`{"round":1,"answer":"我负责……"}`，轮次 1–3，回答去除首尾空格后 1–5000 字。
两个写接口均要求允许的 Origin 和 `X-CSRF-Token`，请求不接受 `user_id` 等额外字段。

会话返回 `id/role/experience/status/created_at/turns/report`，其中 `created_at` 为 Unix 秒。
`turns` 保存已回答题和当前题（`question/answer`，未回答为 null）；
第三轮提交后 `status` 变为 `completed`，`report` 返回公共 `AgentResult`。
409 表示重复、过期或已结束的轮次；重新 GET 记录恢复进度。
不存在和不属于当前用户的 ID 都返回 404。
复盘与待训练项协议见 [模拟面试文档](interview.md)。

## 实时语音面试

与三轮文字练习使用独立会话。以下路径均需登录，所有 POST 复用 Origin 和 CSRF 校验。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /voice-interviews/config | 是否已填写服务配置、单场时长上限；不返回密钥或供应商 URL |
| POST | /voice-interviews | 创建语音会话，输入 `role/experience`（201） |
| GET | /voice-interviews | 当前用户最近 50 条语音会话 |
| GET | /voice-interviews/{id} | 转写、状态与复盘 |
| POST | /voice-interviews/{id}/connect | 输入 `offer_sdp`，后端代理鉴权，返回 `answer_sdp/session` |
| POST | /voice-interviews/{id}/messages | 保存转写快照；按消息 ID 去重 |
| POST | /voice-interviews/{id}/end | 冻结转写并结束；随后异步生成复盘 |
| POST | /voice-interviews/{id}/report | 重试失败或超过 90 秒未完成的复盘（202） |

转写请求：`{"messages":[{"id":"item-1","role":"user","text":"我负责接口开发。","final":true,"interrupted":false}]}`。
消息角色只能是 `user/assistant`；最多 200 条、单条最多 10000 字、整场最多 100000 字。
`sequence` 为 0–200 的对话顺序（兼容默认 0），首次保存后不可改写；用于处理 ASR 完成乱序。
完整转写不能改写文本或角色，可补充被打断标志；未完成转写可更新为完整转写。

结束请求：`{"message_count":2,"accept_incomplete":false}`。
服务端校验条数；候选人未完成转写需显式确认 `accept_incomplete=true`。
结束后不再接受转写写入，重复结束不重复调用模型；面试中请求复盘返回 409。
没有完整候选人回答时不生成评分。报告中的引用必须来自已完成的候选人转写，逐条校验原文。

`status` 为 `created/connecting/live/ended`；`report_status` 独立为
`not_started/processing/completed/failed`，避免把通话与分析混成一种状态。
失败不丢转写；无配置返回 503，上游连接失败返回 502 且不回显供应商响应或密钥。
真实语音配置、结束流程和联调字段详见 [语音文档](voice-interview.md)。
