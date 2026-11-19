---
name: poc-scoping
description: 把 RFQ 报价 Agent 收成一条可演示的概念验证切片。在决定先做什么、写 POC 范围、或判断某模块是否属于当前切片时使用。
---

# 概念验证范围

概念验证要证明一条路径能从 RFQ 包得到结构化 `QuoteDraft`。它不证明全商品库、全条款库或真实模型质量。

先读 `tasks/40-iteration-loop.md` 的批次顺序，以及当前 `tasks/*.md` 的 `Status`。只把状态为当前任务的模块放进切片。下一批的文件即使看起来顺手，也不写。

## 切片内

- 一个可重新生成的 fixture：case1，简单 PCBA 加结构件。规格温和，无单源，预期无 gate。
- Ingestion：可抽取文本的 PDF 与多级 Excel BOM，产出 `RFQPackage`。
- 确定性 should-cost 与自底向上 rollup。金额来自工具。
- Orchestrator 跑完 Wave 1 与 Wave 2，Assembler 写出 `QuoteDraft`。
- 模型调用走 `LLMClient`，本切片用 mock 回放。
- 人工决策用脚本化 `reviewer_cb`。case1 不触发 gate，回调不被调用。

## 切片外

- ERP、PLM、供应商门户、联网询价。
- 扫描件 PDF、图纸几何解析、真实供应商议价。
- case2 与 case3 的单源、规格缺口和条款缺口。它们属于 eval 门槛，不属于第一条演示路径。
- 独立的人工界面。暂停与恢复由 `ReviewGateEngine` 和回调完成。
- 用模型直接填写单价、毛利或成本汇总。

## 完成时留下的范围说明

写清四项：本切片包含的任务编号、明确排除的模块、使用的 fixture、以及“case1 在 mock 下得到 `incomplete_reason` 为空的 QuoteDraft”这条完成条件。Schema 与任务描述冲突时停止，按 `tasks/40-iteration-loop.md` 的 `[BLOCKER]` 格式提问，不另造字段。
