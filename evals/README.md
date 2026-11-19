# 评估案例

这里登记三个金样例的通过条件。可执行比对在 `tests/eval/test_eval_suite.py`，由任务 30 实现。本目录不另建一套运行器。

容差：`piece_price` 与 `nre_total` 为 ±2%，`total_project_value` 为 ±5%。风险条数不低于金样例下限，`critical_count` 与 `review_trail` 长度必须一致。成功路径的 `incomplete_reason` 为空。

| 案例 | 场景 | Gate |
|---|---|---|
| `case1` | 简单 PCBA + 结构件，约 15 行，规格温和 | 不触发 |
| `case2` | 座舱核心板，约 40 行；SoC 与显示单源；DDP、48 个月保修、责任上限 150% | `SINGLE_SOURCE_CRITICAL`、`TERM_GAP_CRITICAL`、`MARGIN_FLOOR_BREACH`，合并为一个 packet |
| `case3` | ADAS 前视摄像头，约 25 行；规格 8MP/120dB，BOM sensor 为 4MP；sensor 单源 | `SPEC_GAP_HIGH`、`SINGLE_SOURCE_CRITICAL`；替代 sensor 的 override 后重跑采购 |

Fixture 将位于 `tests/fixtures/<case>/`，含可抽取文本的 `rfq.pdf`、`bom.xlsx` 和 `meta.yaml`。冻结报价位于 `tests/eval/golden/<case>_quote.json`。人工决策由 `meta.yaml` 回放，模型响应由 `tests/eval/mock_responses/` 回放。

评估时使用 `.cursor/skills/rfq-evaluation/SKILL.md`。
