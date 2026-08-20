# BEACON — Behavioral Equivalence Certification Framework

Database Management Systems Project — Team: Sai, Yatin, Navaneeth

BEACON is a verification layer that certifies whether AI-modernized code preserves the
behavior of the legacy system it replaces. It does not translate code — it mines implicit
business-rule invariants from a legacy system, compiles them into language-agnostic
executable oracles, certifies modernized code against those oracles with a quantified
score under a deterministic certification policy, and monitors post-migration observations
for continuous behavioral drift.

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

---

## Repository Layout

```
beacon/
├── legacy_sample/         Sample legacy app + synthetic trace generator
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
│   │   ├── models.py              Observation, Policy, Artifact, CertificationInputSet, CertificationCase, ImmutabilityError
│   │   ├── adapters.py            Generic ImplementationAdapter, LegacyAdapter, ModernizedAdapter
│   │   ├── adapter_registry.py    Registry resolving application adapters generically without hardcoding
│   │   ├── input_generator.py     Shared test suite generator & deterministic replay
│   │   ├── engine.py              Cross-version 4-way comparison engine
│   │   ├── certification_engine.py Policy-driven certification & atomic evidence synthesis
│   │   ├── repository.py          Thread-safe immutable certificate, input-set & case storage with integrity verification
│   │   ├── report_generator.py    Human-readable HTML & Markdown audit reports
│   │   └── runner.py              Backward-compatible certification runner
│   ├── drift/             Phase 10 — Post-Migration Drift Foundation
│   │   ├── models.py              DriftObservation, DriftEvent, DriftPolicy
│   │   └── evaluator.py           Runtime observation evaluation against frozen OracleSet
│   ├── cli.py             BEACON Command Line Interface
│   └── api/               FastAPI REST API wiring all stages together with case-level audit endpoints
├── frontend/              React + Vite + Recharts interactive dashboard with case drill-down & dataset export
├── docs/                  Baseline documentation & architectural verification
├── scripts/               End-to-end demo runner
└── tests/                 Comprehensive pytest test suite (136 passed tests)
```

---

## Running Locally

### 1. Python Environment Setup
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### 2. Backend & Dashboard
```powershell
# Terminal 1: Backend API
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

### 4. Run Test Suite & Demo Pipeline
```powershell
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe scripts/run_demo_pipeline.py
```
