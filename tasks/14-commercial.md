# Task 14 — Commercial Agent

Status: TODO

## 目标
实现 `agents/commercial.py`：解析客户商业条款、对照我方标准条款库、识别 term gap、产出 `CommercialReport`。LLM 用于条款理解与 gap 判读，规则库用于匹配。

## 输入
`RFQPackage`（含 `spec_doc.commercial_req_raw`）+ `QuoteIntent` + `EngineeringReport`（取 NRE 工程项，合并商务 NRE）

## 输出文件
- `src/rfq_agent/agents/commercial.py`
- `src/rfq_agent/prompts/commercial.md`
- `src/rfq_agent/data/standard_terms.yaml`（我方标准条款库，纯文档资产）
- `tests/agents/test_commercial.py`

## 职责分解

### 1. 条款解析（LLM）
- `prompts/commercial.md` 输入：`commercial_req_raw`（客户原文片段）。
- 输出 JSON：`{incoterm, payment_terms, warranty: {months, mileage, scope}, liability_cap_pct, ip_terms, penalty_clauses, exclusivity, volume_commitment, quote_validity_req}`。
- 客户未提的字段 → null，标 `term_undefined` 歧义。

### 2. 标准条款对照（规则）
- 读 `data/standard_terms.yaml`（我方默认：Incoterms FCA 工厂、月结 60、保修 36 月/10 万公里、liability cap 100% 合同额、IP 我方保留、报价有效期 30 天）。
- 逐项比对：客户要求 vs 我方标准 → `TermGap(term, customer_req, our_standard, severity)`。
- severity 规则：
  - liability_cap > 100% → critical
  - 保修 > 60 月或里程 > 15 万公里 → high
  - IP 独家许可给客户 → high
  - payment_terms < 30 天 → medium
  - Incoterms 偏向 DDP（我方承担物流风险）→ medium

### 3. 商务 NRE
- 合并工程 NRE + 商务 NRE（认证费如 IATF/CE/FCC、客户特定审核费、首批 PPAP 包装）。
- 商务 NRE 项规则化（按 project_type 与 customer 要求触发）。

### 4. Penalty 与 Exclusivity
- penalty_clauses：客户要求逾期罚款 → 标 cap_pct（建议 ≤ 合同额 10%）。
- exclusivity：客户要求独家供应 → high severity（限制我方市场化）。

### 5. Quote Validity
- 默认 30 天；客户要求 >90 天 → medium gap（价格波动风险）。
- 最终 `quote_validity_days` = min(客户要求, 我方上限 60)，超限 gate。

## LLM 边界
- 仅条款解析 + gap 描述。
- 金额数字（liability_cap_pct 等）由 LLM 抽取客户原文数字，但**对照规则与 severity 全规则化**。
- LLM 不得编造客户未提的条款。

## 验收标准
1. case2 座舱：客户要求 DDP + 保修 48 月 + liability cap 150% → 3 个 TermGap（incoterm medium / warranty high / liability critical），其中 liability critical 触发 gate（Task 17）。
2. case3 摄像头：客户未提保修 → `term_undefined`，填我方标准。
3. case1 简单 PCBA：条款温和，无 critical gap。
4. `standard_terms.yaml` 可被规则引擎加载，字段完整。
5. `test_commercial.py` 覆盖：4 类 severity 触发、null 字段处理、NRE 合并。
6. `mypy --strict` 通过。

## 约束
- 不评估成本/margin（财务域）。
- 不评估物料风险（工程/采购域）。
- `standard_terms.yaml` 是可配置资产，便于策略调整。
- LLM 抽取的数字必须经规则校验（如 liability_cap_pct ∈ [0, 500]），异常 → gate `DATA_MISSING`。
