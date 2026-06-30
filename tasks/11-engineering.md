# Task 11 — Engineering Agent

Status: TODO

## 目标
实现 `agents/engineering.py`：从工程视角审查 BOM 与规格，产出 `EngineeringReport`。不计算成本（那是采购+财务的活），只识别工程风险与 NRE 工程项。

## 输入
`RFQPackage`（含 `bom_tree`、`spec_doc`、`ambiguity_flags`）+ `QuoteIntent`

## 输出文件
- `src/rfq_agent/agents/engineering.py`
- `src/rfq_agent/prompts/engineering.md`
- `tests/agents/test_engineering.py`

## 职责分解

### 1. BOM 校验
- 层级完整性（已在 schema validator 保证）
- 关键件缺失检测：智驾项目必须有 SoC/MCU + 电源管理 + 通信接口；座舱项目必须有 SoC + 显示 + 音频；摄像头模组必须有 sensor + ISP + 镜头 + serializer。规则表写常量。
- 缺失 → `SpecGap`（spec 要求 vs BOM 缺件）

### 2. Auto-grade 合规
- 遍历 BOM，`auto_grade_required=True` 的行：检查 attributes 是否含 AEC-Q100 等级标识。
- 缺失 → `AutoGradeGap`，severity high（车规件无认证 = 量产风险）

### 3. Spec Gap 分析（LLM）
- LLM prompt（`prompts/engineering.md`）输入：spec_doc.sections + bom_tree 节点摘要。
- 输出：客户规格要求 vs 我方能力/物料属性的 gap 列表。
- 例：客户要求 DDR5-6400，BOM 物料标 DDR5-4800 → `SpecGap(gap_severity=medium)`
- 严格 JSON，schema 对应 `list[SpecGap]`

### 4. DFM 风险（LLM + 规则）
- 规则触发：高密度 PCBA（BOM 层级深、PCBA 行多）、双面贴装、异形结构件公差紧、光学件装配对准。
- LLM 判读具体 DFM 问题与缓解措施。

### 5. VAVE 机会（LLM）
- 识别可降本替代：物料超规格、冗余功能、可集成的分立器件、可取消的涂覆。
- 输出 `VAVEOpportunity`（含估算节省百分比，仅工程判断，不做价格计算）。

### 6. ECN 敏感性（规则）
- 关键件（SoC/Display/Camera/Sensor）的 spec 变更对成本/周期的影响评级。
- 规则：SoC pin-to-pin 兼容变更 = low；封装变更 = medium；换平台 = high。
- 输出 `ECNSensitivity`。

### 7. 工程 NRE
- 列出工程侧一次性投入：模具（结构件）、治具（装配/测试）、验证（DV/PV/EMC/环境）、软件许可（OS/中间件/地图/Navi）。
- 每项 `NRELine(item, description, cost, currency, one_time=True)`。
- **成本数字由规则表估算**（按物料类别+复杂度档位），不调 LLM。规则表常量可配置。

## LLM 边界
- Spec gap / DFM / VAVE 用 LLM（理解+判读）。
- BOM 校验 / auto-grade / ECN 敏感性 / NRE 估算 全规则化。

## 验收标准
1. case2 座舱核心板：标出 SoC 单源风险（移交 procurement 复核）、至少 1 个 spec gap、NRE 含模具+治具+验证+软件许可 4 类。
2. case3 摄像头：标出光学件 spec gap、DFM 风险（镜头对准）、auto-grade 缺口（若 sensor 未标 AEC-Q100）。
3. case1 简单 PCBA：无 spec gap，NRE 仅治具+验证。
4. LLM 用 mock 回放，单测确定性。
5. `EngineeringReport` 通过 schema 校验。
6. `mypy --strict` 通过。

## 约束
- 不计算 unit price、不评估 margin（财务域）。
- 不评估供应商landscape（采购域）。
- NRE 估算只出工程项，商务 NRE（认证/差旅）归 commercial。
- VAVE 节省百分比是工程判断，最终金额由采购/财务换算。
