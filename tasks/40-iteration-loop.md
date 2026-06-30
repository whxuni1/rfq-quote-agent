# Task 40 — Codex 迭代协议（人机协作 SOP）

Status: TODO（参考文档，无需代码产出）

## 目标
定义"人如何用 Codex 把这个 repo 从零建起来"的迭代节奏。这不是一次性生成，是分任务、小步提交、人工 gate 的工程过程。

## 前置准备（人工，5 分钟）
1. 建空 repo，把 `AGENTS.md` + `docs/` + `tasks/` 全部拷入。
2. `git init`，首次提交 = prompt set 全集。
3. 在 `tasks/` 每个 `.md` 头部确认 `Status: TODO`。
4. 配置 Codex 工作目录指向该 repo，确保 Codex 读到 `AGENTS.md`。

## 执行顺序（严格按编号）

任务有依赖关系，必须按此顺序：

```
15-ingestion  ──►  20-tool-layer（部分）──►  11-engineering
                                          ──►  12-procurement
                                          ──►  14-commercial
13-finance（依赖 12 的 should_cost + 11 的 NRE）
17-human-loop（依赖 11/12/13/14 的 report）
16-assembler（依赖全部 report）
10-orchestrator（依赖 11-17 全部 agent）
30-eval-harness（依赖 10 + 全部）
```

建议批次：
- **Batch 1**：15 → 20（pdf/xlsx/should_cost 部分）
- **Batch 2**：11、12 并行 → 13 → 14
- **Batch 3**：17 → 16 → 10
- **Batch 4**：30（含 fixture 生成）→ 全量 eval → 修缺

## 单任务迭代闭环（每个任务）

1. **接手**：把任务 `.md` 的 `Status: TODO` 改 `DOING`。
2. **理解**：让 Codex 读 `AGENTS.md` + 对应 `docs/` + 该任务 `.md`，复述任务目标与验收标准（强制确认理解）。
3. **实现**：Codex 写代码 + 测试。一个任务一个 PR。
4. **验证**：`pytest tests/` + `mypy --strict` + `ruff` 必须全绿。Codex 自跑后才提 PR。
5. **人工 review**：人审 diff，重点看：
   - 是否越界实现（做了下个任务的模块）
   - 是否幻觉 API
   - schema 字段是否与 `docs/02-shared-schemas.md` 一致
   - LLM 边界是否守住（数字处禁用 LLM）
6. **合并**：merge 后把任务 `.md` 改 `Status: DONE`，追加 `## 完成记录`。
7. **下一个**。

## 人工介入信号（Codex 必须停下问）

Codex 遇到以下情况**停止并提问**，不得自行决策：
- schema 字段在 task prompt 与 `docs/02` 间不一致
- 架构歧义（如某职责归属不清）
- 需要新第三方库（须确认）
- 测试 fixture 与现实业务明显不符
- LLM 边界判断模糊（某计算"看起来该用 LLM"）

提问格式：
```
[BLOCKER] task=15-ingestion
问题：BOMTree.currency_hint 与 QuoteIntent.currency 冲突时取哪个？
依据：docs/02 中两者均可空，task 未指定优先级。
候选：A) intent 优先 B) bom 优先 C) 触发 ambiguity
```

## 反震荡规则

- 同一问题 Codex 改了 2 次仍 fail → 停，人工介入根因分析，不要硬改。
- 累计 PR 失败 3 次同类型（如 schema 校验）→ 暂停，回头审 `docs/02` 是否需修订。

## Definition of Done（全项目）

见 `AGENTS.md` §7。最后由 Task 30 的 eval suite 全绿 + 人工抽检 1 个 case 的 QuoteDraft 输出质量签字。

## 迭代节奏建议

- 单任务 PR 目标 < 400 行 diff（不含测试）。超了说明任务粒度太大，拆。
- 全项目预估 8-12 个 PR，2-3 个工作日（含人工 review）。
- 不要让 Codex 一次跑完所有任务——会失序、会越界、会幻觉。批次 + 人工 gate 是质量底线。
