# 协作规范

1. 从 `main` 更新代码，为任务创建 Issue，再建 `feat/job-<描述>` 等独立分支。
2. 一次 PR 解决一个可验收任务，关联 Issue，并写清验证结果。
3. 由另一位成员审查。CI 通过后合并；仓库创建后建议启用 main 分支保护。
4. 修改共享协议、数据库或鉴权前，在 Issue 里说明兼容性和调用方影响。
5. 不提交 `.env`、密钥、数据库、真实简历、用户对话或依赖目录。

## 公共约定

- 后端业务路由放在 `/api/v1` 下，错误使用 `error.code/message`。
- 用户身份由 `Depends(current_user)` 获取；不得信任浏览器传来的 user_id。
- 所有写操作通过 `Depends(require_csrf)` 校验。用户数据查询必须包含归属条件。
- 前端复用 `lib/api.ts`，禁止自行保存会话令牌。
- 密钥只在后端读取；前端 `VITE_` 环境变量会暴露给浏览器，不得放密钥。
- Agent 输入输出复用 `agents/contracts.py`；业务数据用 Pydantic 建立具体结构。
- 数据库追加编号迁移，不修改已发布迁移；每周合入可运行的增量。

## 本地依赖更新

后端修改 `pyproject.toml` 后重新安装并更新 `requirements.lock`，保留纯版本依赖，
不要将本机 editable 路径写入锁文件。前端通过 npm 更新并提交 package-lock.json。

推荐提交格式：`feat: ...`、`fix: ...`、`docs: ...`、`test: ...`。
