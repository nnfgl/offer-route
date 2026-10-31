# Offer Route · 多智能体求职教练

面向目标岗位的能力诊断与实战训练。四个专业 Agent 共享能力档案，由流程调度器组织协作。

## 当前阶段

已实现公共架构与账号模块：注册、登录、当前用户、会话恢复、退出登录、受保护工作台。
公共入口的四个业务页面仍标记为建设中。C 的实战训练后端已提供独立本地入口，
支持 SQL 练习、确定性校验和证据查询；共享调度及训练前端尚未接入。
运行方式与联调边界见 [训练 C 后端说明](docs/training-c-local.md)。
本阶段不需要 DeepSeek API Key。

## 技术与目录

```text
backend/app/
  core/                 配置、数据库迁移、错误处理
  modules/auth/         注册登录、会话与公共鉴权依赖
  agents/
    contracts.py        Agent 输入输出协议
    job/                岗位分析（待开发）
    diagnosis/          能力诊断（待开发）
    training/           实战训练（待开发）
    interview/          模拟面试（待开发）
    orchestration/      流程调度（待开发）
backend/tests/          账号与安全边界测试
frontend/src/
  features/auth/        账户页面
  features/workspace/   受保护工作台
  features/agents/      四个业务页面（待开发）
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
- [四人分工与业务任务](docs/team-plan.md)
- [协作流程](CONTRIBUTING.md)

生产上线需 HTTPS、显式来源配置、持久数据库、备份，以及按部署规模提供共享限流。
邮箱当前仅作登录标识，未验证归属；邮箱验证、找回密码属于后续账号里程碑。
本仓库完成的是开发基础，不包含公网应用部署。
