# BEACON — Behavioral Equivalence Certification Framework

Database Management Systems Project — Team: Sai, Yatin, Navaneeth

BEACON is a verification layer that certifies whether AI-modernized code preserves the
behavior of the legacy system it replaces. It does not translate code — it mines implicit
business-rule invariants from a legacy system, compiles them into language-agnostic
executable oracles, certifies modernized code against those oracles with a quantified
score, and keeps monitoring production traffic for behavioral drift after deployment.

## Repo Layout

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
│   ├── oracle/            Stage 3 — oracle DSL + synthesis + interpreter
│   ├── certification/     Stage 4 — equivalence scoring engine
│   ├── drift/             Stage 5 — production drift monitor
│   └── api/               FastAPI app wiring all stages together
├── frontend/              React + Recharts dashboard
├── docs/                  Baseline documentation & architectural reports
├── scripts/               End-to-end demo runner
└── tests/                 Comprehensive pytest test suite (87 tests)
```

## LLM Provider Hierarchy & Configuration

BEACON decouples LLM candidate hypothesis generation from the verification engine through a multi-provider abstraction:

1. **OpenRouter (Primary Cloud Provider)**: High-speed cloud reasoning via models such as `anthropic/claude-3.5-sonnet`.
2. **Anthropic (Supported Cloud Provider)**: Direct Anthropic API access via `claude-sonnet-4-6`.
3. **Ollama (Local Fallback Provider)**: Local offline execution using models like `qwen2.5-coder:7b` or `mistral:7b`.
4. **Offline Rule Synthesizer (Deterministic Fallback)**: Zero-dependency rule synthesizer for continuous testing without external APIs.

### Automatic Fallback (`LLM_PROVIDER=auto`)
In `auto` mode (the default), BEACON automatically navigates the fallback chain:
$$\text{OpenRouter} \longrightarrow \text{Anthropic} \longrightarrow \text{Ollama} \longrightarrow \text{Offline}$$

If a provider is unconfigured, times out, or encounters rate limits, BEACON gracefully falls back to the next tier while attaching full provenance (`provider`, `model`, `fallback_chain`) to every candidate invariant.

### Strict Verification Independence
The LLM is strictly a candidate hypothesis generator in Phase 6. All proposed invariants must independently pass:
1. **Semantic Grounding**: Variable, operator, and threshold verification against the `UnifiedEvidencePackage`.
2. **Adversarial Validation**: Property-based boundary probing, combinatorial truth tables, and counterexample minimization.
3. **Confidence Gate**: Strict 0.8 threshold gating in `confidence_scorer.py`.

Once compiled into executable oracles (Phase 8), **modernization certification (Phases 9–10) executes deterministically without calling any LLM**.

## Local Prototype Setup (Recommended)

From the repository root in Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# Terminal 1: API
cd backend
..\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000

# Terminal 2: Dashboard
cd frontend
npm.cmd install
npm.cmd run dev
```

Run test suite and deterministic demo pipeline:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_demo_pipeline.py
```
