# Error taxonomy

Codes are the regression identifiers stored in `eval/failures/latest.jsonl`.
A code marked release_blocker fails a production decision when it is present on a gate that did not pass.

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
