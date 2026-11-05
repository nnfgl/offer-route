# API v1

开发 API 基址：`http://127.0.0.1:8000/api/v1`，交互文档：`/docs`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /health | 健康检查 |
| POST | /auth/register | 邮箱、密码、称呼注册并登录 |
| POST | /auth/login | 邮箱与密码登录 |
| GET | /auth/me | 当前用户、CSRF token；未登录返回 401 |
| POST | /auth/logout | 撤销会话；成功 204 |
| GET | /workspace | 需要登录，四个业务模块均为 available |
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
岗位、诊断和训练当前只有内部协议。模拟面试已开放以下 API，均需要登录。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /interviews | 创建三轮面试（201） |
| GET | /interviews | 当前用户最近 50 条记录，按创建时间降序 |
| GET | /interviews/{id} | 恢复自己的面试及复盘 |
| POST | /interviews/{id}/answers | 提交当前轮回答，第三轮生成复盘 |

创建请求：`{"role":"Python 后端工程师","experience":"开发校园图书借阅系统，负责后端接口。"}`。
岗位去除首尾空格后 1–100 字，经历 10–5000 字。
可选 `job_analysis_id/diagnosis_id` 与共用数据库同名；诊断不能脱离岗位单独关联。
`GET /interviews/contexts?job_analysis_id=...` 获取所属用户的已完成岗位和诊断选项。
统一表未就绪时，携带岗位 ID 创建返回 503；独立练习不受影响。
统一布局下没有旧实验表时，创建必须选择岗位。关联记录的归属、状态和岗位一致性由后端检查。
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
| GET | /voice-interviews/config | 分别返回 configured（语音）、review_configured（DeepSeek 复盘），不返回密钥 |
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

## 集成后的诊断与训练 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /diagnoses/capabilities | 诊断提供方与配置可用性 |
| POST | /diagnoses | 简历原文、标题及已完成 job_analysis_id；返回诊断 |
| GET | /diagnoses | 当前用户诊断摘要 |
| GET | /diagnoses/{id} | 诊断详情 |
| GET | /training/diagnoses/{id}/gaps | 将已保存诊断转为训练输入；证据来自所属岗位原文 |
| POST | /training/tasks | diagnosis_id、requirement_id；首期仅支持 SQL 缺口 |
| GET | /training/tasks | 当前用户任务列表 |
| GET | /training/tasks/{id} | 训练详情 |
| POST | /training/tasks/{id}/submissions | request_id（UUID）和 answer_text；重复请求幂等 |
| GET | /training/tasks/{id}/submissions | 提交历史 |
| GET | /training/submissions/{id} | 单次提交结果 |
| POST | /training/tasks/{id}/archive | 归档训练任务 |
| GET | /training/diagnoses/{id}/evidence | 通过训练得到的证据，不覆盖原诊断 |
| GET | /training/materials?query=SQL | 标为 synthetic 的本地示例资料 |

全部接口要求登录；写接口要求 Origin 和会话 CSRF。其他用户的记录返回 404。
完整可交互结构以本机 `/docs` 为准。

## 求职路线

| 方法 | 路径 | 请求及结果 |
| --- | --- | --- |
| POST | /career-routes | `request_id`、`job`（含 `title` 和 `source_text`）、`resume_title`、`resume_text`。相同编号和材料可安全重试 |
| GET | /career-routes | 当前用户的历史路线摘要 |
| GET | /career-routes/{id} | `revision`、`phase`、`next_stage`、尝试记录、关联 ID 和能力档案 |
| POST | /career-routes/{id}/advance | 传入最新 `revision`，执行一个步骤。重复或过期版本返回 409，刷新后可继续 |
| POST | /career-routes/{id}/practices/{session_id} | `skill`、`answer`，保存已有关联面试练习的回答 |

路线中调用的 SQL 校验和面试使用原接口。面试列表支持 `diagnosis_id` 筛选当前用户的关联会话。
模型用量为已知请求的累计计数，能力档案覆盖率按已通过练习的必需要求计数。
