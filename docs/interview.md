# 模拟面试与复盘（成员 D）

本分支 `feat/interview` 实现独立可用的文字面试，不依赖尚未完成的岗位、诊断或训练模块。
输入由用户手动填写，建议使用模拟经历；不需要 DeepSeek API Key。

## 首版范围

1. 输入目标岗位与项目经历，创建面试。
2. 完成三轮问答：个人职责与行动 → 技术取舍与验证 → 结果、局限和改进。
3. 追问引用上一轮回答；服务器保存全部题目与回答。
4. 复盘包含表达维度、回答原文依据、建议与待训练项。
5. 刷新或重新登录后，从最近记录继续未完成面试或查看历史复盘。

当前题目与反馈由固定规则生成。中文关键词命中只表示回答出现了表达线索，
即使出现关键词，也可能是错误或否定表述；0–4 分不是能力评级，也不验证技术正确性。
真实模型接入应使用团队后续提供的公共客户端。

## 联调输入与输出

HTTP 路径、约束和状态码见 [API 约定](api.md)。
当前创建接口只接受 `role`、`experience`。A/B 的输出尚未确定，因此先不依赖其内部字段。
`user_id` 始终来自登录态；调用方不得传入或覆盖。

面试结束时，服务端构造公共 `AgentRequest`：

```text
task_id = 面试 ID
user_id = 当前登录用户 ID
goal = 目标岗位
context.turns = 三轮 question / answer
```

`service.review` 返回公共 `AgentResult`：`agent=interview`、`status=completed`。
`evidence[].source` 格式为 `interview:{面试ID}:round:{轮次}`，`excerpt` 是回答原文片段。
`data` 结构如下：

```json
{
  "evaluation_mode": "rules-v1",
  "score": 0,
  "max_score": 4,
  "dimensions": [
    {
      "name": "个人行动",
      "score": 0,
      "basis": "本次回答未命中该表达维度的规则线索",
      "suggestion": "用一个具体案例说明个人职责与实际行动。"
    }
  ],
  "training_items": [
    {
      "skill": "个人行动",
      "task": "用一个具体案例说明个人职责与实际行动。",
      "source_task_id": "面试ID",
      "status": "pending"
    }
  ],
  "notice": "规则反馈与尚未同步共享能力档案的说明"
}
```

实际 `dimensions` 固定包含个人行动、技术取舍、结果验证、反思改进四项。
`training_items` 只包含缺少表达线索的维度；全部命中时为空。
这些项已持久保存在面试复盘内，**尚未写入公共能力档案或创建训练任务**。
公共档案完成后，A/C 可按 `source_task_id + skill` 去重消费；接入前共同确认字段和权限。

## 共享文件变化与合并说明

- `core/database.py`：只追加迁移 2，创建 `interviews` 及归属索引，不修改账号迁移。
  若其他分支也追加迁移，应在合并时统一排序，避免两个已执行数据库具有相同迁移编号。
- `main.py`：注册 `/api/v1/interviews`，只将面试状态设为 `available`。
- 工作台及模块状态类型：添加模拟面试入口，其他模块仍为 `planned`。
- `contracts.py` 和鉴权实现不变，复用现有协议与依赖。
- 账号浏览器回归测试：待开发卡片数量从四个改为三个。

按仓库协作规范，提交 PR 前应在团队 Issue 中说明上述共享数据库和入口的变化。
建议 Issue 标题：`[面试] 文字面试会话与复盘`；本地工作没有自动发布 Issue 或 PR。

## 本地运行与验收

按根目录 README 启动前后端。注册或登录 → 工作台 → 进入模拟面试。
填写模拟经历并完成第一轮；刷新页面后重新进入，从“继续第 2 轮”恢复。
第三轮后查看原文依据和待训练项，再返回列表重开复盘。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm.cmd run build
npm.cmd run test:e2e
```

测试覆盖账号回归、三轮流程、复盘依据、输入边界、Origin/CSRF、用户归属隔离、
重复及并发回答、数据库升级和重启恢复，以及桌面/手机问答、刷新与失败重试。
