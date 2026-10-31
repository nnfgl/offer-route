# 面试模块对齐团队更新

## 本次读取的 GitHub 更新

- `docs/shared-database-contract`，`f7cfa50`：共用数据库、建表参考、迁移归属。
- `docs/interview-text-voice`，`f383783`：文字/语音范围、同轮次输入及验收。
- `feat/job-analysis` / `feat/diagnosis`，均为 `c16366f`：岗位实现与公共 DeepSeek 客户端。

检查时 `main` 仍为 `b76bd88`。本次读取这些分支，不把尚未合并的岗位/诊断功能标为已部署。
公共客户端文件与 `c16366f` 中的 `core/model_client.py` 内容相同，复用同一配置命名。

## 确认保留的交互

用户明确选择：**保留实时可打断语音，同时对齐公共接口和数据库**。
因此语音依然由 Qwen-Omni-Realtime 原生对话，面试中不增加转写确认按钮，
不改成逐段录音上传，不适用“单段上传 60 秒 / 8 MB”的录音方案。
语音结束后使用公共 DeepSeek 客户端分析已保存的回答文字。
无密钥文字练习作为独立练习保留；本次不声称实现同一云端会话内无缝切换两种输入。
团队录音确认方案保留在 `interview-team-spec.md`，供后续共同确认范围。

## 公共字段与关联

两个创建 API 均新增 `job_analysis_id`、可选 `diagnosis_id`，字段与共用数据库一致。
`GET /api/v1/interviews/contexts` 返回当前用户已完成的岗位及所选岗位下已完成的诊断。
前端通过下拉框选择，不要求手工复制数据库 ID。

- 关联岗位必须已完成且归当前用户；岗位标题从服务器读取。
- 关联诊断必须已完成、归当前用户，并且 `job_analysis_id` 与会话岗位一致。
- 未完成返回 409，不存在或属于他人返回 404；客户端传入 `user_id/parent_context` 均不接受。
- `parent_context` 是创建时的岗位要求和诊断快照，用于实时面试提示词和面试后复盘。
- 新会话和结果使用 `schema_version: 1`；旧 JSON 缺少该字段时按版本 1 读取。
- `AgentRequest/AgentResult` 公共类型不改变，模型复盘继续校验候选人原文引用。

## 数据库就绪与兼容

统一 SQL 目前是评审参考，**尚未成为运行时迁移**。A 负责最终迁移编号。
本次没有追加或重排已经发布的编号迁移，也没有对开发数据库手动执行参考 SQL。

`shared_store.py` 在统一表就绪、且创建请求关联了岗位时，使用
`interview_sessions/interview_turns`；否则原有独立练习仍使用既有实验表。
统一布局没有旧表时，创建必须关联岗位。两种布局的历史可以共同读取，旧记录不强制重写。

统一表中的字段：

| 字段 | 实现 |
| --- | --- |
| `interview_sessions.input_mode` | text / voice |
| `status` | 文字 active/completed；语音 created/active/completed |
| `job_analysis_id/diagnosis_id` | 服务器校验过的父记录 ID，复合外键再次约束所属用户 |
| `max_rounds` | 文字 3，实时语音 20；超过上限返回冲突 |
| `report_payload` | 合法 JSON，含 schema_version、report、session_state |
| `interview_turns.round_no` | 同一会话唯一、从 1 开始，重复保存保留轮次 ID |
| `question_text/answer_text` | 原始问题及完整回答；未完整 ASR 不写成已回答 |
| `input_mode/status` | 保存实际模式，asked / answered / skipped；结束时未答题标为 skipped |
| `feedback_payload` | schema_version + 原始 voice_messages；answer_confirmation 区分 user_submitted / asr_unconfirmed |
| `audio_duration_ms` | 实时链路尚无可信逐轮时长时为 NULL，不伪造时长 |
| `created_at/updated_at` | UTC 秒级时间戳；更新不早于创建 |

实时对话中连续的回答片段归同一轮，下一段 AI 提问开启新轮。
语音的 connecting/live/ended、后台报告 processing 等是 `session_state` 内的传输状态，
不写进共用 SQL 的业务 status 枚举。面试完成和复盘完成分开表示。

### 已发现的迁移冲突

岗位分支的 v2 创建 `job_analysis_tasks`；既有面试分支的 v2 创建 `interviews`。
两个数据库不能只凭 `user_version=2` 就互相升级。
新增启动检查会识别这种不兼容布局并明确报错，保留原账号、岗位数据及版本号，
避免误执行另一个分支的下一条迁移。不要通过修改 user_version 或删库解决。

A 提供正式统一迁移并保留 users/sessions 后，适配器可直接使用统一表；
测试在临时数据库中模拟 A 的 v1/v2 + 参考统一表，确认不创建 D 的旧实验表。
包含旧表的数据库也验证了新旧记录共存及重复启动，不要求真实库重建。
`database-schema.sql` 的面试索引采用 `interview_sessions_owner`，与旧索引不冲突。

## 模型与异步复盘

实时语音鉴权仍用百炼 Key。结束后的复盘改用 `DeepSeekClient.complete_json`，
不再单独调用百炼文字模型，不再使用 `OFFER_VOICE_REVIEW_URL/MODEL`。
新配置、超时、用量预算与岗位模块一致，见 `.env.example`。
引用/结构验证在公共客户端重试回调内执行；无依据结果不会直接保存成有效评分。
调用用量保存至 `report_usage`，成功结果同时包含 `data.usage`。

异步执行仍是 FastAPI BackgroundTasks + SQLite，没有引入 Redis 或独立 worker。
失败保留原文，可重试；服务重启后的任务按原有超时机制重试。

## 验证和待联调项

测试覆盖旧 JSON 版本兼容、v2 冲突数据保护、统一表读写、稳定轮次 ID、
岗位/诊断完成状态、跨用户和错岗位引用、实时语音保留及结束后才复盘。
公共模型测试使用 MockTransport，不调用付费 API。

仍需 A 合并正式共用迁移，并由团队审查字段和 report_payload 包装结构。
真实麦克风、百炼语音与 DeepSeek 复盘仍需实际凭据联调；模拟测试不等于云端验收。
