# 实时语音面试与结束后复盘

成员 D 的语音模块沿用 FastAPI + React，独立于尚未完成的岗位、诊断和训练模块。
首版供应商为阿里云百炼。语音使用 Qwen-Omni-Realtime 原生双向音频，
复盘使用独立文字模型；不将固定题库或浏览器朗读称为真实模型语音面试。

## 当前验证状态

已实现 API、WebRTC 控制、转写持久化、自动/手动打断和结束后的异步复盘。
自动化测试使用模拟云服务与模拟 WebRTC，验证调用顺序、末句保存、失败和安全边界。
**尚未使用真实 API Key 做麦克风、中文识别、音色及插话延迟验收。**
配置完成后需按下文手动验收，不承诺未经测量的延迟或识别质量。

## 申请与配置（北京地域示例）

1. 在[阿里云百炼](https://bailian.console.aliyun.com/)开通模型服务，
   获取北京地域的 API Key 和业务空间 ID，并确认实时模型和复盘模型有调用权限及可用额度。
2. 按根目录 README 安装锁定依赖，复制 `.env.example` 为 `.env`（已有文件时直接编辑）。
3. 在后端 `.env` 设置：

```dotenv
OFFER_VOICE_API_KEY=填入你的密钥
OFFER_VOICE_WEBRTC_URL=https://你的业务空间ID.cn-beijing.maas.aliyuncs.com/api/v1/webrtc/realtime
OFFER_VOICE_MODEL=qwen3.8-omni-flash-realtime
OFFER_VOICE_NAME=Tina
OFFER_VOICE_REVIEW_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
OFFER_VOICE_REVIEW_MODEL=qwen-plus
OFFER_VOICE_MAX_MINUTES=15
```

也可以将复盘 URL 设置成控制台对应业务空间的
`https://你的业务空间ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions`。
其他地域应同时修改地址、Key 与可用模型，不混用不同地域配置。
模型名和权限以控制台及[官方实时文档](https://help.aliyun.com/zh/model-studio/realtime)为准。
`/config` 的 `configured=true` 只表示已填写 Key 和 URL，不表示已通过云端连通性测试。

`.env` 不入库，不将 Key 写入前端 `VITE_` 配置。`DEEPSEEK_API_KEY` 不参与这条语音链路。
当前文字模型适配集中在 `voice_provider.py`，团队公共模型客户端完成后再统一替换该适配层。
`httpx` 已从开发依赖移为运行依赖，现有锁文件已包含同版本，无新增包版本。

重启后端，打开工作台 → 进入模拟面试 → 实时语音。
使用 HTTPS 或 `http://127.0.0.1`，允许麦克风，建议戴耳机。

## 数据流与状态

```mermaid
sequenceDiagram
    participant UI as 浏览器
    participant API as FastAPI
    participant Cloud as 百炼
    UI->>API: 创建语音会话（Cookie + Origin + CSRF）
    UI->>API: offer_sdp
    API->>Cloud: SDP + 后端密钥
    Cloud-->>API: answer_sdp
    API-->>UI: answer_sdp + 面试配置
    UI->>Cloud: WebRTC 双向音频
    Cloud-->>UI: 字幕 / 语音起止 / 回复事件
    UI->>API: 逐条保存完整转写
    UI->>Cloud: 插话时 response.cancel + 本地静音播报
    UI->>UI: 结束：关闭麦克风输入，等待末句转写
    UI->>API: 保存最终快照
    UI->>UI: 停止音轨，关闭 PeerConnection
    UI->>API: end（核对 message_count，冻结记录）
    API-->>UI: ended + processing
    API->>Cloud: 用已结束的完整对话生成 JSON 复盘
    UI->>API: 轮询报告
    API-->>UI: completed / failed
```

通话状态：`created → connecting → live → ended`。
分析状态：`not_started → processing → completed/failed`。
面试中不启动评分请求、不显示分数；结束操作可安全重试。

浏览器等到 `session.updated` 后才打开麦克风输入。
云端 VAD 检测到用户说话后，本地立即静音 AI 播报并取消正在生成的回复；
下一次 AI 回复开始时恢复播放，也提供“打断面试官”按钮。
被取消的面试官转写保留 `interrupted=true`，可能包含尚未听到的生成内容。

结束时关闭麦克风输入但保留通道，以静音让 VAD 提交末句；
等待语音结束、未完成 ASR 消息归零和静默窗口，最长等待约 12 秒。
未完成或失败的转写不会被当成完整回答：页面提示重试等待，
或由用户明确选择“仅用已保存内容结束”，报告标记不完整。
结束后按完整候选人回答生成报告；缺少完整回答则不生成评分。

## 给队友的字段约定

| 字段 | 类型 | 归属与用途 |
| --- | --- | --- |
| `role` | string | 当前手动输入目标岗位；之后映射 A 的岗位标题 |
| `experience` | string | 当前手动输入模拟经历；之后由用户确认 B 提供的经历摘要 |
| `id` | string | 服务端生成的语音面试 ID，对应公共 `AgentResult.task_id` |
| `messages[].id` | string | 云端消息项 ID；保存、重试和证据引用的去重键 |
| `messages[].sequence` | integer | 对话中首次出现的顺序，0–200；不按 ASR 完成先后排列 |
| `messages[].role` | user / assistant | 区分回答与提问 |
| `messages[].text` | string | 转写内容；`final` 表示是否完成 |
| `messages[].interrupted` | boolean | 该段 AI 回复被打断，不等于用户听完全部文字 |
| `report.data.training_items` | array | 低于 4/5 分维度的待训练建议，供 C 后续消费 |
| `report.evidence[].source` | string | `voice:{面试ID}:message:{消息ID}` |

模块内函数名无需与队友一致；API 路径、方法、字段名和类型应按上述协议联调。
客户端不传 `user_id`，后端通过公共登录态确定归属。
岗位要求和薄弱项的详细结构尚未确定，后续先共同扩展输入协议，再做映射。

复盘使用公共 `AgentResult`。`data.evaluation_mode=model-transcript-v1`，
固定四项：岗位理解、技术与经历、表达结构、反思改进，各 0–5 分，总分 20。
每个非零评分必须带候选人原文引用；服务端校验消息 ID、角色、完整状态和连续原文，
不合格输出作为生成失败，保留转写供重试，不静默改成无依据评分。
本版仅评价文字内容，不分析语速、口音、音色或真实录用概率。
待训练项保存在面试记录内，尚未回写公共能力档案。

## 持久化、失败与部署边界

- 迁移 3 新建 `voice_interviews`，不更改已发布迁移 1/2；合并时与其他成员统一追加顺序。
- 全部 API 按用户归属查询；写操作校验 Origin、CSRF。SDP/模型鉴权只在后端完成。
- 语音数据经 WebRTC 直接传给供应商；应用只保存浏览器上传的转写，不保存原始录音。
  转写是浏览器提交的数据，不是供应商签名或独立能力验证，不应当作可信招聘评测证书。
- 单会话不支持重复建连；刷新或断线可查看已保存转写、结束并复盘，再新建一场语音面试。
  不将这个流程称为无缝续接旧的云端对话。
- 完整转写逐条保存；关闭页面前尚未完成的识别片段可能丢失，正式结束会等待并检查末句。
- 后台复盘有 70 秒总超时，失败可重试；进程被终止时，90 秒后允许重试旧任务。
  多进程任务使用数据库 attempt 防止旧结果覆盖新结果；生产部署可替换为持久任务队列。
- 浏览器执行单场时长限制，并在退出、结束、组件卸载时关闭音轨和连接。
  该限制不是供应商侧强制费用上限；WebRTC 直连不支持由本后端强制撤销已建立的媒体连接。
  云端额度/并发限制需在供应商控制台配置。
- 语音创建、连接和复盘重试另有每用户每分钟 10 次进程内限流。

## 验收

自动化：根目录运行后端测试和 ruff，前端构建及 Playwright。
模拟 WebRTC 的桌面/手机测试检查打断、末句延迟到达、错误确认和结束后才调用复盘。

真实凭据配置后手动检查：

1. 允许麦克风，确认面试官问候、语音播放和中文转写；声音被浏览器拦截时点击播放按钮。
2. 在 AI 说话期间插话，确认旧播报停止、用户回答被识别，之后 AI 根据回答继续追问。
3. 切换静音，确认不会继续采集回答；恢复后继续对话。
4. 在最后一句说完后立即结束，确认转写保存后才生成报告，且引用与回答原文一致。
5. 模拟断网和转写失败，确认显示失败、不伪造完整回答，并可查看已保存内容。
6. 检查 Network 与构建产物没有 API Key；检查数据库未保存音频。
7. 检查真实模型耗时、识别效果及供应商账单，记录测量结果后再声明联调完成。

## 参考来源

借鉴设计，当前实现未复制第三方实现代码：

- [interview-agent-py](https://github.com/renjianguojinqianfan/interview-agent-py)：
  FastAPI/React、通话和评估分离（AGPL-3.0）。
- [DeepInterview](https://github.com/ngoanpv/DeepInterview)：prep/live/post 分层（Apache-2.0）。
- [realtime-interview-practice](https://github.com/Jaskey15/realtime-interview-practice)：
  WebRTC 对话与面试后复盘（MIT）。
- [百炼实时语音协议](https://help.aliyun.com/zh/model-studio/realtime)、
  [客户端事件](https://help.aliyun.com/zh/model-studio/client-events)、
  [结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。
