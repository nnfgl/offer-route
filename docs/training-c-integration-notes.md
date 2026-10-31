# C 后端对接备注与公共约定差异

本文件只记录本地实验的对接边界，不代表团队已经批准新的公共协议。
本变更仅包含后端、测试及说明；源码可供团队审查，运行数据和私密配置始终不提交。

## 已核对的来源

- main / 本地基线：`b76bd88c543d18ad637b5ba9845ae49bc8d56553`。
- C 验收任务：GitHub Issue #3（SQL 练习、受限验证、证据、鉴权和 CSRF）。
- 公共数据库 PR #7：`f7cfa506ed242f831ef14892ae4902664f47a324`。
  [字段与状态](https://github.com/nnfgl/offer-route/blob/f7cfa506ed242f831ef14892ae4902664f47a324/docs/database.md)
  和 [参考 SQL](https://github.com/nnfgl/offer-route/blob/f7cfa506ed242f831ef14892ae4902664f47a324/docs/database-schema.sql)。
- A 的岗位分析 PR #5：`c16366f0164cd19413439ac05d352cb4aeceb766`。
- 检查时 PR #5/#7 均未合并；B 分支只有诊断 README，无业务输入输出实现。
- 读取的公共文档快照保存在忽略目录 `.local-training/reference/`。

## 1. 公共 SQLite 与本次 MySQL 实验

公共约定要求各人运行 SQLite。本次按用户明确要求另建 MySQL 8 实验库
`offer_route_training_c_local`；公共的 `core/database.py` 和迁移队列没有修改。
`mysql_schema.sql` 是本地适配，不是已获团队认可的正式迁移。

- 表名、业务字段、UUID、UTC 秒时间戳、JSON、状态枚举和复合归属外键保持一致。
- MySQL 的 ID 用 VARCHAR(36)，时间用 BIGINT，原文/JSON 用 TEXT/LONGTEXT；
  不使用不可索引的 TEXT 外键，也不使用 SQLite PRAGMA。
- MySQL 跨字段 CHECK 必须为表级约束；DDL 会隐式提交，不能宣称全程可事务回滚。
- 增加 `training_local_schema` 仅用于本地版本/校验和；它不属于公共九表业务设计。
- 本地 SQLite 同样使用独立标记，不把 user_version 擅自提升到团队 v3。
- 正式迁移仍由 A 编号、合并。合并后先对比差异，不能直接把本地标记当正式迁移版本。
- MySQL 的 JSON 列保留 LONGTEXT + JSON_VALID 检查；程序在读写时用具体模型检查。
  与 SQLite 参考的 JSON 默认值有差异，当前服务和模拟数据均显式写入 JSON。
- 本地 MySQL 适配层兼容公共账号模块的参数绑定及重复账号处理；不应未经评审替换公共数据库层。

## 2. B → C 的具体薄弱点结构尚待确认

公共文档约定 `diagnosis_id` 和 `result_payload`，没有定义内部 gaps 字段。
本地定义 version 1 格式，B/A 联调前需确认或提供转换器：

```json
{
  "schema_version": 1,
  "gaps": [{
    "requirement_id": "req-sql-01",
    "skill_id": "sql.join_aggregation",
    "description": "验证 SQL 多表查询与聚合",
    "source": "job_analysis:对应岗位记录UUID",
    "excerpt": "SQL 多表查询、聚合及空值处理",
    "start": 0,
    "end": 18
  }]
}
```

示例位置仅展示字段；真实 start/end 必须逐字匹配 source_text（Python 字符索引，右端不包含）。
source 当前接受该诊断父记录的 `job_analysis:UUID` 或 `resume:UUID`。
省略位置时由后端定位；非法来源、伪造摘录或错位引用会拒绝创建训练。
首期技能标识只接受 `sql` / `sql.join_aggregation`，不能为其他技能悄悄生成 SQL 题。
模拟岗位和诊断仅用于 C 测试，不能宣称完成了 A/B 的实际能力诊断。

## 3. 证据和能力档案

按 PR #7 的记录链关联，不新建各模块共同覆盖的大 JSON 档案：
job_analysis_tasks → diagnosis_tasks → training_tasks → training_submissions。

通过后的证据写入 submission.evaluation_payload.evidence，包含原任务、诊断、技能、
要求、答案摘要、时间与版本；只读汇总接口允许 A/D 取得同一用户的训练证据。
不修改 B 的 result_payload，不自行定义整项技能等级，也不把一道题通过等同于掌握 SQL。
如果后续公共证据表/档案服务落地，需把这里的汇总入口对接到其统一服务。
现有通用 Evidence 仍保持 source/excerpt，详细结构放在 version 1 业务 payload。

## 4. A 的调度接口与本地入口

`TrainingAgent.run(AgentRequest)` 使用后端已认证 user_id，context 为
`{diagnosis_id, requirement_id}`；通用 task_id 表示调度调用，不能与训练表 id 混用。
生成题目时 AgentResult.status=completed，但训练任务状态仍为 planned。
校验结束后 AgentResult 的 data 单独携带 submission.status；答错不等于 Agent 故障。

main 当前没有 A 的业务入口。本次使用独立 `training.application:app` 注册训练路由，
复用账号、Cookie、current_user、require_csrf 和公共错误处理；公共 main 不受影响。
A 的 PR #5 合并后，需由 A 在统一应用初始化训练服务、挂载 router 并注册调度阶段。
当前工作台仍显示训练 planned，因为用户明确只要求后端，不修改前端或共享工作台。

## 5. SQL 隔离及适用范围

业务数据库为 MySQL，练习题明确声明为 SQLite SQL，二者不是同一连接或同一库。
用户提交仅以数据形式传给 stdlib-only 子进程中的内存练习数据库。
不执行任意 Python、Shell 或用户指定文件，不把 root 密码/应用环境传给子进程。

本地 SQL 校验使用 SQLite authorizer 白名单、只读内存数据库、禁止扩展/ATTACH/PRAGMA、
函数白名单、VM 步数和墙钟超时、返回行数上限；Windows Job Object 限制
192 MiB 内存、2 秒 CPU、最多一个进程，并禁止显示子进程窗口。
资源约束无法建立时拒绝执行，不降级为无限制执行。

此方案仅用于本机 SQL 演示；没有提供独立容器/远程执行主机或 OS 网络隔离。
公共架构要求的正式独立执行环境仍需团队部署验收；不能据此开放任意 Python 运行。
接入正式执行服务时替换 SQLRunner，保持 CheckResult 与提交状态约定。

## 6. 并发、恢复和时间预算

- 每次答案新增 submission。任务级数据库锁和唯一约束保护 attempt_no。
- request_id 放入 evaluation_payload；同任务相同请求及内容返回原提交，不重复记证据。
  同请求不同内容返回 409。新请求遇到 pending 也返回 409。
- 执行 SQL 期间不持有业务库事务锁；最终提交结果和任务状态在一个事务内更新。
- 已完成/已归档任务禁止新提交；归档不删除历史。每任务上限 20 次提交为本地策略，待 A 确认。
- 本地启动把中断的 pending 标记 error，不自动重放；同 request_id 仍返回该 error。
- 该恢复逻辑仅限单进程，启动只允许一个 worker。多实例需由 A 设计租约和任务队列。
- 提交接口目前在一次 HTTP 请求内完成有限校验；默认三组用例，最坏等待约 12 秒。
  耗时模型/远程执行接入时需改为返回编号再查询，注意公共前端请求默认 20 秒超时。

## 7. Chroma 与模型

Navicat 是 MySQL 客户端，不是 ChromaDB 管理工具；不在 MySQL 中假建一个 chromadb 表来冒充向量库。
实际 Chroma 独立目录为 `.local-training/chroma/`，集合为 `python_backend_training_c_local_v1`。
六篇模拟资料由本次人工编写，保留原文、SHA256 和版本。资料检索引用会逐字匹配并核验摘要。
嵌入为显式标注的 local-test-hash-v1 测试向量，不能声称真实语义检索或模型效果已验证。
后续换真实嵌入模型须用新集合、记录模型/维度/版本并重新入库，不能混用向量空间。

本次使用已验证 SQL 模板出题，没有复制 DeepSeek 客户端或使用密钥。
未来自由生成题目需复用 A 的公共客户端，并额外验证题目、数据和答案一致性。

## 8. 本地文件与后续提交

数据库、Chroma、报告、凭据和虚拟环境均被忽略。提交范围只包含源码、人工编写的
模拟资料、测试、依赖声明、CI 及说明，不包含任何本地运行数据。
Issue #3 还包含前端等后续要求，本次后端变更不宣称整个 Issue 已完成。
本地使用 editable 安装；打包配置也包含训练 .sql 和 fixtures/*.md，便于干净环境安装。
后端 CI 安装训练扩展依赖并运行 SQLite/Chroma 测试；真实 MySQL 测试仍须显式启用，
不能把默认 CI 中跳过的 MySQL 用例计为通过。

## 9. 本次 MySQL 建表恢复记录

首次转换时，MySQL 拒绝列级 CHECK 中引用另一列；当时只建立了 users、sessions、
job_analysis_tasks、resumes 四张空表。修正为表级约束后，单独校验了这四张表的
字段、非空、唯一性、归属外键及空表状态，再只补建其余表。没有删除或覆盖既有表。
后续重复初始化与记录保留检查已通过。恢复脚本只用于该次空库，留在忽略目录中，
不要在已有业务数据的库中运行，也不能把它当作正式的通用迁移器。
