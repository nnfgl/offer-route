# 任务 C 后端本地运行

> 整合更新：四模块现共用主应用和正式 v4 迁移；以下保留模块分支阶段的实现与实验记录。当前启动、适配和限制以 [整合说明](integration.md) 为准。

本地实现：SQL 练习生成、提交、确定性校验、证据保存及查询、归档、模拟资料检索。
先阅读 [对接备注](training-c-integration-notes.md)，其中列出尚待团队确认的约定。

## 文件与数据

- 后端：`backend/app/agents/training/`。
- 基础依赖：`backend/requirements.lock`（未修改）。
- MySQL/Chroma 扩展：`backend/requirements.training-local.txt`。
- 虚拟环境：仓库根目录 `.venv/`。
- 私密配置：`.env.training-local`，只在本机填写，禁止复制到聊天或提交。
- 业务 MySQL 库：`offer_route_training_c_local`，root 连接仅用于本地测试。
- Chroma：`.local-training/chroma/`，Navicat 中看不到该集合。
- 模拟训练资料：`backend/app/agents/training/fixtures/python_backend_test_materials.md`。
- 验收报告和公共文档快照：`.local-training/`，已忽略。

## 安装

以下命令均从仓库根目录运行，不使用其他项目的解释器：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.training-local.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e backend
```

在根目录新建已被忽略的 `.env.training-local`，使用 `OFFER_TRAINING_` 前缀：

```dotenv
OFFER_TRAINING_DATABASE_BACKEND=mysql
OFFER_TRAINING_MYSQL_HOST=127.0.0.1
OFFER_TRAINING_MYSQL_PORT=3306
OFFER_TRAINING_MYSQL_USER=root
OFFER_TRAINING_MYSQL_DATABASE=offer_route_training_c_local
# 在本地取消下一行注释并填写已有密码，不要提交该文件。
# OFFER_TRAINING_MYSQL_PASSWORD=
```

工具不会从 Navicat 设置中提取密码；特殊字符建议使用环境文件支持的引号写法。
默认只允许本机地址与上述固定数据库名，防止误连现有业务库。

## 显式初始化

```powershell
.\.venv\Scripts\python.exe -m app.agents.training.local_tools probe --backend mysql
.\.venv\Scripts\python.exe -m app.agents.training.local_tools bootstrap --backend mysql
.\.venv\Scripts\python.exe -m app.agents.training.local_tools seed-knowledge
```

bootstrap 只接受新空库或已带正确本地标记的库；不会删除或替换既有表。
正常应用启动只验证 schema，不自动创建 MySQL 库或导入模拟数据。
Navicat 中刷新对应 root 连接，即可查看 offer_route_training_c_local 和表。

## 启动后端

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.agents.training.application:app --host 127.0.0.1 --port 8013 --workers 1
```

只绑定本机；交互文档为 http://127.0.0.1:8013/docs。
这是 C 的独立本地入口，`app.main:app` 仍为原公共应用。

## 业务接口

统一前缀 `/api/v1`，全部训练接口要求登录。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /training/tasks | 用 diagnosis_id、requirement_id 创建练习 |
| GET | /training/tasks | 查询自己的练习，支持 limit/offset |
| GET | /training/tasks/{id} | 查询题目、引用与训练状态 |
| POST | /training/tasks/{id}/submissions | 提交 request_id、answer_text |
| GET | /training/tasks/{id}/submissions | 查询历次提交 |
| GET | /training/submissions/{id} | 查询一次提交的结果与证据 |
| POST | /training/tasks/{id}/archive | 归档，保留历史 |
| GET | /training/diagnoses/{id}/evidence | 汇总自己的训练验证证据 |
| GET | /training/materials?query=SQL | 检索模拟资料及原文引用 |

写操作要求允许的 Origin 和 X-CSRF-Token；会话使用 HttpOnly Cookie。
不要直接用 /docs 的无 Origin 请求判断业务不可用。建议用下面脚本测试完整会话。
未认证返回 401；CSRF/来源失败 403；跨用户记录 404；状态/重复请求冲突 409；
不兼容输入 422；资料或存储结构未就绪 503。通用错误为 error.code/message。
训练创建返回 201/planned，绝不标成用户已经完成。提交通常返回 201；
同 request_id 正在校验时可能返回 202/pending，之后可查询。
校验结果 failed 表示答案未通过，error 表示执行未完成，不能作为负面能力证据。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m app.agents.training.local_tools smoke --backend mysql
```

smoke 通过公共注册接口创建一个随机模拟账号，在该实验库新增模拟岗位、简历、诊断，
实际检索 Chroma，分别提交错误答案和正确答案，再验证重复提交及证据汇总。
不打印或保存该随机账号的密码、Cookie 或 CSRF；报告保存在被忽略的本地目录。
它只证明本地真实 MySQL/Chroma 链路，不证明付费模型、真实 B/D 或正式隔离服务已集成。

若只做公共 SQLite 兼容测试，可显式使用 --backend sqlite 初始化和 smoke；
不可把该结果当 MySQL 结果。MySQL 集成测试需显式启用：

```powershell
$env:OFFER_RUN_MYSQL_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_training_mysql.py -q
Remove-Item Env:OFFER_RUN_MYSQL_TESTS
```

这些测试会保留模拟业务记录供 Navicat 检查，不自动删除数据。

## 手工检查一个训练流程

1. 使用注册/登录接口获得自己的会话；按公共约定携带 Origin 与 CSRF。
2. 从 /auth/me 取得用户 ID，在终端运行以下命令得到模拟 diagnosis_id：

```powershell
.\.venv\Scripts\python.exe -m app.agents.training.local_tools seed-diagnosis --user-id 你的用户UUID
```

3. 创建训练时传入该 diagnosis_id 和 requirement_id=req-sql-01。
4. 按题目给出的 SQLite 方言提交 SQL，每次新尝试使用新的 request_id。
5. 在 Navicat 中核对 training_tasks、training_submissions；再查询证据接口。
6. 用第二个账号查询第一个账号的记录应返回 404，而不是读到记录。

以上只使用本地模拟信息，没有前端改动；运行数据库和私密配置不随源码提交。

## 本次实际验收记录（2026-10-31）

- Python 3.13.2 的独立 .venv；原 requirements.lock 中 33 个版本全部核对一致。
- MySQL 8.0.45 / root@localhost，9 张公共业务表 + 1 张本地版本标记表。
- ChromaDB 1.5.9 实际写入六篇模拟资料，可重开客户端检索并校验原文 SHA256。
- 最终后端测试 61 passed，显式启用 5 项真实 MySQL 集成测试，无跳过项。
- Ruff 与 pip check 通过；公共运行时代码、鉴权、Agent 外壳、原锁文件和前端未修改。
- 已通过真实 Uvicorn HTTP 验证：健康检查、文档、Cookie、CSRF、Chroma 引用、
  错误/正确 SQL、重复请求、训练证据。
- 验收时 API 服务仅监听 http://127.0.0.1:8013，不是系统服务；重新运行需按上述命令启动。
- 结果：`.local-training/backend-test-results.xml`、`.local-training/http-acceptance.json`。
- 本地依赖完整快照：`backend/requirements.training-local.freeze.txt`，已忽略，未覆盖原锁文件。

这些结果不包含真实模型、真实 B/D 联调或正式容器/远程隔离环境验收。
