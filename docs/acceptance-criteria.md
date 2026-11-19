# 验收标准

项目完成指下面每一条都成立。评估步骤见 `.cursor/skills/rfq-evaluation/SKILL.md`，案例索引见 `evals/README.md`。

## 报价结果

三个 fixture 端到端跑通，输出通过 schema 校验的 `QuoteDraft`：

| 案例 | fixture | 必须看到 |
|---|---|---|
| case1 简单 PCBA + 结构件 | `tests/fixtures/case1_simple_pcba/` | 无 gate，status `done`，`incomplete_reason` 为空 |
| case2 智能座舱核心板 | `tests/fixtures/case2_cockpit_core/` | `SINGLE_SOURCE_CRITICAL`、`TERM_GAP_CRITICAL`、`MARGIN_FLOOR_BREACH` 合并为一个 `ReviewPacket` |
| case3 ADAS 前视摄像头 | `tests/fixtures/case3_adas_camera/` | `SPEC_GAP_HIGH` 与 `SINGLE_SOURCE_CRITICAL`；override 后采购重跑且 gate 关闭；例外清单含规格降级 |

数值容差相对冻结金样例：

- `piece_price` 与 `nre_total`：±2%
- `total_project_value`：±5%
- `risk_register` 条数不低于金样例下限，`critical_count` 相等
- `review_trail` 长度与金样例一致

`AGENTS.md` 的项目级成本容差是 ±5%。eval 对单价和 NRE 使用更紧的 ±2%。金样例经人工确认后冻结，不因实现漂移而改写。

## 结构与不变量

- `CostBreakdownLine.extended_price` 等于 `qty_per * unit_price`，量化到 4 位。
- 金额 `Decimal >= 0`，`qty_per > 0`。
- BOM 第 0 层没有父件；更深层的 `parent_line_no` 指向存在的行。
- `proposed_margin_pct` 低于 `target_margin_pct` 时，`margin_floor_breached` 为真。
- `ReviewPacket.gates` 非空。
- 单价、毛利和汇总来自 `tools/should_cost.py` 与 `tools/cost_rollup.py`。

## 人工回路

脚本化 `reviewer_cb` 能让流水线从 `awaiting_review` 恢复。未注入回调时，gate 触发使运行进入 `blocked`，草稿写出 `incomplete_reason`。

## 工程门槛

- `pytest tests/` 全绿。
- 整体覆盖率 ≥ 80%，工具层 ≥ 95%。
- `mypy --strict` 与 `ruff` 零告警。
- `README.md` 含一键运行命令和架构图。
- fixture 可由 `tests/fixtures/build_fixtures.py` 重新生成。
- eval 与单测不联网。`llm/mock.py` 只被测试导入。

## 当前状态

编号任务仍是 `TODO`。本文件是完成线，不是对当前仓库已实现行为的声明。`tests/` 与 `evals/` 在任务 30 落地前只保留契约说明。
