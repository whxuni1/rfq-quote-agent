---
name: rfq-evaluation
description: 按三个金样例验收 RFQ 报价结果。在核对 QuoteDraft、编写或修改 tests/eval、判断 gate 与成本容差是否通过时使用。
---

# RFQ 评估

评估一份报价是否可交付。读 `docs/acceptance-criteria.md` 和 `tasks/30-eval-harness.md`，再对照 `evals/README.md` 里的案例。不改金样例数字来换取通过。

## 步骤

1. 确认输入是哪一个 fixture：`case1_simple_pcba`、`case2_cockpit_core`、`case3_adas_camera`。缺 fixture 或金样例时停住，不要用临时数字代替。
2. 用 mock LLM 与 `meta.yaml` 里写好的人工决策跑 `run_rfq`。eval 不联网，不调用真实模型。
3. 逐项核对，并按案例写出通过或失败：
   - `piece_price`、`nre_total` 相对金样例 ±2%。
   - `total_project_value` 相对金样例 ±5%。
   - `risk_register` 条数不低于金样例下限，`critical_count` 相等。
   - `review_trail` 长度与金样例一致，成功路径的 `incomplete_reason` 为空。
   - case1 无 gate，status 为 `done`。
   - case2 至少触发 `SINGLE_SOURCE_CRITICAL`、`TERM_GAP_CRITICAL`、`MARGIN_FLOOR_BREACH`，合并成一个 `ReviewPacket`。
   - case3 触发 `SPEC_GAP_HIGH` 与 `SINGLE_SOURCE_CRITICAL`；脚本化 override 后采购重跑，gate 关闭，例外清单含规格降级声明。
4. 抽查金额来自 `should_cost` 与 `cost_rollup`，不是模型生成的数字。
5. 失败时列出案例、字段、期望、实际。不放宽容差，不删除风险项。

## 不做

- 不把四个 sub-agent 收成一次模型调用再评估。
- 不在生产代码路径启用 mock 响应。
- 金样例首次由人工确认后冻结；评估者只比对，不改写冻结值。
