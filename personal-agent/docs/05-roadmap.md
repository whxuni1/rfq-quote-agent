# 05 — 路线图与任务拆分

按 RFQ 项目 `tasks/` 惯例，确认设计后每一行可落为 `tasks/pa-XX-*.md`（Status: TODO/DOING/DONE，一任务一 PR）。

## v0.1 MVP（目标：§4 四个用户故事端到端跑通）

| 任务 | 内容 | 依赖 | DoD |
|---|---|---|---|
| pa-00 | 仓库骨架、配置、structlog、SQLite 迁移 | Q1/Q2 决策 | `pytest`、`ruff`、`mypy --strict` 空跑通过 |
| pa-01 | Schemas（`02-schemas.md`） | pa-00 | 序列化往返测试 |
| pa-02 | LLM 抽象：`OpenAICompatClient` + `FakeLLMClient` + 结构化输出降级 | pa-01 | fake 覆盖修复重试路径 |
| pa-03 | Tool Registry + Sandbox Runner（子进程、超时、出网代理） | pa-01 | 超时/越界出网被拦截测试 |
| pa-04 | Sentinel（规则 1–6）+ Audit Log | pa-03 | 规则逐条金样例；注入场景（故事 4）被拒 |
| pa-05 | Credential Vault | pa-03 | 输出脱敏测试；LLM 上下文中无明文断言 |
| pa-06 | Memory Service（fact/preference，关键词召回，导出/删除） | pa-02 | 故事 2 通过；untrusted 来源不自动入库 |
| pa-07 | Goal Engine 状态机 + 事件溯源 + Scheduler | pa-02, pa-04 | kill -9 后重启恢复测试 |
| pa-08 | Planner + 步骤执行 + 重规划 | pa-07 | 故事 1（fake LLM）通过 |
| pa-09 | Approval Gate | pa-04, pa-07 | 故事 3 通过；自由文本不能触发批准 |
| pa-10 | 工具集 v0.1：web.search / web.fetch / mail.list(IMAP) / mail.draft / calendar.read(CalDAV) / todo | pa-03, pa-05 | 各工具金样例（录制响应） |
| pa-11 | 通道：CLI + Web(FastAPI+SSE)，含审批卡片与"用到的记忆"展示 | pa-09 | 手工演示脚本 |
| pa-12 | Eval harness：4 个故事 + 10 个提示注入用例 + 预算超限用例 | 全部 | 注入用例 100% 拦截；故事全部通过 |

## v0.2
事件触发（IMAP IDLE、网页变化）、Proactive 每日建议、`mail.send` / `calendar.create`（R3，走审批）、向量召回、每目标容器、Telegram 通道、Sentinel LLM 辅助否决。

## v0.3+
浏览器自动化填表（容器内 Playwright）、一次性虚拟卡支付（R4）、procedure 记忆、多目标优先级调度。

## 关键度量
- 安全：注入 eval 拦截率 100%（硬门槛）；R3+ 动作无审批执行次数 = 0。
- 效用：故事类目标完成率；每目标平均打扰（审批）次数。
- 成本：每目标平均 token；长时目标唤醒开销。

## 实现状态（v0.1，2026-09-26）

| 任务 | 状态 | 说明 |
|---|---|---|
| pa-00 骨架 | ✅ | `pyproject.toml`、structlog、SQLite |
| pa-01 Schemas | ✅ | `src/personal_agent/schemas/` |
| pa-02 LLM 抽象 | ✅ | DeepSeek 默认；`json_object` + 校验修复 |
| pa-03 Tool Registry + Sandbox | ✅ | 子进程 + 清空环境 + 超时；出网由 Sentinel 与工具内二次校验（尚无独立出网代理） |
| pa-04 Sentinel + Audit | ✅ | 规则 1–6；hash 链审计 |
| pa-05 Vault | ✅ | AES-GCM + scrypt；输出脱敏 |
| pa-06 Memory | ✅ | fact/preference；CJK 二元组召回；untrusted → 待确认 |
| pa-07 Goal Engine | ✅ | 事件溯源，重启恢复；Scheduler/SLEEPING 唤醒留待 v0.2 |
| pa-08 Planner/Executor | ✅ | 重规划上限、每步动作上限、全局预算 |
| pa-09 Approval | ✅ | 结构化审批、编辑参数重审、防重放 |
| pa-10 工具 | 🟡 | web.search(SearXNG)、web.fetch、todo、doc.write、mail.draft、mail.list(IMAP)、mail.send(SMTP, R3，从 v0.2 提前)；calendar.read(CalDAV) 未做 |
| pa-11 通道 | 🟡 | CLI 完成；Web(FastAPI+SSE) 未做 |
| pa-12 Eval | ✅ | 4 个用户故事 + 11 个注入用例，全部通过 |

已知限制：
- 工具已执行但事件未落盘时崩溃，恢复后该动作可能重做（至少一次语义）；R3 工具需幂等或人工核对。
- 预算耗尽直接 FAILED，尚未实现"申请追加预算"的审批。
- 敏感数据检测是字符串包含匹配，短值（如"花生"）会让含该词的搜索也进入审批，偏保守。
- `registrable_domain` 为无 PSL 的近似实现。
