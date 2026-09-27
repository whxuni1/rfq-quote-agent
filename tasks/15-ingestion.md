# Task 15 — Ingestion Parser Agent

Status: DOING

## 目标
实现 `agents/ingestion.py` + `tools/pdf_extract.py` + `tools/xlsx_bom.py`，把 RFQ 包（PDF + Excel）转为 `RFQPackage`。这是 pipeline 唯一入口，产出必须 schema 合法且零外部依赖。

## 输入
- `pdf_path: str`（RFQ 技术规格书）
- `xlsx_path: str`（BOM，可能多 sheet）
- `rfq_id: str`

## 输出文件
- `src/rfq_agent/tools/pdf_extract.py`
- `src/rfq_agent/tools/xlsx_bom.py`
- `src/rfq_agent/agents/ingestion.py`
- `src/rfq_agent/prompts/ingestion.md`（运行时 LLM system prompt）
- `tests/unit/test_xlsx_bom.py`
- `tests/agents/test_ingestion.py`

## 实现要求

### `pdf_extract.py`
- 用 `pdfplumber` 抽取文本与表格。输出 `SpecDoc`（sections / quantity_req / delivery_req / commercial_req_raw / quality_req）。
- 文本切分：按 H1/H2 标题（字号启发式或大写行）切 section。
- 表格保留为 `list[list[list[str]]]`。
- **不做语义理解**，只做结构抽取。语义理解交给 `IngestionAgent` 的 LLM 步骤。

### `xlsx_bom.py`
- 用 `openpyxl` 读多 sheet。识别哪个 sheet 是 BOM（含 "Part No"/"物料号"/"Qty"/"用量" 列）。
- 层级识别策略（按优先级）：
  1. 显式 level 列（"Level"/"层级"）
  2. 缩进（前导空格/制表符计数）
  3. 父件号列（"Parent"/"父件"）
  4. 退化：全部 level=1，root 用项目名构造
- 物料分类：`material_class` 用关键词规则映射（SoC/MCU/DDR/NAND/Display/Camera/PCB/Connector/Housing/Harness/...）。规则表写在 `xlsx_bom.py` 顶部常量，可配置。
- `single_source_risk` 预判：source_hint 含单一厂商名且无备选 → True。
- `auto_grade_required`：spec 文本含 "AEC-Q100"/"车规"/"automotive grade" → True。
- 输出 `BOMTree`，校验 level/parent 一致性（validator）。

### `IngestionAgent`
- 顺序：`pdf_extract` → `xlsx_bom` → LLM 理解（生成 `QuoteIntent` 草稿 + `AmbiguityFlag` 列表）。
- LLM system prompt（`prompts/ingestion.md`）要求：
  - 从 spec_doc + bom_tree 提取项目类型/量纲/币种/交付/特殊要求
  - 标记歧义：spec 缺口、用量模糊、UOM 冲突、图纸引用缺失、条款未定义
  - 输出**严格 JSON**，schema 对应 `QuoteIntent` + `AmbiguityFlag[]`
- LLM 输出经 Pydantic 校验失败 → 重试 1 次（带 schema 错误提示），仍失败抛 `IngestionError`。
- 产出 `RFQPackage`（含 `ambiguity_flags`）。

### 歧义标记规则
- 客户规格出现但 BOM 无对应物料 → `spec_gap` high
- BOM 物料数量单位与常规不符（如 SoC 按"米"计） → `uom_ambiguous`
- 同一物料不同 sheet 量不同 → `qty_ambiguous`
- source_hint 指定厂商但无料号 → `source_conflict` medium
- 图纸引用号在文件包中找不到 → `drawing_missing` high

## 验收标准
1. 3 个 fixture（`tests/fixtures/case1..3`）跑通，产出 `RFQPackage` 通过 schema 校验。
2. BOM 多层级正确：case2 智能座舱核心板至少 3 层，root=组件，level=2 含 SoC/DDR/NAND。
3. 歧义标记：case3 ADAS 摄像头模组至少标出 1 个 spec_gap（光学规格 vs BOM 缺失）。
4. `test_xlsx_bom.py` 覆盖：单 sheet/多 sheet/层级策略 1-4/异常列名。
5. 全程零网络调用。LLM 用 `llm/mock.py` 注入回放，单测确定性。
6. `mypy --strict` 通过。

## 约束
- 不解析图纸（PDF 图纸二进制跳过，仅记录 `DrawingRef`）。
- 不调 OCR；fixture PDF 必须是文本可抽取（测试前提）。
- 不得为"提高准确率"引入任何外部 API。

## 完成记录

> 状态保持 DOING，PR 合并后改 DONE（见 `tasks/40-iteration-loop.md` 第 6 步）。

### 改动文件
- 项目骨架：`pyproject.toml`（ruff / mypy --strict / pytest 配置）、`requirements.txt`、`requirements-dev.txt`、`.gitignore`
- Schema（仅本任务所需）：`schemas/rfq.py`、`schemas/bom.py`、`schemas/intent.py`
- LLM 抽象：`llm/base.py`（`LLMClient` 协议）、`llm/mock.py`（回放 mock）
- 工具：`tools/pdf_extract.py`、`tools/xlsx_bom.py`、`tools/__init__.py`（`ToolError`）
- Agent：`agents/ingestion.py`、`prompts/ingestion.md`、`prompts/__init__.py`（`load_prompt`）
- 测试：`tests/unit/test_xlsx_bom.py`、`tests/unit/test_pdf_extract.py`、`tests/unit/test_schemas_bom.py`、`tests/agents/test_ingestion.py`
- Fixture：`tests/fixtures/build_fixtures.py` 生成 case1..3 的 `spec.pdf` / `bom.xlsx` / 图纸占位 / `llm_ingestion.json`

### 关键决策
1. **歧义标记分两层**：可机械判定的 5 类（spec_gap / uom / qty 跨 sheet / source_conflict / drawing_missing）走确定性规则；LLM 只补充语义歧义。规则优先，与规则同 (category, line) 的 LLM flag 去重；最终统一编号 `AMB-001..`。
2. **spec_gap 规则**：规格章节标题经 `classify_material` 命中某物料类别、而 BOM 无该类别 → high。保守但确定。
3. **3 个 fixture 分别覆盖 3 种层级策略**：case1 level 列、case2 缩进（3 层 + 多 sheet 用量冲突）、case3 父件列。
4. **PDF fixture 用内置极简 PDF 写入器生成**，未引入 reportlab 等新依赖。
5. **图纸查找**：在 `package_dir`（默认 PDF 所在目录）下递归匹配文件名前缀 = 图纸号。

### 遗留问题（结构化提问，需人工确认）
```
[BLOCKER] task=15-ingestion
问题：QuantityReq / DeliveryReq / QualityReq 在 docs/02 只有类型名、无字段定义。
依据：docs/02 §1 SpecDoc。
当前实现：QuantityReq(annual_volume, project_life_years, raw_text)、
          DeliveryReq(sop_date, incoterm, delivery_location, raw_text)、
          QualityReq(standards, ppap_level, raw_text)。
候选：A) 采纳并回写 docs/02  B) 另行指定字段
```
```
[BLOCKER] task=15-ingestion
问题：Ingestion 的 LLM 产出 QuoteIntent 草稿，但 RFQPackage 无字段承载它。
依据：本任务要求"生成 QuoteIntent 草稿"，docs/00 又规定 Orchestrator.plan() 生成 QuoteIntent。
当前实现：IngestionAgent.run() 返回 tuple[RFQPackage, QuoteIntent]。
候选：A) 保持，Task 10 plan() 可把草稿作为参考  B) 丢弃草稿，Ingestion 只产歧义
      C) 在 RFQPackage 增加 intent_draft 字段（需改 docs/02）
```
```
[BLOCKER] task=15-ingestion
问题：parse_bom 权威签名 (xlsx_path, rfq_id) 拿不到项目名，无法按"root 用项目名构造"。
当前实现：增加可选参数 project_name（默认用 rfq_id），不破坏权威签名。
候选：A) 采纳并回写 Task 20 签名  B) 合成 root 一律用 rfq_id
```
- `auto_grade_required` 目前只看行内文本（描述/规格/厂商）。规格书全局"所有 IC 须 AEC-Q100"尚未下传到行，建议由 EngineeringAgent（Task 11）复核。
- 多个 BOM 类 sheet 时，取第一个为主 BOM，其余只参与用量一致性检查。
- 尚无 `.github/workflows/ci.yml`（不属于任何任务），建议单独补。
