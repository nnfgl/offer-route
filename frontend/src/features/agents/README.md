# 业务页面

四个业务模块按 job、diagnosis、training、interview 建立子目录，各负责人同时完成对应页面。
共享 API 请求复用 `src/lib/api.ts`。`interview/` 已提供三轮文字面试与复盘页面，
通过工作台“进入模拟面试”打开；其他三个模块仍待开发。
