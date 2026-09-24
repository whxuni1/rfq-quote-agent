# 03 — 安全：Sentinel、审批与凭据保险库

个人 Agent 的核心风险是**"它能以用户身份行动"**。安全设计目标：LLM 被提示注入或出错时，最坏结果仍被限定在"生成了一份错误草稿"。

## 1. 威胁模型

| 威胁 | 例子 | 主要防线 |
|---|---|---|
| T1 提示注入 | 网页/邮件内容诱导 Agent 外发数据 | 工具结果标注 untrusted + Sentinel 出网白名单 + 数据流标签 |
| T2 越权动作 | 规划出"删除所有邮件" | 动作风险分级 + 审批 |
| T3 凭据泄漏 | LLM 把密码写进回复 | Vault 引用式凭据，明文永不进入 LLM 上下文 |
| T4 失控循环 | 无限重试刷接口 | Goal 预算 + 速率限制 |
| T5 记忆污染 | 恶意内容被写成"用户偏好" | 记忆来源标注；来自 untrusted 内容的记忆需用户确认 |

## 2. 动作风险分级

每个工具在注册时声明静态属性，Sentinel 只看声明 + 实参，不信任 LLM 的自我描述。

| 级别 | 定义 | 例子 | 默认策略 |
|---|---|---|---|
| R0 只读本地 | 读记忆、读本地文件 | `memory.search` | allow |
| R1 只读外部 | 读网页、读邮件、读日历 | `web.fetch`, `mail.list` | allow（目标域需在白名单或属搜索结果） |
| R2 可撤销写 | 草稿、待办、本地文档 | `mail.draft`, `todo.add` | allow + 通知 |
| R3 对外可见/不可撤销 | 发邮件、建会议邀请、提交表单 | `mail.send`, `form.submit` | **needs_approval** |
| R4 资金/身份 | 支付、改密码、删账号 | `pay.checkout` | needs_approval + 二次确认；MVP 不注册此类工具 |

## 3. Sentinel 判定流程（纯函数）

```python
def judge(req: ActionRequest, ctx: SentinelContext) -> SentinelVerdict
```
依次执行，任一 deny 即终止：
1. **工具存在且启用**，实参通过工具的 Pydantic 参数模型校验。
2. **目标一致性（规则）**：工具类别必须在该 Goal 创建时由 Planner 声明、用户可见的 `allowed_capabilities` 中（例："研究类目标"不含 `mail.send`）。
3. **出网白名单**：URL 域名 ∈ 全局白名单 ∪ 本目标内搜索结果返回的域名；禁止内网/元数据地址（SSRF）。
4. **数据流标签**：参数中若含被标记为 `sensitive`（通讯录、记忆中的健康信息等）的数据，且目的地为外部 → needs_approval（R1 的查询参数也适用）。
5. **速率与预算**：每工具每分钟上限、每目标总步数。
6. **风险级别策略**：按上表映射 allow / needs_approval。
7. （v0.2）**LLM 辅助否决**：小模型判断"该动作是否服务于用户原始目标"，只能把 allow 改成 needs_approval，不能反向。

所有判决写 Audit Log，含命中的规则 ID。

## 4. 审批（Approval Gate）

- 复用 RFQ 项目 HiL gate 模式：同一目标同一时刻的待审动作合并为一个 `ApprovalRequest`，避免频繁打扰。
- 审批卡片必须展示：**将要做什么（人类可读）+ 完整实参 + 为什么（关联的目标步骤）+ 风险级别 + 命中规则**。
- 决策：approve / reject / edit（用户修改实参后批准，修改后的实参重新过 Sentinel）。
- 超时：默认 24h 未决 → 目标转 `sleeping` 并提醒一次；不默认批准。
- 审批只能来自已认证通道的结构化操作（按钮/签名指令），**自由文本"好的"不算批准**，防止注入内容伪造审批。

## 5. 凭据保险库（Vault）

- 存储：本地加密文件/SQLite 表，主密钥来自 OS keyring 或启动时口令派生（scrypt）。
- Agent 与 LLM 只能看到 `CredentialHandle(id, service, scopes)`。
- 工具声明所需 `scopes`；Runner 执行前向 Vault 请求**单次**凭据，注入子进程内存，执行结束即销毁。
- 工具输出经脱敏过滤（匹配已知凭据值、token 模式）后才返回。
- OAuth（v0.2）：refresh token 只存在 Vault，access token 按需换取。

## 6. 审计与可见性

- Audit Log 只追加（hash 链防篡改），用户可在 UI 中按目标查看完整轨迹。
- 提供"一键暂停所有目标"总开关（kill switch）。
