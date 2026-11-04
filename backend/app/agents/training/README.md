# 实战训练 Agent

负责人 C。已实现独立后端入口，包含 SQL 练习、受限校验、提交历史、证据与资料检索。
用户 SQL 在独立受限子进程的内存数据库中运行；正式执行隔离环境仍待团队验收。

- [本地运行与验证](../../../../docs/training-c-local.md)
- [公共协议与对接备注](../../../../docs/training-c-integration-notes.md)

入口：`app.agents.training.application:app`，仅用于本地单进程实验。
共享 `app.main:app`、前端及 A 的调度入口尚未接入 C。
运行数据库、密码、Chroma 持久文件和测试报告均不随源码提交。
