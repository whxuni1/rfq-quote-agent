# AGENTS.md — RFQ Quote Agent (Codex Master Instruction)

> 本文件是 Codex 在本 repo 工作时的最高指令。每次会话先读本文件，再按 `tasks/` 下顺序执行任务 prompt。

## 1. 项目使命

构建一个**汽车硬件 RFQ 智能报价 Agent 系统**。它不是聊天机器人，是执行主体：
- 输入：RFQ 包（PDF 技术规格 + Excel BOM + 图纸引用）
- 输出：报价草稿包（报价函 + 成本明细 + 风险登记 + 假设条件 + 例外清单 + 评审轨迹）

主战场：智能座舱 / 智驾硬件（SoC、显示、摄像头模组、传感器、PCBA、连接器、结构件、线束、热管理、光学、软件许可）。

## 2. 硬约束（不可违反）

1. **纯文档进文档出**：不调用任何外部网络 API、不连 ERP/PLM/供应商系统。所有"工具"是纯函数（pdf 文本抽取、xlsx 解析、参数化 should-cost、成本汇总、模板渲染）。
2. **多 Agent + Human-in-loop**：Orchestrator 编排 4 个 sub-agent（工程/采购/财务/商务），关键决策点必须可暂停等待人工决策。
3. **确定性优先**：工具层确定性；LLM 只在理解/拆分/汇总/风险判读处使用。同输入同 schema 输出可复现。
4. **不幻觉 API**：不得 import 不存在的库或编造函数签名。用到第三方库必须写入 `requirements.txt` 并在 PR 说明里标明用途。
5. **类型完备**：所有跨模块数据结构用 Pydantic v2 模型定义于 `schemas/`，sub-agent 间通信只传模型实例或其 JSON 序列化。
6. **可测试**：每个 sub-agent 必须有单元测试，工具层必须有金样例测试。eval harness（`tests/eval/`）是 DoD 门槛。

## 3. 架构摘要（详见 `docs/00-architecture.md`）

```
RFQ Package (PDF+XLSX)
        │
        ▼
[Ingestion Parser] ──► RFQPackage + BOMTree (Pydantic)
        │
        ▼
[Orchestrator] ── 任务理解 → 拆分 → 分发 → 汇总 → HiL gate → 装配
        │
   ┌────┼────────┬────────┬────────┐
   ▼    ▼        ▼        ▼        ▼
[Eng] [Proc]   [Fin]   [Com]   (并行，读同一 BOMTree)
   │    │        │        │
   └────┴────────┴────────┴──► Blackboard (共享状态)
        │
        ▼
[Review Gates] ── 风险触发 → 暂停 → 人工决策 → 恢复
        │
        ▼
[Quote Assembler] ──► QuoteDraft (报价函+成本明细+风险+假设+例外+评审轨迹)
```

## 4. Repo 结构（Codex 必须遵守，详见 `docs/01-repo-structure.md`）

```
rfq-quote-agent/
├── AGENTS.md                      # 本文件
├── docs/                          # 架构/结构/schema 规范（只读，Codex 参照执行）
│   ├── 00-architecture.md
│   ├── 01-repo-structure.md
│   └── 02-shared-schemas.md
├── tasks/                         # 给 Codex 的任务 prompt（按编号顺序执行）
│   ├── 10-orchestrator.md
│   ├── 11-engineering.md
│   ├── 12-procurement.md
│   ├── 13-finance.md
│   ├── 14-commercial.md
│   ├── 15-ingestion.md
│   ├── 16-assembler.md
│   ├── 17-human-loop.md
│   ├── 20-tool-layer.md
│   ├── 30-eval-harness.md
│   └── 40-iteration-loop.md
├── src/rfq_agent/
│   ├── schemas/                   # Pydantic 模型
│   ├── tools/                     # 纯函数工具
│   ├── agents/                    # orchestrator + 4 sub-agents + ingestion + assembler
│   ├── gates/                     # HiL review gate 引擎
│   ├── prompts/                   # 各 sub-agent 的 LLM system prompt（运行时资产）
│   └── runner.py                  # 端到端入口
├── tests/
│   ├── unit/
│   ├── eval/                      # 3 个金样例 + 通过门槛
│   └── fixtures/                  # 样例 RFQ PDF/XLSX
└── requirements.txt
```

## 5. 工作方式（Codex 执行协议）

1. 每次会话：读 `AGENTS.md` → 读 `docs/` → 读 `tasks/` 下一个未完成任务。
2. 任务 prompt 文件头部标注 `Status: TODO | DOING | DONE`。Codex 接手前先改为 DOING，完成后改 DONE 并在文件末尾追加 `## 完成记录`（改了哪些文件、关键决策、遗留问题）。
3. **小步提交**：一个任务一次 PR，PR 标题 = 任务文件编号+标题。
4. **不许跨任务超前实现**：只做当前任务 prompt 明确要求的。下个任务的模块即使"顺手"也不要写。
5. 遇到 schema 不一致或架构歧义：**停止并在 PR 描述里提结构化问题**，不要自行发明。
6. 每个任务结束前跑 `pytest tests/` 必须全绿。

## 6. 编码规范

- Python 3.11+，类型注解强制，`ruff` + `mypy --strict` 通过。
- Pydantic v2，模型 `model_config = ConfigDict(frozen=True)` 除非需可变。
- LLM 调用封装在 `src/rfq_agent/llm/` 抽象后，sub-agent 不直接调 OpenAI/Anthropic SDK。便于 mock。
- 工具层零 LLM 依赖。
- 日志：`structlog`，每条带 `rfq_id`、`agent`、`step`。

## 7. Definition of Done（整个项目）

- [ ] 3 个 eval fixture 端到端跑通，输出 QuoteDraft 通过金样例比对（成本容差 ±5%、风险全捕获、gate 正确触发）
- [ ] `pytest --cov >= 80%`，工具层 >= 95%
- [ ] HiL gate 演示：模拟人工决策能恢复流水线
- [ ] `mypy --strict` + `ruff` 零告警
- [ ] `README.md` 含一键运行命令与架构图

## 8. 反模式（禁止）

- ❌ 把 4 个 sub-agent 合并成一个大 prompt 顺序问 LLM
- ❌ 用 LLM 做成本计算（成本必须走确定性工具）
- ❌ sub-agent 之间直接互调，必须经 Orchestrator/Blackboard
- ❌ 在 HiL gate 之外"顺便"问人工
- ❌ 输出自由文本报价，必须落到 `QuoteDraft` schema 再渲染
