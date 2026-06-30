# Task 30 — Eval Harness（金样例与端到端验证）

Status: TODO

## 目标
建立 3 个端到端 fixture + 金样例比对，作为整个项目 DoD 门槛。Codex 必须先建 fixture 再跑 eval，确保 pipeline 端到端可运行。

## 输出文件
- `tests/fixtures/case1_simple_pcba/`（rfq.pdf + bom.xlsx + meta.yaml）
- `tests/fixtures/case2_cockpit_core/`（rfq.pdf + bom.xlsx + meta.yaml）
- `tests/fixtures/case3_adas_camera/`（rfq.pdf + bom.xlsx + meta.yaml）
- `tests/eval/golden/case1_quote.json`、`case2_quote.json`、`case3_quote.json`
- `tests/eval/test_eval_suite.py`
- `src/rfq_agent/runner.py`（端到端入口）

## Fixture 设计

### case1 — 简单 PCBA + 结构件
- BOM 1 层 + 1 子层，~15 行：MCU + 电源 IC + 连接器 + 电阻电容 + PCB + 铝外壳 + 螺丝。
- 客户规格温和，条款标准，无单源。
- 预期：无 gate 触发，一气呵成 `done`。
- 金样例：piece_price、NRE、total_project_value 精确值。

### case2 — 智能座舱核心板
- BOM 3 层，~40 行：SoC（高通8295）/ DDR5 / NAND / PMIC / 显示驱动 / 摄像头 / 麦克风 / Wi-Fi 模组 / PCBA / 散热 / 屏幕总成。
- SoC 单源（Qualcomm）、display 单源。
- 客户要求 DDP + 保修 48 月 + liability cap 150%。
- 预期：触发 `SINGLE_SOURCE_CRITICAL`（SoC）+ `TERM_GAP_CRITICAL`（liability）+ `MARGIN_FLOOR_BREACH`（mock margin 压低）。
- 金样例：人工 override 后的 piece_price、NRE、风险登记 critical 数量、评审轨迹长度。

### case3 — ADAS 前视摄像头模组
- BOM 2 层，~25 行：image sensor（Sony IMX）+ ISP + serializer + 镜头组 + IR-cut filter + PCBA + 结构件 + 连接器。
- 客户规格要求 8MP/120dB HDR，BOM sensor 标 4MP → spec gap high。
- sensor 单源。
- 预期：触发 `SPEC_GAP_HIGH` + `SINGLE_SOURCE_CRITICAL`，人工 override 指定替代 sensor → 重跑 procurement → gate 关闭。
- 金样例：override 后的 should_cost 差异、piece_price、例外清单含 spec 降级声明。

### Fixture 文件生成
- `rfq.pdf`：用 `reportlab` 生成（文本可抽取，非扫描）。脚本 `tests/fixtures/build_fixtures.py`。
- `bom.xlsx`：用 `openpyxl` 生成。同脚本。
- `meta.yaml`：客户名、项目类型、量纲、币种、预期 gate 列表。

## 金样例比对（`test_eval_suite.py`）

```python
@pytest.mark.parametrize("case", ["case1","case2","case3"])
async def test_end_to_end(case, mock_llm, mock_reviewer):
    quote = await run_rfq(pdf, xlsx, llm=mock_llm, reviewer_cb=mock_reviewer)
    golden = load_golden(case)
    assert quote.piece_price == pytest.approx(golden.piece_price, rel=0.02)
    assert quote.nre_total == pytest.approx(golden.nre_total, rel=0.02)
    assert quote.total_project_value == pytest.approx(golden.total_project_value, rel=0.05)
    assert len(quote.risk_register.items) >= golden.min_risk_count
    assert quote.risk_register.critical_count == golden.critical_count
    assert len(quote.review_trail) == golden.review_trail_len
    assert quote.incomplete_reason is None
```

### mock_reviewer
按 case 的 `meta.yaml` 预期 gate 顺序返回 `ReviewDecision`（确定性回放人工决策）。这样 eval 全程无真人介入。

### mock_llm
`llm/mock.py` 按 (agent, input_hash) 回放固定 JSON。mock 响应库 `tests/eval/mock_responses/` 每个场景一个 JSON 文件。

## runner.py

```python
async def run_rfq(
    pdf_path: str,
    xlsx_path: str,
    *,
    rfq_id: str | None = None,
    llm: LLMClient | None = None,
    reviewer_cb: Callable[[ReviewPacket], Awaitable[ReviewDecision]] | None = None,
    config: Config | None = None,
) -> QuoteDraft: ...
```
- 默认 LLM 用真实 client（生产），测试注入 mock。
- 默认 reviewer_cb 为 None → gate 触发即 `blocked`（生产需显式注入）。
- 返回 `QuoteDraft`，同时落 trace 到 `./runs/<rfq_id>/`。

## 验收标准
1. 3 case 端到端全绿。
2. case1 无 gate；case2 触发 ≥3 gate 合并为 1 packet；case3 override 后重跑成功。
3. 金样例数字容差：piece_price/NRE ±2%，total ±5%。
4. risk_register 与 review_trail 数量匹配金样例。
5. `pytest tests/` 全绿，整体覆盖率 ≥ 80%。
6. `mypy --strict` + `ruff` 零告警。

## 约束
- Fixture 必须可由脚本重新生成（`build_fixtures.py`），不依赖手工编辑二进制。
- 金样例首次由人工审核确认后冻结，提交入仓。
- mock 响应不得在生产路径生效（`mock.py` 只在测试 import）。
- eval 测试不得联网。
