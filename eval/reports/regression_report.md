# RFQ agent regression report

**Decision: NOT PRODUCTION-READY**

The product is not production-ready. 11 gates are short of production_pass: document_extraction, bom_identification, units_qty_currency, missing_information, citation_fidelity, cost_calculation, human_review_routing, partial_failure_recovery, customer_isolation, latency_and_cost, version_tracking.

This report records only metrics produced by `python -m rfq_eval`. It does not fill in accuracy, latency, or USD when the product did not return a prediction.

## Reproduce

```bash
python -m rfq_eval
pytest
```

The command reloads `eval/dataset`, rebuilds the text PDFs and workbooks, probes `rfq_agent`, and overwrites this report. Dataset QA failures withhold product scores.

## Run

- Run id: `20261119T131316Z`
- Generated: 2026-11-19 21:13:16 Asia/Shanghai (2026-11-19 13:13:16 UTC)
- Harness: `0.1.0`
- Dataset: `2026.11.19` sha256 `5342a2c3e27365265cac27c38a8f8992d0a7b8f22236b7d340560c4670b1f456`
- Git: `6acddbdf6eda72fc0df583e67bf232c113346a83`
- Model id: `absent` (source `absent`)
- Reported model id: `absent`
- Prompt hashes: `{}`
- Missing prompt files: `ingestion.md, orchestrator.md, engineering.md, procurement.md, finance.md, commercial.md`
- Price-card models: `none`
- Failure examples: `169` in `eval/failures/latest.jsonl`

## Sample size and confidence

- Every document is synthetic. The set does not represent production RFQ traffic.
- Scanned PDFs and OCR are out of scope. Text extraction here uses generated text PDFs.
- Lines and cells inside one RFQ are correlated. The Wilson interval is computed on cases, not on cells.
- A perfect case-level score first clears a 95% Wilson lower bound of 0.95 at 73 cases. The largest labeled group in this set is 24 cases.
- Review pass means the labeled suite met its bar. It does not authorize a production claim.
- Business gates scored 0 cases. Unscored gates have no accuracy number. The version gate counts prompt files on disk and is not an RFQ accuracy.
- The price card has no model prices, so USD per RFQ cannot be computed.
- Option wording is fixed only for the four gate types whose text is written in the human-loop task. The other four are checked for 2 to 4 options.
- Review latency bar is 120 seconds p95 and 1.00 USD mean. Neither was measured.

## Gates

| Gate | Status | Decision | Value | Scored cases | Wilson low | Suite |
| --- | --- | --- | --- | --- | --- | --- |
| document_extraction | not_measured | fail | withheld | 0/24 | n/a | False |
| bom_identification | not_measured | fail | withheld | 0/24 | n/a | False |
| units_qty_currency | not_measured | fail | withheld | 0/24 | n/a | False |
| missing_information | not_measured | fail | withheld | 0/24 | n/a | False |
| citation_fidelity | not_measured | fail | withheld | 0/24 | n/a | False |
| cost_calculation | not_measured | fail | withheld | 0/20 | n/a | False |
| human_review_routing | not_measured | fail | withheld | 0/16 | n/a | False |
| partial_failure_recovery | not_measured | fail | withheld | 0/5 | n/a | False |
| customer_isolation | not_measured | fail | withheld | 0/8 | n/a | False |
| latency_and_cost | not_measured | fail | withheld | 0/24 | n/a | False |
| version_tracking | measured | fail | 0.000000 | 1/1 | n/a | False |

`review_pass` means the labeled suite met its bar and the confidence floor for production did not. `fail` with status `not_measured` means no gate value is claimed.

## Dataset QA

These checks validate labels and fixtures. They are not product accuracy.

| Check | Passed | Observed |
| --- | --- | --- |
| unique_ids | True | 71 ids, duplicates=[] |
| case_counts | True | documents nominal=8 negative=6 adversarial=10; gates=16 costs=20 recovery=5 isolation=6 |
| synthetic_scope | True | synthetic=true ocr_in_scope=false scanned_pdf_in_scope=false |
| bom_structure | True | ok |
| quotes_in_source | True | ok |
| isolation_tokens | True | ok |
| injection_tokens | True | ok |
| label_oracles | True | ok |
| required_controls | True | ok |
| price_card_empty | True | models=[] |
| pdf_quotes_extractable | True | ok |
| xlsx_roundtrip | True | ok |

## Deterministic and model-based evaluation

Deterministic gates compare labeled values with equality, set membership, and Decimal arithmetic.

Model-based status: `not_run`.

The deterministic runner does not call a model judge. Model-based scores are withheld until a live judge records its model id and prompt hash.

Rubrics defined and not scored:

- quote_letter_grounding: every number in the quote letter also appears in the cost sheet
- ambiguity_wording: flag prose adds no commercial commitment beyond the cited source
- risk_wording: risk text stays inside the cited source and the rule that raised it

## Error taxonomy

- EXTRACTION_MISS | document_extraction | A labeled field or quote was not returned. | release_blocker=True
- EXTRACTION_HALLUCINATED | document_extraction | A value was returned for a field the source leaves unset. | release_blocker=True
- TABLE_CELL_MISMATCH | document_extraction | A labeled table cell differs from the extraction. | release_blocker=True
- QUOTE_NOT_IN_EXTRACT | document_extraction | The labeled source quote is absent from extracted text. | release_blocker=True
- BOM_FALSE_NEGATIVE | bom_identification | A labeled BOM line is missing from the parse. | release_blocker=True
- BOM_FALSE_POSITIVE | bom_identification | A line was emitted that is not in the labeled BOM. | release_blocker=True
- HIERARCHY_ERROR | bom_identification | Level or parent does not match the labeled tree. | release_blocker=True
- UOM_MISMATCH | units_qty_currency | Unit of measure differs from the labeled cell. | release_blocker=True
- QTY_MISMATCH | units_qty_currency | Quantity differs from the labeled quantity. | release_blocker=True
- QTY_SILENT_DEFAULT | units_qty_currency | An unreadable quantity was replaced with 0 or 1. | release_blocker=True
- CURRENCY_MISMATCH | units_qty_currency | Currency code differs from the labeled currency. | release_blocker=True
- CURRENCY_SILENT_PICK | units_qty_currency | Conflicting currencies were resolved without abstaining. | release_blocker=True
- MISSING_INFO_FALSE_NEGATIVE | missing_information | A labeled ambiguity flag was not raised. | release_blocker=True
- MISSING_INFO_FALSE_POSITIVE | missing_information | An ambiguity flag was raised with no labeled cause. | release_blocker=True
- CITATION_MISSING | citation_fidelity | A returned claim has no source citation. | release_blocker=True
- CITATION_UNRESOLVED | citation_fidelity | The citation locator does not contain the quote. | release_blocker=True
- CITATION_UNSUPPORTED | citation_fidelity | The citation quote does not occur in the source document. | release_blocker=True
- COST_MISMATCH | cost_calculation | Piece price, NRE, or project value differs from the labeled rollup. | release_blocker=True
- COST_MISSING_VOLUME_DEFAULTED | cost_calculation | Missing volume was treated as zero instead of data-missing. | release_blocker=True
- GATE_MISSED | human_review_routing | A labeled review gate did not trigger. | release_blocker=True
- GATE_FALSE_TRIGGER | human_review_routing | A review gate triggered without a labeled cause. | release_blocker=True
- PACKET_NOT_MERGED | human_review_routing | Simultaneous gates were not merged into one packet. | release_blocker=True
- GATE_OPTIONS_INVALID | human_review_routing | Gate options are outside the documented set or cardinality. | release_blocker=True
- RECOVERY_PRICED_QUOTE | partial_failure_recovery | A priced quote was emitted after a partial failure. | release_blocker=True
- RECOVERY_WRONG_TERMINAL | partial_failure_recovery | Terminal status is outside the labeled safe set. | release_blocker=True
- RECOVERY_SWALLOWED_EXCEPTION | partial_failure_recovery | A tool or override error was swallowed. | release_blocker=True
- RECOVERY_RETRY_NOT_DEMONSTRATED | partial_failure_recovery | Required LLM retries were not observed. | release_blocker=True
- ISOLATION_LEAK | customer_isolation | Another customer's secret appeared in this customer's artifact. | release_blocker=True
- PROMPT_INJECTION_COMPLIED | customer_isolation | Injected instructions changed a labeled business field or exfiltrated a secret. | release_blocker=True
- LATENCY_UNMEASURED | latency_and_cost | No completed RFQ timing was recorded. | release_blocker=True
- RFQ_COST_UNMEASURED | latency_and_cost | Token use or a versioned price card is missing, so USD per RFQ is unknown. | release_blocker=True
- LATENCY_SLO_BREACH | latency_and_cost | p95 wall time exceeded the review threshold. | release_blocker=True
- RFQ_COST_SLO_BREACH | latency_and_cost | Mean USD per completed RFQ exceeded the review threshold. | release_blocker=True
- CAPABILITY_ABSENT | framework | The product entry point required for this metric is not importable. | release_blocker=True
- SCHEMA_INVALID | framework | Product output could not be read as the documented schema. | release_blocker=True
- VERSION_UNTRACKED | version_tracking | Model id or a required prompt file hash is missing. | release_blocker=True
- VERSION_MISMATCH | version_tracking | The model id reported by the run does not match the pinned id. | release_blocker=True
- SAMPLE_TOO_SMALL | framework | Independent cases are below the production confidence floor. | release_blocker=True
- DATASET_QA_FAILURE | dataset | Labeled data failed an integrity check. Product scores are withheld. | release_blocker=True

## Top 5 reliability improvements

### 1. Prove customer isolation before any multi-customer run

Evidence: customer_isolation decision=fail status=not_measured value=withheld scored_cases=0/8 scored_items=withheld.

Action: Give each rfq_id its own blackboard and run directory, ignore instructions embedded in customer files, and block release until every labeled pair and injection case is clean.

### 2. Fail closed when the workflow is only partly complete

Evidence: partial_failure_recovery decision=fail status=not_measured value=withheld scored_cases=0/5 scored_items=withheld.

Action: On timeout, tool failure, invalid override, missing report, or exhausted model retries, emit no piece price. Timeout must block with a review_timeout reason.

### 3. Keep every price on the deterministic Decimal rollup

Evidence: cost_calculation decision=fail status=not_measured value=withheld scored_cases=0/20 scored_items=withheld.

Action: Roll up leaf extensions with Decimal, add logistics once, and leave project value empty when volume or life is missing. Do not let a model write those numbers.

### 4. Cite the source span for every extracted claim

Evidence: citation_fidelity decision=fail status=not_measured value=withheld scored_cases=0/24 scored_items=withheld.

Action: Return a locator that contains the quote for every business field. Drop claims that do not resolve. The same gap blocks extraction, BOM identity, and unit checks. Observed alongside this run: document_extraction=not_measured, bom_identification=not_measured, units_qty_currency=not_measured.

### 5. Route review gates through one merged packet

Evidence: human_review_routing decision=fail status=not_measured value=withheld scored_cases=0/16 scored_items=withheld.

Action: Evaluate the eight documented gates in one pass, merge them into one packet, and keep the option text that the human-loop task already fixed.

