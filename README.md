# Offer Route · 多智能体求职教练

面向目标岗位的能力诊断与实战训练。四个专业 Agent 共享能力档案，由流程调度器组织协作。

## 当前阶段

已实现公共架构与账号模块：注册、登录、当前用户、会话恢复、退出登录、受保护工作台。
岗位分析已实现：粘贴招聘要求，区分必需、加分和待确认条件，逐条核对原文，
保存并恢复当前用户的最近分析记录。流程调度入口已接入岗位分析；能力诊断、
实战训练、模拟面试仍在建设中，由对应成员独立开发。
默认本地规则提取，无需密钥；可选开启 DeepSeek 分析。

## 技术与目录

```text
backend/app/
  core/                 配置、数据库迁移、错误处理
  modules/auth/         注册登录、会话与公共鉴权依赖
  agents/
    contracts.py        Agent 输入输出协议
    job/                岗位分析、证据定位与结构化结果
    diagnosis/          能力诊断（待开发）
    training/           实战训练（待开发）
    interview/          文字与语音模拟面试（待开发）
    orchestration/      岗位分析调度与任务状态持久化
  modules/jobs/         岗位分析 API、历史与权限隔离
backend/tests/          账号与安全边界测试
frontend/src/
  features/auth/        账户页面
  features/workspace/   受保护工作台
  features/agents/job/  岗位分析页面，其余三个业务页面待开发
  lib/                  统一请求与类型
docs/                   架构、API、四人分工和协作规范
.github/                CI、Issue 和 PR 模板
```

Python FastAPI + React / TypeScript / Vite；当前数据库为 SQLite，后续根据部署规模迁移。
已在 Python 3.14、Node 24 上验证；团队建议统一版本。依赖锁文件提交入库。

## 本地启动（Windows PowerShell）

在仓库根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e backend
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

打开 <http://127.0.0.1:5173>，后端 API 文档 <http://127.0.0.1:8000/docs>。
初次运行自动创建本地数据库。没有预置账号，请在页面注册。
前端通过 Vite 将 `/api` 代理给后端，Cookie 不保存在 localStorage。

登录后点击“开始岗位分析”，可使用“填入示例”完成一次分析，点击“查看原文”
核对证据。页面刷新后，重新进入岗位分析并打开“最近分析”可恢复记录。

## 可选：使用 DeepSeek

保留已有 `.env`，只编辑以下配置；不要重复复制示例覆盖自己的配置：

```dotenv
OFFER_JOB_PROVIDER=deepseek
DEEPSEEK_API_KEY=在本地填写自己的密钥
OFFER_DEEPSEEK_MODEL=deepseek-flash
```

重启后端后生效。密钥仅由后端读取，禁止提交或填入前端配置。默认规则提取
适合格式明确的招聘要求，复杂逻辑需要人工核对；不会把规则结果标记为 AI 分析。
DeepSeek 实现参考[官方 JSON Output 文档](https://api-docs.deepseek.com/guides/json_mode/)，
使用 JSON 输出与本地结构校验，引用必须逐字存在于原文中。
当前自动测试使用模拟模型响应，不调用付费接口，真实账户连通性需配置密钥后验证。

服务默认每次分析总超时 12 秒、最多 2 次调用、每次输出上限 1800 tokens，
按最坏情况预留 3600 输出 tokens；每账户每分钟最多提交 6 次，进程内最多并行 4 个。
用量显示只包含服务实际返回的 token 计数，不代表精确账单。

macOS/Linux 使用 `.venv/bin/python` 替代 Python 路径，使用 `cp .env.example .env`。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm.cmd run build
npm.cmd run test:e2e
```

浏览器测试在本地使用 Edge；先按启动步骤运行后端（或将虚拟环境加入 PATH）。
测试自动启动前端，覆盖桌面和手机尺寸。CI 安装 Chromium 后运行同一组测试。
GitHub push/PR 自动运行后端测试、前端构建与浏览器测试。

## 协作入口

- [架构与安全边界](docs/architecture.md)
- [接口约定](docs/api.md)
- [成员 D：文字与语音面试范围](docs/interview.md)
- [四人分工与业务任务](docs/team-plan.md)
- [岗位分析模块与后续接入](docs/job-analysis.md)
- [协作流程](CONTRIBUTING.md)

生产上线需 HTTPS、显式来源配置、持久数据库、备份，以及按部署规模提供共享限流。
邮箱当前仅作登录标识，未验证归属；邮箱验证、找回密码属于后续账号里程碑。
本仓库完成的是开发基础，不包含公网应用部署。
