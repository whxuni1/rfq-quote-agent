# 03 — Enterprise Work Graph (RFQ → quotation approval)

Status: design proposal. It does not change the runtime, the task sequence, or the Pydantic contracts in `docs/02-shared-schemas.md`.

Revised after review: an RFQ revision pins the document revisions it contained; tool and model bodies are stored as artifacts, not hashes alone; impact closes over the whole BOM ancestor chain with no silent hop cap; tenant-wide aliases stay unique when `customer_id` is null.

Start anchor: 19 Nov 2026 (Asia/Shanghai). The three increments below are a sequence with exit criteria. They are not a staffing estimate.

## 1. Decision

Use **PostgreSQL as the only store**, with two layers in the same database:

1. Typed current-state tables for the work graph (entities, revisions, a small set of polymorphic links).
2. An append-only `work_event` log that is the replay and audit source.

Keep the in-process `Blackboard` as the scratch pad for a single run. The graph is the system of record around the run.

A dedicated graph database is not part of this design. The queries this product must answer are named, tenant-scoped, and at most a few hops. Impact is computed when a change is committed and stored as rows, so readers do not explore the graph ad hoc. Money stays in `numeric` columns. Tenant isolation is row-level security.

Option A (relational tables alone) is the projection half of this design. Shipping it without the log means reconstructing provenance later from audit columns. Option C (a graph engine beside Postgres) becomes a second system of record before there is a query that needs one.

## 2. What the graph is

The graph is the durable identity, history, and attribution layer for one workflow: a customer RFQ becomes a quotation that a human can approve.

It records:

- who the business objects are, and which revision is current
- which object a number or a judgment came from
- which human, agent, or tool asserted each fact
- what a later change invalidates

It does not replace the orchestrator, the four sub-agents, or the deterministic cost tools. Sub-agents still exchange Pydantic models through the orchestrator. They do not read or write the graph. The runner is the only adapter.

Three existing distinctions carry into the ontology.

| Today | Graph rule |
|---|---|
| `BOMLine` mixes usage and part identity | `BOMItem` is a usage in one structure (qty, parent, find number). `Part` is the thing, shared across RFQs inside one tenant. |
| `ReviewDecision` mixes judgment and sign-off | `Decision` is a judgment with evidence. `Approval` is an authorization of one quote revision. A review can decide without approving. |
| `AgentTrace.output_hash` is the whole trail | `AgentRun` is the execution. `Evidence` is the citable artifact (document span, tool output, rule firing). `CostEstimate` is an immutable computed row whose actor is the tool, not the model. |

The architecture rule still holds: anything that changes a price is `derivation = computed` and is written by a system actor. An agent run may request the computation and may record a classification. It does not own the numeric row.

## 3. Comparison

Scores are design judgments for an early single-team deployment. 5 is more favorable. They are not measurements from production.

| Criterion | A. Relational only | B. PostgreSQL + event log | C. Dedicated graph database |
|---|---|---|---|
| Build cost in the first three increments | Low. Tables match the Pydantic models. | Medium. Same tables, plus an event envelope, idempotency, and a replay test. | High. A second store, a sync path, and Postgres retained anyway for money, RLS, and constraints. |
| Named queries (provenance, BOM tree, where-used, stale lines) | Sufficient with foreign keys and a recursive CTE. History is awkward. | Sufficient, and history is the log. Impact is a stored result of the write. | Native path queries. The headroom is unused while the query set stays named and shallow. |
| Provenance and replay | Audit columns and update-in-place. Replay means guessing past state. | Append-only events. State replay folds the log. Execution replay re-runs with pinned tool I/O. | The graph holds current edges. Replay still needs a log, so C does not remove B. |
| Operational complexity | One database, one backup. | One database. The failure mode to watch is projection drift, which a fold can repair. | Two backups, two tenancy models, a consistency lag between the quote numbers and the edges. |
| Tenant isolation | Row-level security is a mature fit. | Same RLS policy on projection tables and on the log. | Isolation is application-enforced per query. A missing tenant predicate crosses customers. |
| Migration later | The log has to be invented under live rows. | A read-side projector can populate a graph engine from events without changing commands. | Leaving the engine, or keeping it in sync with Postgres, is a permanent job. |

### Query requirements that were checked

| Named query | Depth | How B answers it |
|---|---|---|
| Quote line → cost estimate → tool evidence → document span | 3 | Foreign keys. |
| BOM ancestor / subtree | Typical hardware depth under 8 | Adjacency list plus a materialized path on the revision row. |
| What a BOM, document, or part change makes stale | Whole ancestor chain | Written at commit into `impact_item` by a relational closure. The read is a filter. |
| Where a part is used on open quotes | 2 | Join `part` → `bom_item_revision` → `quote_line`. |
| Replay one RFQ | One stream | `work_event` ordered by `(tenant_id, stream_id, seq)`. |
| Arbitrary cross-program path search | Unbounded | Not a product requirement in this horizon. This is the query that would reopen option C. |

### Recommendation

Build B. Treat A as the projection schema inside B. Hold C until section 10 is true on measured queries.

## 4. Ontology

Thirteen entity types. Two are new relative to the current schemas (`Actor` is infrastructure, counted separately). `Tenant` and `Actor` exist so every other row can name its scope and its author.

### 4.1 Entities

| Entity | Identity | Changes by | Maps from |
|---|---|---|---|
| Tenant | `tenant_id` | Rare. One row even for a single-org install. | New. There is no tenant today. |
| Actor | `actor_id` inside a tenant | New row when the human, the prompt version, or the code SHA changes. | `decided_by`, agent name on traces. |
| Customer | `customer_id` | Revision of commercial attributes only. | `RFQPackage.customer` string. |
| RFQ | `rfq_id` stable for the life of the request | `rfq_revision` for intent, status, received package pointer. | `RFQPackage`, `QuoteIntent`, blackboard status. |
| Document | `document_id` | `document_revision` (immutable bytes addressed by hash). | `SpecDoc`, `DrawingRef`, `raw_files`. |
| BOMItem | `bom_item_id` stable across revisions of the same find | `bom_item_revision` for qty, parent, part, attributes. | `BOMLine`. |
| Part | `part_id` | Attribute revision. External part numbers are aliases. | `BOMLine.part_no` + `attributes`. |
| Supplier | `supplier_id` | Slow-changing profile. | `source_hint`, `supplier_landscape`. Not a first-class model today. |
| Quote | `quote_id` | `quote_revision` pins one RFQ revision and one set of lines. | `QuoteDraft`. |
| CostEstimate | `estimate_id` | Never updated. A new computation inserts a new row and points `supersedes` at the prior one. | `ShouldCostLine`, `CostRollup`, `NRELine`. |
| Task | `task_id` | Status moves through a short enum. | Orchestrator wave step. Implicit today. |
| AgentRun | `run_id` | Insert at start, one completion update that sets terminal fields once. | `AgentTrace`. |
| Decision | `decision_id` | Immutable. | Agent classifications and `GateDecision`. |
| Evidence | `evidence_id` | Immutable. | Tool hashes, rule ids, document spans. Partial in `AgentTrace`. |
| Approval | `approval_id` | Immutable authorization of one quote revision. A later revision needs a new approval. | A `ReviewDecision` that authorizes the quote. Other review outcomes stay decisions. |

Stable ids are UUIDv7, generated by the application. They never encode the tenant, the part number, or the revision.

External identifiers (customer part number, supplier code, customer RFQ number) live in `alias`. The same customer part number in two tenants is two parts. Inside one tenant, two customers can alias different internal parts with the same printed number.

### 4.2 Relationships

Structural relationships are foreign keys. They are the ones the product queries by name.

| Name | From | To | Cardinality | Notes |
|---|---|---|---|---|
| submitted | Customer | RFQ | 1:N | |
| has_document | RFQ revision | Document revision | 1:N | Table `rfq_document`. The snapshot a quote priced. `document.rfq_id` only says which request owns the file. |
| contains | RFQ revision | BOMItem revision | 1:N | The BOM snapshot for that revision. |
| parent_of | BOMItem | BOMItem | tree | `parent_item_id`. Level 0 has no parent, matching the current validator. |
| specifies | BOMItem revision | Part | N:1 | The usage points at the part. |
| known_as | Part | Alias | 1:N | Scheme: `customer_pn`, `internal_pn`, `manufacturer_pn`. Unique including a null `customer_id`, so a tenant-wide internal part number cannot be claimed twice. |
| sourced_from | Part | Supplier | N:M | `landscape`: single, dual, multi, open. Matches `ShouldCostLine.supplier_landscape`. |
| answers | Quote revision | RFQ revision | N:1 | A quote always names the RFQ revision it prices. |
| prices | Quote line | BOMItem revision | N:1 | Line identity follows the BOM item, not the display line number alone. |
| supports | CostEstimate | BOMItem revision | N:1 | Also referenced by the quote line that consumed it. |
| executes | AgentRun | Task | N:1 | A retry is a new run on the same task. |
| requested_by | CostEstimate | AgentRun | N:0..1 | The run asked. The system actor computed. |
| authorizes | Approval | Quote revision | N:1 | |
| supersedes | revision or estimate | prior row | N:1 | Linear history per entity. Branches are out of scope. |

Provenance relationships are rows in `link` because the target type varies.

| Name | From | To | Rule |
|---|---|---|---|
| cites | BOM revision, estimate, decision | Evidence | A `judged` or `overridden` decision has at least one cite. |
| produced | AgentRun | Evidence or Decision | Set when the run completes. |
| based_on | Decision | Evidence | Same constraint as cites, stored so the provenance query is one hop. |
| affects | Decision | Quote, BOMItem, CostEstimate, Approval | The subject columns on `decision` are the authoritative pointer. `link` mirrors them for neighborhood reads. |
| invalidates | ChangeSet | stale target | Written by the impact function. Readers do not re-derive it. |

### 4.3 Actors

`actor.kind` is `human`, `agent`, or `system`.

- A human row carries `human_user_id` inside the tenant.
- An agent row carries `agent_name`, `model_id`, `prompt_version`, and `code_sha`. A prompt or code change is a new actor, so old decisions stay attributed to the version that made them.
- The system actor is the deterministic tool (`should_cost`, `cost_rollup`, `gate_eval`). Cost rows reference this actor.

Every event and every current-state row that asserts a fact has `actor_id` and `source_event_id`.

### 4.4 Derivation

`derivation` is closed:

| Value | Writer | Example |
|---|---|---|
| extracted | system, citing a document span | BOM line parsed from a sheet |
| computed | system | should-cost unit price |
| judged | agent or human, citing evidence | spec-gap severity, risk narrative |
| overridden | human, citing the decision they replaced | gate override payload |
| imported | system | a file dropped into the package, no extract yet |

Invariant, enforced in the command handler and covered by a test: a row with a non-null money column has `derivation = computed` and an actor of kind `system`.

## 5. Cross-cutting rules

### 5.1 Versioning

Parents are stable (`rfq`, `bom_item`, `quote`, `part`). Children are immutable revisions. The parent holds `head_revision`.

A business mutation is a `changeset`: one or more events committed in a single database transaction. Ingest, a human gate decision, a BOM edit, and a re-quote are changesets. Callers address the changeset, not a pile of row updates.

History of a single entity is `supersedes` plus the event stream. There is no update-in-place of a revision row.

### 5.2 Provenance

Evidence kinds: `document_span`, `tool_output`, `rule_firing`, `model_output`, `human_note`, `imported_record`.

A document span stores document id, revision, and a locator inside that revision (page and character range, or sheet and cell). The bytes of the file live behind `document_revision.locator`, addressed by `content_hash`.

A tool output stores tool name and method version, and it references two artifacts: the request body and the response body. A model output stores the prompt version and references the response body. Hashes on the evidence row are copies of `artifact.content_hash` so a citation can be checked without loading the body. They are not a substitute for the body.

An artifact is immutable and content-addressed. The row holds `content_hash`, `media_type`, `byte_size`, and `locator`. The same hash inside a tenant is one artifact. Event payloads store the artifact id and the hash. They do not embed the body. File bytes and model transcripts stay out of `work_event` for the same reason PDF bytes stay out of `document_revision`.

Retention: an artifact referenced by `evidence` is kept for as long as that evidence row exists. A document revision's bytes, behind its own locator, follow the same rule. Those rows are removed only by an operator deleting the stream, which is outside this horizon. A projection rebuild does not delete artifacts or document bytes. Execution replay that cannot read a cited artifact, or whose bytes do not match `content_hash`, fails closed. It does not call the live tool or model to fill the gap.

Model-output evidence supports a classification. It is not a citation for a price. The price citation is the tool-output evidence on the cost estimate, and that evidence's response artifact is what execution replay pins.

### 5.3 Tenant isolation

Every table in section 6 includes `tenant_id`. RLS policies compare it to `current_setting('app.tenant_id')`. The runner sets that config at the start of the transaction and uses a role that is subject to RLS.

No edge crosses tenants. A shared industry catalog, if it ever exists, is an explicit copy into the tenant, recorded as `imported` evidence. Agent connections cannot bypass RLS.

### 5.4 Replay

Two modes, both fed by the same log.

**State replay** folds `work_event` for one stream and rebuilds the projection. This is how projection bugs are repaired and how audits show that the tables match the log. Folding does not call tools or models.

**Execution replay** re-invokes the runner for one task. Tool request and response bodies are loaded from the artifacts cited by that run's evidence. The LLM client is pointed at the stored model-response artifact. This matches the existing mock-LLM test seam. The product uses it to see whether a code change would alter a decision. It writes a new run and new decisions. It does not rewrite the old ones. A missing or hash-mismatched artifact aborts the replay before any tool or model is called.

Commands are idempotent on `(tenant_id, idempotency_key)`. Replaying a command whose body matches the stored hash returns the original changeset. A different body with the same key is a conflict.

### 5.5 Impact analysis

Impact is a pure function of a changeset and the current projection. The command transaction writes every `impact_item` row before commit. There is no hop cap. A changeset that commits has `impact_status = complete`. If the closure cannot be finished, the transaction rolls back and the command returns an error. Readers of a committed changeset do not re-derive dependencies, and they do not have to wonder whether a deep ancestor was skipped.

The function is three SQL closures, not a generic graph walk.

1. **Ancestor closure.** From each changed BOM item, select every item whose `path` is equal to the changed path or is a strict prefix of it (`changed.path = item.path OR changed.path LIKE item.path || '/%'`). A structure change also selects descendants (`item.path LIKE changed.path || '/%'`). Path comparison covers the whole chain, including a leaf whose rollup crosses more than five parents.
2. **Money closure.** Select every `cost_estimate` and `quote_line` whose `bom_item_id` is in that set, then every open `approval` on those quotes. A parent rollup is included because the ancestor is in the set, not because a walker happened to have hops left.
3. **Citation closure.** A document-span change first selects the BOM revisions whose evidence cites that span, then runs closures 1 and 2. A supplier or commodity change first selects the estimates that cite it, then the quote lines and approvals that consume them, plus the ancestor closure of those BOM items.

| Change | Effect | Reason code |
|---|---|---|
| BOM qty, parent, or part changes | The item, its ancestors, and on a structure change its descendants. Their estimates and quote lines become `stale`. Open approvals on those quotes become `reapprove`. | `bom_qty_changed`, `bom_structure_changed`, `part_swapped` |
| Document revision whose span is cited by a BOM line | Those BOM revisions, their ancestor rollups, and their estimates become `stale`. | `document_span_changed` |
| Supplier link or commodity basis cited by an estimate | That estimate, its quote lines, ancestor rollups, and open approvals become `stale`. | `supplier_basis_changed` |
| Human override whose gate lists affected agents | Those tasks become `rerun`. | `override_applied` |
| Approval granted | No downstream stale rows. The approval pins the quote revision it names. | `none` |

`ECNSensitivity` in the engineering report stays an analytical output of the agent. The graph impact function does not call a model and does not invent a cost delta. A cost delta appears only after the tool recomputes a new `CostEstimate`.

Interactive unbounded traversal, across programs and domains, is still the requirement that would justify a graph engine. Impact inside one RFQ is a bounded SQL closure over paths and foreign keys. The API does not offer an open-ended walk, so it does not need a depth cap to stay correct.

## 6. Schema proposal

PostgreSQL 16. Application-generated UUIDv7. Money is `numeric(18,4)`, consistent with the four-decimal `Decimal` rule. Status and kind columns are `text` plus `check` constraints so the list can grow by a migration without a Postgres enum rewrite.

The projection is updated in the same transaction as the event insert. There is no outbox until a second consumer exists.

### 6.1 Tenancy, actors, commands, events

```sql
create table tenant (
  tenant_id uuid primary key,
  name text not null,
  created_at timestamptz not null
);

create table actor (
  tenant_id uuid not null references tenant (tenant_id),
  actor_id uuid not null,
  kind text not null check (kind in ('human', 'agent', 'system')),
  display_name text not null,
  human_user_id text,
  agent_name text,
  model_id text,
  prompt_version text,
  code_sha text,
  created_at timestamptz not null,
  primary key (tenant_id, actor_id),
  check (
    (kind = 'human' and human_user_id is not null)
    or (kind = 'agent' and agent_name is not null and code_sha is not null)
    or (kind = 'system' and agent_name is not null)
  )
);

create table command_log (
  tenant_id uuid not null,
  idempotency_key text not null,
  command_type text not null,
  command_hash text not null,
  changeset_id uuid not null,
  received_at timestamptz not null,
  primary key (tenant_id, idempotency_key)
);

create table changeset (
  tenant_id uuid not null,
  changeset_id uuid not null,
  rfq_id uuid,
  reason text not null check (reason in (
    'ingest', 'bom_edit', 'document_edit', 'human_decision',
    'requote', 'approval', 'replay_repair', 'impact'
  )),
  actor_id uuid not null,
  opened_at timestamptz not null,
  impact_status text not null check (impact_status in ('complete', 'not_applicable')),
  primary key (tenant_id, changeset_id)
);

create table work_event (
  tenant_id uuid not null,
  event_id uuid not null,
  stream_id uuid not null,
  seq bigint not null,
  changeset_id uuid not null,
  event_type text not null,
  schema_version int not null,
  actor_id uuid not null,
  causation_id uuid,
  correlation_id uuid not null,
  payload jsonb not null,
  recorded_at timestamptz not null,
  primary key (tenant_id, event_id),
  unique (tenant_id, stream_id, seq)
);
```

`stream_id` is the RFQ id for RFQ-scoped facts and the part id for part-master facts. Sequence is total per stream, not global. Payload mirrors the typed columns and the artifact ids. It does not embed file bytes, tool bodies, or model transcripts. Queries that filter money, status, or revision use the typed tables. `impact_status` is `complete` when the closure in section 5.5 ran, and `not_applicable` for a changeset that cannot stale anything, such as a pure projection repair. A changeset is not stored with a partial impact list.

Event types for this horizon:

`rfq.ingested`, `document.recorded`, `bom.revised`, `part.aliased`, `supplier.linked`, `task.opened`, `run.started`, `run.completed`, `evidence.recorded`, `decision.recorded`, `estimate.computed`, `quote.assembled`, `review.requested`, `review.decided`, `approval.recorded`, `impact.assessed`.

Past events are never updated. A schema change bumps `schema_version` and the folder gains an upcaster.

### 6.2 Work objects

```sql
create table customer (
  tenant_id uuid not null,
  customer_id uuid not null,
  name text not null,
  created_at timestamptz not null,
  primary key (tenant_id, customer_id)
);

create table rfq (
  tenant_id uuid not null,
  rfq_id uuid not null,
  customer_id uuid not null,
  project_name text not null,
  head_revision int not null,
  status text not null check (status in (
    'ingesting', 'planning', 'executing', 'awaiting_review',
    'assembling', 'done', 'blocked'
  )),
  primary key (tenant_id, rfq_id)
);

create table rfq_revision (
  tenant_id uuid not null,
  rfq_id uuid not null,
  revision int not null,
  received_at timestamptz not null,
  project_type text,
  annual_volume numeric(18,4),
  currency char(3),
  intent jsonb not null,
  supersedes int,
  source_event_id uuid not null,
  actor_id uuid not null,
  primary key (tenant_id, rfq_id, revision)
);

create table document (
  tenant_id uuid not null,
  document_id uuid not null,
  rfq_id uuid not null,
  role text not null check (role in ('spec', 'bom_workbook', 'drawing', 'other')),
  head_revision int not null,
  primary key (tenant_id, document_id)
);

create table document_revision (
  tenant_id uuid not null,
  document_id uuid not null,
  revision int not null,
  content_hash text not null,
  locator text not null,
  media_type text not null,
  file_name text not null,
  source_event_id uuid not null,
  primary key (tenant_id, document_id, revision)
);

create table rfq_document (
  tenant_id uuid not null,
  rfq_id uuid not null,
  rfq_revision int not null,
  document_id uuid not null,
  document_revision int not null,
  source_event_id uuid not null,
  primary key (tenant_id, rfq_id, rfq_revision, document_id)
);

create table bom_item (
  tenant_id uuid not null,
  bom_item_id uuid not null,
  rfq_id uuid not null,
  line_no text not null,
  head_revision int not null,
  primary key (tenant_id, bom_item_id),
  unique (tenant_id, rfq_id, line_no)
);

create table bom_item_revision (
  tenant_id uuid not null,
  bom_item_id uuid not null,
  revision int not null,
  rfq_revision int not null,
  parent_item_id uuid,
  level int not null check (level >= 0),
  path text not null,
  part_id uuid not null,
  part_desc text not null,
  material_class text not null,
  qty_per numeric(18,4) not null check (qty_per > 0),
  uom text not null,
  attributes jsonb not null,
  derivation text not null check (derivation in (
    'extracted', 'computed', 'judged', 'overridden', 'imported'
  )),
  evidence_id uuid not null,
  supersedes int,
  source_event_id uuid not null,
  primary key (tenant_id, bom_item_id, revision),
  check ((level = 0 and parent_item_id is null) or (level > 0 and parent_item_id is not null))
);

create table part (
  tenant_id uuid not null,
  part_id uuid not null,
  head_revision int not null,
  primary key (tenant_id, part_id)
);

create table part_revision (
  tenant_id uuid not null,
  part_id uuid not null,
  revision int not null,
  description text not null,
  material_class text not null,
  attributes jsonb not null,
  source_event_id uuid not null,
  primary key (tenant_id, part_id, revision)
);

create table alias (
  tenant_id uuid not null,
  alias_id uuid not null,
  entity_type text not null check (entity_type in ('part', 'customer', 'supplier', 'rfq')),
  entity_id uuid not null,
  scheme text not null,
  value text not null,
  customer_id uuid,
  primary key (tenant_id, alias_id),
  unique nulls not distinct (tenant_id, entity_type, scheme, value, customer_id)
);

create table supplier (
  tenant_id uuid not null,
  supplier_id uuid not null,
  name text not null,
  primary key (tenant_id, supplier_id)
);

create table part_supplier (
  tenant_id uuid not null,
  part_id uuid not null,
  supplier_id uuid not null,
  landscape text not null check (landscape in ('single', 'dual', 'multi', 'open')),
  source_event_id uuid not null,
  valid_to timestamptz,
  primary key (tenant_id, part_id, supplier_id, source_event_id)
);
```

`path` is a projection-maintained materialized path (`/line/line/line`) so ancestor and subtree filters are prefix lookups. It is rebuilt on state replay. No extension.

Bytes of the PDF and workbook stay in the file locator the document revision names. The graph stores the hash.

### 6.3 Execution, money, and authorization

```sql
create table task (
  tenant_id uuid not null,
  task_id uuid not null,
  rfq_id uuid not null,
  rfq_revision int not null,
  kind text not null check (kind in (
    'ingest', 'engineering', 'procurement', 'finance', 'commercial', 'assemble', 'gate'
  )),
  wave int,
  status text not null check (status in ('open', 'running', 'succeeded', 'failed', 'rerun')),
  primary key (tenant_id, task_id)
);

create table agent_run (
  tenant_id uuid not null,
  run_id uuid not null,
  task_id uuid not null,
  actor_id uuid not null,
  started_at timestamptz not null,
  completed_at timestamptz,
  llm_calls int,
  llm_tokens int,
  status text not null check (status in ('running', 'succeeded', 'failed')),
  source_event_id uuid not null,
  primary key (tenant_id, run_id)
);

create table artifact (
  tenant_id uuid not null,
  artifact_id uuid not null,
  content_hash text not null,
  media_type text not null,
  byte_size bigint not null check (byte_size >= 0),
  locator text not null,
  kind text not null check (kind in (
    'tool_request', 'tool_response', 'model_response', 'source_file'
  )),
  created_at timestamptz not null,
  primary key (tenant_id, artifact_id),
  unique (tenant_id, content_hash)
);

create table evidence (
  tenant_id uuid not null,
  evidence_id uuid not null,
  rfq_id uuid,
  kind text not null check (kind in (
    'document_span', 'tool_output', 'rule_firing',
    'model_output', 'human_note', 'imported_record'
  )),
  document_id uuid,
  document_revision int,
  span_locator jsonb,
  tool_name text,
  method_version text,
  input_artifact_id uuid,
  output_artifact_id uuid,
  input_hash text,
  output_hash text,
  rule_id text,
  recorded_by uuid not null,
  recorded_at timestamptz not null,
  source_event_id uuid not null,
  primary key (tenant_id, evidence_id),
  check (
    (kind = 'tool_output' and input_artifact_id is not null and output_artifact_id is not null)
    or (kind = 'model_output' and output_artifact_id is not null)
    or (kind not in ('tool_output', 'model_output'))
  )
);

create table decision (
  tenant_id uuid not null,
  decision_id uuid not null,
  rfq_id uuid not null,
  kind text not null check (kind in (
    'classification', 'risk_judgment', 'gate_choice', 'override', 'quote_authorization'
  )),
  subject_type text not null,
  subject_id uuid not null,
  subject_revision int,
  outcome text not null,
  rationale text,
  derivation text not null check (derivation in ('judged', 'overridden')),
  actor_id uuid not null,
  run_id uuid,
  replaces_decision_id uuid,
  decided_at timestamptz not null,
  source_event_id uuid not null,
  primary key (tenant_id, decision_id)
);

create table decision_evidence (
  tenant_id uuid not null,
  decision_id uuid not null,
  evidence_id uuid not null,
  primary key (tenant_id, decision_id, evidence_id)
);

create table cost_estimate (
  tenant_id uuid not null,
  estimate_id uuid not null,
  rfq_id uuid not null,
  bom_item_id uuid not null,
  bom_revision int not null,
  material numeric(18,4) not null check (material >= 0),
  processing numeric(18,4) not null check (processing >= 0),
  overhead numeric(18,4) not null check (overhead >= 0),
  supplier_margin numeric(18,4) not null check (supplier_margin >= 0),
  unit_price numeric(18,4) not null check (unit_price >= 0),
  currency char(3) not null,
  lead_time_weeks int,
  confidence text not null check (confidence in ('high', 'medium', 'low')),
  commodity_basis text not null,
  method text not null,
  method_version text not null,
  derivation text not null check (derivation = 'computed'),
  actor_id uuid not null,
  requested_by_run uuid,
  evidence_id uuid not null,
  supersedes uuid,
  source_event_id uuid not null,
  primary key (tenant_id, estimate_id)
);

create table quote (
  tenant_id uuid not null,
  quote_id uuid not null,
  rfq_id uuid not null,
  head_revision int not null,
  status text not null check (status in ('draft', 'in_review', 'approved', 'rejected', 'incomplete')),
  primary key (tenant_id, quote_id)
);

create table quote_revision (
  tenant_id uuid not null,
  quote_id uuid not null,
  revision int not null,
  rfq_revision int not null,
  currency char(3) not null,
  nre_total numeric(18,4) not null,
  piece_price numeric(18,4) not null,
  total_project_value numeric(18,4) not null,
  quote_validity_days int not null,
  incomplete_reason text,
  generated_at timestamptz not null,
  source_event_id uuid not null,
  primary key (tenant_id, quote_id, revision)
);

create table quote_line (
  tenant_id uuid not null,
  quote_id uuid not null,
  quote_revision int not null,
  bom_item_id uuid not null,
  bom_revision int not null,
  estimate_id uuid not null,
  qty_per numeric(18,4) not null,
  unit_price numeric(18,4) not null,
  extended_price numeric(18,4) not null,
  currency char(3) not null,
  primary key (tenant_id, quote_id, quote_revision, bom_item_id)
);

create table approval (
  tenant_id uuid not null,
  approval_id uuid not null,
  quote_id uuid not null,
  quote_revision int not null,
  decision_id uuid not null,
  outcome text not null check (outcome in ('granted', 'rejected')),
  actor_id uuid not null,
  decided_at timestamptz not null,
  source_event_id uuid not null,
  primary key (tenant_id, approval_id)
);

create table link (
  tenant_id uuid not null,
  link_id uuid not null,
  rel text not null check (rel in ('cites', 'produced', 'based_on', 'affects', 'invalidates')),
  from_type text not null,
  from_id uuid not null,
  to_type text not null,
  to_id uuid not null,
  valid_from_event uuid not null,
  valid_to timestamptz,
  primary key (tenant_id, link_id)
);

create table impact_item (
  tenant_id uuid not null,
  impact_id uuid not null,
  changeset_id uuid not null,
  rfq_id uuid not null,
  target_type text not null,
  target_id uuid not null,
  target_revision int,
  effect text not null check (effect in ('stale', 'rerun', 'reapprove', 'none')),
  reason_code text not null,
  via text not null check (via in ('ancestor', 'descendant', 'estimate', 'quote', 'approval', 'task')),
  primary key (tenant_id, impact_id)
);
```

`quote_line.extended_price` must equal `qty_per * unit_price` at numeric scale 4, the same validator the Pydantic model already states. The handler rejects the command otherwise.

Indexes the named queries need:

- `work_event (tenant_id, stream_id, seq)`
- `rfq_document (tenant_id, rfq_id, rfq_revision)`
- `bom_item_revision (tenant_id, part_id)`
- `bom_item_revision (tenant_id, path text_pattern_ops)`
- `cost_estimate (tenant_id, bom_item_id, bom_revision)`
- `quote_line (tenant_id, bom_item_id)`
- `quote (tenant_id, rfq_id, status)`
- `link (tenant_id, from_id) where valid_to is null`
- `impact_item (tenant_id, changeset_id)`
- `artifact (tenant_id, content_hash)`
- `evidence (tenant_id, output_artifact_id)`

RLS: `enable` and `force` on every table above except `tenant`. One policy, `tenant_id = current_setting('app.tenant_id')::uuid`, for both `using` and `with check`.

Partitioning of `work_event` waits until a stream index is no longer enough. It is a later migration, not part of the first increment.

## 7. API boundaries

Three surfaces. No open graph language. If a caller needs a traversal, it becomes a named query. Impact and BOM ancestry are closures over the whole chain, not capped walks.

### 7.1 Command API

Called by the runner and by the human-review gateway. Subject to RLS and idempotency.

Envelope:

```json
{
  "command_id": "0192…",
  "tenant_id": "0192…",
  "actor_id": "0192…",
  "idempotency_key": "ingest:rfq-package-hash",
  "type": "rfq.ingest",
  "payload": {}
}
```

Response:

```json
{
  "changeset_id": "0192…",
  "events": [{"event_id": "0192…", "event_type": "rfq.ingested", "seq": 1}],
  "head": {"type": "rfq", "id": "0192…", "revision": 1},
  "impact_count": 0
}
```

| Command | Who calls it | Writes |
|---|---|---|
| `rfq.ingest` | Runner, after a successful parse | Customer, RFQ revision, documents, BOM items, parts, aliases, evidence for each extract |
| `rfq.revise_bom` | Runner or a reviewed human edit | New BOM revisions, impact rows |
| `run.start` / `run.complete` | Runner at wave boundaries | Task, AgentRun, Evidence, Decisions. Completion is one command, not a write per token. |
| `estimate.record` | Runner, wrapping the cost tool | CostEstimate rows, system actor, tool evidence |
| `quote.assemble` | Runner, after gates are closed | Quote revision and lines |
| `review.decide` | Human gateway | Decision, optional override, impact rows with `rerun` |
| `quote.approve` | Human gateway | Approval of a named quote revision |

Reject cases the handler owns:

- `409` when the idempotency key exists with a different body hash
- `422` when a decision has no evidence, a price row is not `computed`, or `extended_price` does not match
- `409` when a command targets a revision that is not the head, except `quote.approve`, which may name an explicit revision and then only that revision

### 7.2 Query API

Read-only, RLS-scoped.

| Query | Returns |
|---|---|
| `GET /rfqs/{id}?revision=` | That RFQ revision, the document revisions pinned in `rfq_document`, and the BOM revisions for that same revision |
| `GET /rfqs/{id}/blackboard` | A Blackboard-shaped JSON document assembled for the runner. Read only. |
| `GET /quotes/{id}/provenance?revision=` | Each line → estimate → evidence → document span, plus the decision ids that touched the line |
| `GET /changesets/{id}/impact` | `impact_item` rows for that changeset |
| `GET /parts/{id}/where-used?status=open` | Open quote lines in this tenant that specify the part |
| `GET /rfqs/{id}/timeline` | Events on that stream |

`GET /rfqs/{id}/blackboard` is a compatibility adapter. Writes never accept a raw blackboard document. The graph is stricter than the in-memory model: it adds tenant, actor, evidence, and revision, and it splits part from BOM usage.

### 7.3 Replay API

Operator-only. Not mounted on the request path of a quote.

| Call | Behavior |
|---|---|
| `POST /internal/replay/project` | State replay. Rebuild one stream's projection from `work_event` and swap it in a transaction. |
| `POST /internal/replay/execute` | Execution replay of one task. Pins tool I/O and model output from evidence. Appends a new run. |

### 7.4 What does not get a client

The engineering, procurement, finance, and commercial agents do not receive a graph client. The orchestrator does not either. The runner translates wave inputs and outputs at the boundary it already owns (`run_rfq` in the current layout). That preserves the rule that agents meet only through the orchestrator and the blackboard.

## 8. Fit with the current agent

During one run the blackboard remains the mutable scratch pad described in `docs/00-architecture.md`. The graph is committed at boundaries:

1. After ingestion succeeds, `rfq.ingest` stores the package. A parse failure still returns `IngestionError` and writes nothing.
2. After each wave, `run.complete` stores traces, judgments, and evidence. If the process dies after `run.start` and before `run.complete`, recovery starts a new run on the same task. The half-open run stays `running` until an operator marks it failed. It is not folded into the quote.
3. After the cost tool returns, `estimate.record` stores the numbers.
4. When a gate opens, the review packet is a query over decisions and risks. The human response is `review.decide`.
5. When the assembler finishes, `quote.assemble` stores the draft. Rendered prose stays a document revision cited by the quote. The structured totals stay columns.

Gate evaluation stays in `GateEvaluator`. The graph records the firing as a `rule_firing` evidence row and the human choice as a decision. It does not reimplement the rule.

A single-tenant deployment still inserts one `tenant` row and sets `app.tenant_id`. There is no mode where `tenant_id` is null.

## 9. Ninety-day sequence

Anchored at 19 Nov 2026 (Asia/Shanghai).

### Increment 1 — record the package

Exit date: 18 Dec 2026.

Scope: tenant, actor, customer, RFQ, document, BOM item, part, alias, event log, changeset, RLS, `rfq.ingest`, state replay of that stream.

Exit criteria:

- The existing ingestion fixture can be deleted from the projection tables and rebuilt byte-for-byte in business columns from `work_event`.
- A session scoped to tenant B cannot read tenant A's RFQ, including through the event log.
- A BOM path query returns ancestors for a multi-level fixture.
- After a later document revision is ingested, `GET /rfqs/{id}?revision=` for the earlier revision still returns the document revisions pinned at that time.
- The current agent tests stay green. This increment adds an adapter and does not rewrite sub-agents.

### Increment 2 — attribute the judgment

Exit date: 17 Jan 2027.

Scope: task, agent run, evidence, decision, cost estimate, `review.decide`, impact rows for a BOM qty change.

Exit criteria:

- Every stored unit price has `derivation = computed`, a system actor, and tool-output evidence.
- Every human gate decision is a `decision` row with kind `human` actor and at least one evidence cite.
- A leaf quantity change whose ancestor chain is longer than five parents still writes `impact_item` rows for every ancestor estimate, the rolled-up quote line, and any open approval. A committed changeset has `impact_status = complete`.
- Two ingests that claim the same `internal_pn` with a null `customer_id` conflict on the alias constraint.
- Provenance query for one quote line resolves to a document span or to a tool artifact whose bytes match the stored hash.

### Increment 3 — close the quote

Exit date: 16 Feb 2027.

Scope: quote revision, quote line, approval, where-used, one execution-replay spike on a single fixture.

Exit criteria:

- An approval names one quote revision. A later `quote.assemble` produces a new revision that is not approved.
- Where-used for a part returns only open quotes in the caller's tenant.
- Execution replay of one procurement task loads the stored tool request and response artifacts, appends a new run, and leaves the original estimate in place. Removing the artifact locator makes the same call fail before any tool is invoked.
- Named-query latency on the fixture set is recorded. The section 10 triggers are written down as met or not met.

Out of this horizon: a graph engine, cross-tenant catalogs, ERP or PLM connections, an ECO workflow beyond the impact rows above, and a general-purpose query language.

## 10. When a graph database would be justified

Reopen the choice only if a named query, after indexes, meets one of these on a realistic tenant volume:

- p95 above 200 ms for provenance, where-used, or impact-by-changeset, and the plan is already an index lookup rather than a sequential scan
- a product requirement for interactive traversal that is not one of the named closures (ancestor path, citation, where-used)
- a second domain (quality deviations, field failures, cross-program ECOs) whose primary interaction is multi-hop where-used across those domains

The migration path is a projector that folds `work_event` into the engine as a read model. Commands stay on Postgres. The engine does not become the place prices are stored.

Until one of those is observed, adding the engine increases operational surface and does not answer a query the schema in section 6 cannot name.

## 11. Assumptions

These are choices, recorded so implementation does not reopen them silently.

1. One tenant is one quoting organization. Parts are not shared across tenants. Customers inside a tenant do not automatically share a part; aliases are customer-scoped when the scheme is `customer_pn`.
2. Who is allowed to approve a margin-floor breach stays a rule in the gate engine. The graph stores the actor and the approval. It does not store an authority matrix in this horizon.
3. Document bytes, tool bodies, and model responses live behind locators on `document_revision` and `artifact`. The graph stores the content hash and the locator. The choice of disk versus object storage is separate. Retention follows the citing evidence or document row, as specified in section 5.2.
4. Revision history is linear. Alternative BOM proposals are separate RFQ revisions, not branches.
5. The blackboard JSON remains the in-process contract among agents. The compatibility read exists so the runner can rehydrate. It is not a write model.
