# 02 — 共享 Schema（草案）

> 实现以 `src/personal_agent/schemas/` 为准；本文是设计时草案，字段细节已有调整（如 `ActionRequest` 不再携带 `data_labels`，敏感数据由 Sentinel 按记忆值匹配）。

约定：Pydantic v2，默认 `model_config = ConfigDict(frozen=True)`；时间一律 UTC `datetime`；ID 为 ULID 字符串。模块间只传模型实例或其 JSON。

## 1. 消息与通道

```python
class InboundMessage(BaseModel):
    message_id: str
    channel: Literal["cli", "web", "telegram"]
    user_id: str
    text: str
    attachments: list[AttachmentRef] = []
    reply_to: str | None = None          # 关联的 OutboundMessage / ApprovalRequest
    structured_action: StructuredAction | None = None  # 按钮点击等（审批只认这个）
    received_at: datetime

class OutboundMessage(BaseModel):
    message_id: str
    channel: str
    text: str
    used_memory_ids: list[str] = []
    goal_id: str | None = None
    approval_request_id: str | None = None
```

## 2. 目标与计划

```python
class GoalStatus(StrEnum):
    CREATED = "created"; PLANNING = "planning"; RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"; SLEEPING = "sleeping"
    REPLANNING = "replanning"; COMPLETED = "completed"
    FAILED = "failed"; CANCELLED = "cancelled"

class GoalBudget(BaseModel):
    max_steps: int = 30
    max_llm_tokens: int = 200_000
    deadline: datetime | None = None
    max_replans: int = 3

class Goal(BaseModel):
    model_config = ConfigDict(frozen=False)   # 由 Goal Engine 独占修改
    goal_id: str
    user_id: str
    title: str
    original_request: str                    # 用户原话，Sentinel 一致性检查的锚点
    allowed_capabilities: list[str]          # 用户在创建时可见并可调整
    status: GoalStatus
    budget: GoalBudget
    plan: Plan | None = None
    created_at: datetime

class PlanStep(BaseModel):
    step_id: str
    description: str
    capability: str                          # 如 "web.read", "mail.draft"
    depends_on: list[str] = []
    success_criteria: str

class Plan(BaseModel):
    plan_id: str
    version: int
    steps: list[PlanStep]
    rationale: str

class GoalEvent(BaseModel):                  # 事件溯源
    event_id: str
    goal_id: str
    type: Literal["status_changed", "plan_created", "step_started", "step_finished",
                  "action_judged", "approval_requested", "approval_decided", "woke_up"]
    payload: dict[str, JsonValue]
    at: datetime
```

## 3. 动作、Sentinel 与审批

```python
class RiskLevel(IntEnum):
    R0 = 0; R1 = 1; R2 = 2; R3 = 3; R4 = 4

class ToolSpec(BaseModel):
    name: str                                # "mail.send"
    capability: str
    risk: RiskLevel
    params_model: str                        # 参数 Pydantic 模型的导入路径
    required_scopes: list[str] = []
    network_domains: list[str] = []          # 静态声明的出网域
    rate_limit_per_min: int = 30

class ActionRequest(BaseModel):
    action_id: str
    goal_id: str
    step_id: str
    tool: str
    args: dict[str, JsonValue]
    data_labels: list[Literal["sensitive", "untrusted", "user_provided"]] = []

class SentinelVerdict(BaseModel):
    action_id: str
    decision: Literal["allow", "deny", "needs_approval"]
    risk: RiskLevel
    matched_rules: list[str]                 # 如 ["EGRESS_ALLOWLIST_OK", "RISK_R3_APPROVAL"]
    reason: str                              # 人类可读

class ApprovalRequest(BaseModel):
    request_id: str
    goal_id: str
    actions: list[ActionRequest]
    verdicts: list[SentinelVerdict]
    human_summary: str
    expires_at: datetime

class ApprovalDecision(BaseModel):
    request_id: str
    decisions: dict[str, Literal["approve", "reject"]]   # action_id → 决策
    edited_args: dict[str, dict[str, JsonValue]] = {}    # 编辑后需重新过 Sentinel
    decided_via: StructuredAction
    decided_at: datetime

class ToolResult(BaseModel):
    action_id: str
    ok: bool
    output: JsonValue                        # 已净化、已脱敏
    trust: Literal["trusted", "untrusted"]
    truncated: bool = False
    error: str | None = None
```

## 4. 记忆

```python
class MemoryType(StrEnum):
    FACT = "fact"; PREFERENCE = "preference"; EPISODE = "episode"; PROCEDURE = "procedure"

class MemoryItem(BaseModel):
    memory_id: str
    type: MemoryType
    subject: str                             # "user" / "contact:张三"
    predicate: str                           # "allergy" / "email_tone"
    value: str
    sensitive: bool = False
    source: Literal["user_statement", "user_explicit", "tool_confirmed"]
    evidence: str                            # 原文片段
    status: Literal["active", "pending_confirm", "superseded"] = "active"
    created_at: datetime
    last_used_at: datetime | None = None

class MemoryCandidate(BaseModel):
    type: MemoryType
    subject: str
    predicate: str
    value: str
    evidence: str
    from_untrusted: bool
```

## 5. 凭据与调度

```python
class CredentialHandle(BaseModel):
    handle_id: str
    service: str
    scopes: list[str]                        # 不含任何秘密

class WakeUp(BaseModel):
    wakeup_id: str
    goal_id: str
    at: datetime | None = None
    on_event: EventMatcher | None = None     # v0.2
```
