# 01 — 系统架构

## 1. 拓扑

```
 用户 ──消息──► [Channel Adapters]  CLI / Web / (v0.2 Telegram…)
                     │ InboundMessage
                     ▼
              [Conversation Router] ── 闲聊/问答 → 直接回复（带记忆召回）
                     │ 识别到"目标"
                     ▼
              [Goal Engine]  目标生命周期唯一推进者（状态机，持久化）
                │    ▲
      Plan 生成 │    │ 步骤结果/事件
                ▼    │
              [Planner (LLM)] ── 读 Memory 召回 + 可用工具清单 → Plan
                     │ ActionRequest（每一步）
                     ▼
              [Sentinel]  确定性规则 → allow / deny / needs_approval
                │ allow                 │ needs_approval
                ▼                       ▼
        [Sandbox Tool Runner]     [Approval Gate] ──推送──► 用户
                │  ▲                     │ ApprovalDecision
      凭据 handle│  │ 注入(不回显)          └──────► Goal Engine 恢复
                ▼  │
           [Credential Vault]
                │
                ▼ ToolResult（净化后）
              [Goal Engine] ──► [Memory Service] 写入候选记忆
                     │
                     ▼
              [Scheduler] 定时/事件唤醒长时目标    [Audit Log] 全链路只追加
```

## 2. 模块职责

| 模块 | 职责 | 是否用 LLM |
|---|---|---|
| Channel Adapters | 协议适配，统一为 `InboundMessage` / `OutboundMessage` | 否 |
| Conversation Router | 判定消息类型：chat / new_goal / goal_update / approval_reply | 是（分类，带规则兜底：审批回复靠结构化按钮/指令优先） |
| Goal Engine | 状态机推进、持久化、重试、超时 | 否 |
| Planner | 目标 → 步骤计划；步骤失败时重规划 | 是 |
| Executor 步骤解释 | 把计划步骤实例化为具体 `ActionRequest`（参数填充） | 是 |
| Sentinel | 动作放行/拒绝/送审 | 否（v0.2 起可附加 LLM 否决票，只能更严不能放宽） |
| Sandbox Tool Runner | 在隔离进程/容器执行工具，限时、限资源、限网络 | 否 |
| Credential Vault | 存储加密凭据，按 handle 注入到工具，Agent 与 LLM 永远拿不到明文 | 否 |
| Memory Service | 记忆写入、召回、编辑、删除 | 写入抽取与召回重排可用 LLM |
| Scheduler | 定时唤醒、事件订阅 | 否 |
| Audit Log | 只追加记录每个 LLM 调用摘要、ActionRequest、Sentinel 判决、审批 | 否 |

**原则**（沿用 RFQ 项目经验）：状态推进、安全判定、凭据处理全部确定性；LLM 只做理解、规划、总结。

## 3. Goal 状态机

```
created → planning → running ⇄ waiting_approval
                       │  ⇅ sleeping（等时间/事件）
                       ├→ replanning → running
                       ├→ completed
                       ├→ failed（重试耗尽 / 重规划超上限）
                       └→ cancelled（用户取消，任意状态可达）
```

- 每次转移写 `GoalEvent`（事件溯源）；Goal 当前状态可由事件回放重建 → 进程重启不丢。
- 预算：每个目标有 `max_steps`、`max_llm_tokens`、`deadline`；超限转 `waiting_approval`（询问是否追加），而不是静默失败。
- 重规划上限默认 3 次，防止死循环。

## 4. 长时运行与主动性

- **Scheduler**：基于持久化的 `WakeUp` 记录（时间或事件条件）；MVP 用进程内 APScheduler 式循环 + SQLite 轮询，不依赖外部队列。
- **事件源（v0.2）**：IMAP IDLE / 日历变化 / RSS / 网页变化检测，统一转成 `Event` 写入事件表，Goal Engine 匹配订阅。
- **主动建议（v0.2）**：Proactive Engine 每日跑一次，读取近期记忆 + 日程 → 生成 ≤3 条建议，**只推送建议，不自动建目标**，用户点"去做"才建 Goal。

## 5. LLM 抽象（OpenAI 兼容）

```python
class LLMClient(Protocol):
    async def chat(self, messages: list[ChatMessage], *, tools: list[ToolSpec] | None = None,
                   response_format: type[BaseModel] | None = None,
                   role: Literal["planner", "router", "memory", "chat"]) -> LLMResponse: ...
```

- 实现：`OpenAICompatClient`，基于官方 `openai` Python SDK，通过 `base_url` + `api_key` 指向任意兼容服务；默认 DeepSeek。
- 按 `model_role` 在配置中映射到不同模型（规划用强模型，路由/记忆抽取可用小模型）。
- 结构化输出：优先 `response_format=json_schema`；服务不支持时降级为"JSON 提示 + Pydantic 校验 + 最多 2 次修复重试"。
- 测试：`FakeLLMClient` 按脚本返回，所有 agent 单测不触网。
- LLM 看到的工具结果一律经**净化层**：截断、剥离脚本、标注来源为 `untrusted`，并置于独立的 `tool` 消息中，防提示注入。

## 6. 隔离执行（对标 Muse 隔离云电脑）

- MVP：每个工具调用在子进程中执行（`multiprocessing` spawn），环境变量清空，仅注入 vault 下发的单次凭据；网络经本地出网代理，代理按 Sentinel 白名单放行。
- v0.2：每个 Goal 一个容器（Docker/Podman），只挂载该目标工作目录；浏览器自动化（Playwright）只在容器内运行。
- 宿主机上的 Agent 主进程**不直接访问外网**（LLM 端点除外）。

## 7. 技术选型（草案）

| 领域 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | 与 RFQ 项目一致 |
| 数据模型 | Pydantic v2 | 同上 |
| 存储 | SQLite（标准库 `sqlite3`） | 单用户够用，SQL 保持可迁 Postgres |
| 向量召回 | sqlite-vec（v0.2） | 不引入额外服务 |
| LLM SDK | `openai`（仅作 OpenAI 兼容客户端，默认指向 DeepSeek） | DeepSeek 只支持 `json_object`，schema 放 prompt + Pydantic 校验 + 修复重试 |
| Web 通道 | FastAPI + SSE | 轻量 |
| 浏览器自动化 | Playwright（v0.3，容器内） | — |
| 加密 | `cryptography`（Fernet / AES-GCM） | vault |
| 日志 | structlog，带 `goal_id` / `step_id` / `module` | 与 RFQ 规范一致 |
