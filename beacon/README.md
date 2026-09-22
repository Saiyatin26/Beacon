# BEACON — Behavioral Equivalence Certification Framework

Database Management Systems Project — Team: Sai, Yatin, Navaneeth

BEACON is a domain-agnostic verification layer that certifies whether modernized code preserves the
behavior of the legacy system it replaces. It mines invariants, compiles them into language-agnostic
executable oracles, certifies modernized code with a quantified equivalence score under a deterministic policy,
and generates audit-grade grounded explanations.

---

## BEACON V2 Authoritative Roadmap

- **Phase 1** — V2 Foundation
- **Phase 2** — Adapter Framework
- **Phase 3** — Real Execution + Evidence
- **Phase 4** — Behavioral Evaluation
- **Phase 5** — Controlled Business Rules
- **Phase 6** — Rule Discovery
- **Phase 7** — Rule Reconciliation + OracleSet
- **Phase 8** — Dynamic / Evidence-Driven Thresholds
- **Phase 9** — Company Knowledge RAG
- **Phase 10** — Intelligent Agent + Detailed Certification Explanations
- **Phase 11** — Integration Hardening
- **Phase 12** — End-to-End Certification
- **Phase 13** — Evidence/Audit/Cryptographic Hardening
- **Phase 14** — Testing/Security/Performance
- **Phase 15** — Final Validation/UI/Documentation/Demo

---

## Full End-to-End Lifecycle

```
Legacy Source
     │
     ▼
Static / Dynamic Evidence (AST + Traces)
     │
     ▼
Unified Evidence Package (Correlated Facts)
     │
     ▼
LLM-Assisted Invariant Mining (OpenRouter -> Anthropic -> Ollama -> Offline)
     │
     ▼
Semantic Grounding & Anti-Hallucination Gate
     │
     ▼
Adversarial Validation & Property-Based Probing (Boundaries, Jitters, Combinatorial)
     │
     ▼
Confidence Scorer (0.80 Certification Gate)
     │
     ▼
Language-Independent Oracle Compiler (Pure AST, Canonical Serializer, SHA-256 Hasher)
     │
     ▼
Frozen Oracle Set (Immutable, Content-Addressed)
     │
     ▼
Same Shared Test Inputs Applied to Legacy and Modernized Adapters
     │
     │
     ▼
Deterministic Oracle Evaluation & 4-Way Classification
(MATCH, MODERN_REGRESSION, REFERENCE_INCONSISTENT, MUTUAL_VIOLATION)
     │
     ▼
Phase 11 Evidence Persistence & Reproducibility Verification
(Immutable InputSets, Execution Cases, Canonical SHA-256 Hash Reconstruction, Atomic SQLite Persistence)
     │
     ▼
Quantified Certification Policy Engine
(CERTIFIED, CERTIFIED_WITH_WARNINGS, NOT_CERTIFIED, REFERENCE_INCONSISTENT, INSUFFICIENT_COVERAGE)
     │
     ▼
Immutable Cryptographic Certification Artifact (JSON + SHA-256 Hash + HTML/Markdown Report)
     │
     ▼
Interactive UI Dashboard with Per-Oracle Failure & Case-Level Audit Drill-Down & Dataset Export
     │
     ▼
Post-Migration Drift Monitoring (Runtime Observations -> evaluate_oracle)
```

---

## The Core Separation Principle: Zero LLM in Certification

BEACON preserves a strict separation of concerns:
- **Discovery (Phase 6)**: LLMs (OpenRouter primary, Anthropic supported, Ollama local, or Offline fallback) act strictly as un-trusted candidate hypothesis generators.
- **Validation (Phase 7)**: Independent property-based adversarial testing attempts to disprove candidate invariants against legacy execution.
- **Compilation (Phase 8)**: Validated invariants are compiled into language-independent canonical AST oracles with SHA-256 content hashes.
- **Certification (Phases 9–10)**: **Strictly deterministic and LLM-independent.** Certification authority is derived solely from the frozen validated oracle set, target implementation execution results, coverage metrics, and configured certification policy.

---

## Formal Certification Outcomes & Policy Semantics

- **`MATCH`**: Both legacy and modern implementations satisfy the oracle on the applicable input.
- **`MODERN_REGRESSION`**: Reference satisfies the oracle, but the modernized implementation violates it. Captures exact counterexamples and blocks certification (`NOT_CERTIFIED`).
- **`REFERENCE_INCONSISTENT`**: Reference implementation contradicts a validated oracle. Directly reduces equivalence score and strictly blocks certification (`REFERENCE_INCONSISTENT`).
- **`MUTUAL_VIOLATION`**: Both reference and modern implementations contradict the same oracle for an applicable input. Reduces equivalence score and blocks certification (`NOT_CERTIFIED`).
- **`INSUFFICIENT_COVERAGE`**: The tested input domain or exercised oracle count is insufficient to support the configured certification policy (`INSUFFICIENT_COVERAGE`).
- **`CERTIFIED_WITH_WARNINGS`**: Permitted only when policy explicitly allows non-critical warnings and zero critical blocking failures exist.
- **`CERTIFIED`**: High equivalence score ($\ge 80\%$), 100% oracle coverage, 0 regressions, 0 reference inconsistencies, 0 mutual violations, and 0 execution errors.

> **Methodological Limitation Notice**: BEACON does not mathematically prove universal program equivalence; it certifies oracle-relative behavioral equivalence over the validated oracle set and tested input domain under a versioned certification policy.

## Phase 12 — Scientific Reproducibility & Benchmark Hardening

BEACON provides a cryptographically auditable, configuration-sensitive certification framework across multi-domain benchmarks.

### 1. The Scientific Reproducibility Contract
Every certification execution generates an immutable, content-addressed `CertificationArtifact` tied to an authoritative `CertificationContext` containing:
- **`benchmark_id`**, **`benchmark_version`**, **`benchmark_name`**, **`benchmark_provenance`** (e.g. `REALISTIC_SYNTHETIC`, `PUBLIC`, `CONTROLLED`).
- **`dataset_id`**, **`dataset_version`**, **`dataset_checksum`** (SHA-256 over raw dataset content).
- **`evaluation_mode`** (`CONTROLLED` vs `FULL_BEACON`).
- **`modernization_variant_id`**, **`modernization_variant_name`**, **`modernization_provenance`** (`INDEPENDENT_REIMPLEMENTATION`, `CONTROLLED_MUTATION`).
- **`legacy_implementation_id`**, **`legacy_implementation_hash`** (deterministic SHA-256 AST/directory digest).
- **`modernized_implementation_id`**, **`modernized_implementation_hash`**.
- **`oracle_set_id`**, **`oracle_set_hash`**, **`oracle_source_type`** (`CONTROLLED_ORACLE_SET`, `FULL_BEACON_DISCOVERED`, `FULL_BEACON_OFFLINE_FALLBACK`).
- **`provider`** (actual model provider used, e.g. `openrouter`, `anthropic`, `ollama`, `offline`), **`model`**, **`generation_method`**, **`provider_metadata`** (containing `requested_provider`, `actual_provider`, `actual_model`, `fallback_occurred`, `fallback_chain`, `fallback_reason`).
- **`policy_id`**, **`policy_hash`**.

### 2. Disambiguated Evaluation Metrics
To eliminate all ambiguity, metrics are exposed and asserted independently:
- **`unique_input_count`**: Number of distinct test inputs in the active dataset.
- **`certification_case_count`**: Total execution cases evaluated ($N_{inputs} \times N_{oracles}$).
- **`oracle_count`**: Number of active oracles in the certified `OracleSet`.
- **`oracle_evaluation_count`**: Number of times oracles were triggered and evaluated.
- **`matching_case_count`**: Number of cases where both implementations agreed.
- **`regression_case_count`**: Number of cases where modernized code violated a validated invariant.
- **`execution_error_count`**: Unhandled runtime exceptions in adapters during evaluation.
- **`counterexample_count`**: Concrete minimal inputs disproving invariants or modernized equivalence.

### 3. Provider Hierarchy & Truthful Provenance
The discovery pipeline supports a 4-tier provider hierarchy:
1. **OpenRouter** (Primary Cloud LLM via configurable models).
2. **Anthropic** (Secondary Direct Cloud Fallback).
3. **Ollama** (Local Model Fallback, e.g. Mistral / Qwen).
4. **Deterministic Offline Fallback** (Static AST + Dynamic Trace candidate generator when models are unavailable).

The actual provider that produced the accepted response is truthfully preserved in `OracleProvenance.reproducibility["actual_provider"]` and `CertificationContext.provider`. Zero secrets, authorization headers, or private keys are ever stored or exposed.

### 4. Canonical Discovery Configuration Hashing
In `FULL_BEACON` mode, OracleSets are cached and content-addressed by a 18-parameter canonical JSON SHA-256 digest: `SET-{BENCHMARK}-FULL-{config_hash[:12]}`. Mutating any element (model, provider, prompt version, candidate generator version, evidence hash, validator version, or dataset checksum) invalidates the cache and forces fresh execution.

### 6. Phase 13 — Production-Grade 9-Step Certification Workflow
Phase 13 establishes a production-grade, step-by-step guided certification interface:
- **Step 1:** Target Benchmark Selection (Retail, Payroll, Medical, Loan Demo).
- **Step 2:** Real-Time Dataset Specifications & Provenance Inspection.
- **Step 3:** Evaluation Mode Selection (`CONTROLLED` vs `FULL_BEACON`).
- **Step 4:** Multi-Tier Provider Hierarchy Configuration (`OpenRouter → Anthropic → Ollama → Offline`).
- **Step 5:** Target Modernization Variant Selection (`Clean` vs `Buggy`).
- **Step 6:** Pre-Flight Validation with Dataset Record & Adapter Verification.
- **Step 7:** Execution with Atomic State Clearing & Duplicate Protection.
- **Step 8:** Authoritative Status Outcome (`CERTIFIED`, `NOT_CERTIFIED`, `INSUFFICIENT_COVERAGE`) with Plain-Language Summaries.
- **Step 9:** Interactive Evidence Drill-Down, Expandable Per-Oracle Verification, Case Explorer, Cryptographic Audit Verification, and JSON/Markdown/CSV Dossier Exports.

---

## Repository Layout

```
beacon/
├── benchmarks/            Phase 12 — External & Public Benchmark Suites
├── backend/
│   ├── common/            Shared config, SQLite/Atlas client, Pydantic models
│   ├── ingestion/         Static AST parsing + dynamic runtime tracer
│   ├── evidence/          UnifiedEvidencePackage builder & correlated facts
│   ├── llm/               Decoupled Multi-Provider LLM Abstraction Layer
│   │   ├── base.py                LLMProvider ABC & standardized LLMResponse
│   │   ├── openrouter_provider.py OpenRouter Cloud Provider (Primary)
│   │   ├── anthropic_provider.py  Anthropic Cloud Provider (Supported)
│   │   ├── ollama_provider.py     Local Ollama Provider (Qwen/Mistral)
│   │   ├── offline_provider.py    Deterministic Rule Synthesizer (Fallback)
│   │   └── manager.py             ProviderManager with auto-fallback & status
│   ├── mining/            Adversarial invariant mining & validation sub-pipeline
│   │   ├── base_generator.py      CandidateGenerator interface
│   │   ├── offline_miner.py       Deterministic local invariant miner
│   │   ├── candidate_generator.py Multi-provider decoupled candidate miner
│   │   ├── evidence_selector.py   Relevance scoring & top-K selection
│   │   ├── prompt_builder.py      Structured LLM prompt with guardrails
│   │   ├── normalizer.py          Commutative AST boolean canonicalization
│   │   ├── grounding_checker.py   Semantic evidence grounding & anti-hallucination
│   │   ├── adversarial.py         Multi-strategy boundary/diverse validation & shrinking
│   │   ├── validator.py           Invariant validation routing
│   │   ├── confidence_scorer.py   Weighted confidence formula & 0.8 gate
│   │   └── pipeline.py            Canonical mining & validation orchestrator
│   ├── oracle/            Phase 8 — Language-Independent Oracle DSL Subsystem
│   │   ├── models.py              Canonical AST models, Schemas, OracleSet
│   │   ├── serializer.py          Canonical JSON serializer & SHA-256 hasher
│   │   ├── compiler.py            Validation-gated oracle compiler
│   │   ├── evaluator.py           Pure AST evaluator & 5-way status reporter
│   │   └── registry.py            Versioned immutable oracle & oracle set registry
│   ├── certification/     Phase 9, 10 & 11 — Equivalence, Certification & Evidence Reproducibility
│   │   ├── models.py              Observation, Policy, Artifact, CertificationInputSet, CertificationCase
│   │   ├── adapters.py            Generic ImplementationAdapter, LegacyAdapter, ModernizedAdapter
│   │   ├── adapter_registry.py    Registry resolving application adapters generically
│   │   ├── input_generator.py     Shared test suite generator & deterministic replay
│   │   ├── engine.py              Cross-version 4-way comparison engine
│   │   ├── certification_engine.py Policy-driven certification & atomic evidence synthesis
│   │   ├── repository.py          Thread-safe immutable certificate, input-set & case storage with 8-point integrity verification
│   │   ├── report_generator.py    Human-readable HTML & Markdown audit reports
│   │   └── runner.py              Backward-compatible certification runner
│   ├── benchmarks/        Phase 12 — Benchmark Registry, Schema Validator & Dataset Loader
│   │   ├── models.py              BenchmarkSpec, DatasetSpec, ProvenanceCategory, Manifest
│   │   ├── dataset_loader.py      Deterministic loader with SHA-256 validation
│   │   └── registry.py            Benchmark registry & adapter lifecycle wiring
│   ├── drift/             Phase 10 — Post-Migration Drift Foundation
│   │   ├── models.py              DriftObservation, DriftEvent, DriftPolicy
│   │   └── evaluator.py           Runtime observation evaluation against frozen OracleSet
│   ├── cli.py             BEACON Command Line Interface
│   └── api/               FastAPI REST API with modern lifespan, health/readiness probes & audit exports
├── frontend/              React + Vite + Recharts dashboard with 9-Step Production Workflow & Audit Trail
├── docs/                  Baseline documentation & architectural verification
├── DEPLOYMENT.md          Comprehensive production deployment & topology guide
├── RELEASE_CHECKLIST.md   Production release candidate verification checklist
├── BACKUP_AND_RECOVERY.md SQLite backup, WAL snapshots & disaster recovery guide
├── scripts/               End-to-end demo runner
└── tests/                 Comprehensive pytest test suite (480 passed tests)
```

---

## Phase 2 Application Input Resolution Contract

BEACON enforces a strict, fail-closed input resolution hierarchy for real-world applications:

1. **Explicit Dataset (Primary)**:
   - Configured via `dataset_path`, registered `dataset_id`, or inline records.
   - If configured dataset is missing, corrupted, or invalid, BEACON fails closed immediately (`ApplicationResolutionError`). It will never silently invent inputs.

2. **Explicit Input Contract Fields**:
   - Generated deterministically based on defined field schemas and constraints in `InputContract`.
   - If contract generation fails, BEACON fails closed immediately.

3. **Synthetic Input Fallback (Strictly TEST/DEVELOPMENT ONLY)**:
   - Real application inputs are required by default. BEACON does not automatically understand or guess arbitrary application inputs in production.
   - If neither a dataset nor input contract fields exist, execution **fails closed** with a validation/configuration error unless synthetic fallback is explicitly enabled (`allow_synthetic_inputs=True` or `BEACON_ALLOW_SYNTHETIC_INPUTS=true`).
   - When explicitly enabled for test/dev, synthetic inputs are tagged with explicit provenance (`source="phase2_test_development_fallback"`, `mode="test_development_fallback_only"`, `synthetic=True`, `explicitly_enabled=True`).

---

## Running Locally

### 1. Python Environment Setup
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Backend & Dashboard
```powershell
# Terminal 1: Backend API (Development Mode)
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --reload --port 8000

# Terminal 2: Frontend Dashboard
cd frontend
npm.cmd install
npm.cmd run dev
```

### 3. CLI Command
```powershell
.\.venv\Scripts\python.exe -m backend.cli certify --implementation buggy --format text
```

### 4. Run Test Suite & Production Build
```powershell
# Run full automated test suite
python -m pytest -q tests

# Run frontend production build
cd frontend && npm run build
```
