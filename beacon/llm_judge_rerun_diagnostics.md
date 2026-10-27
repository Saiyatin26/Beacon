# BEACON — LLM-as-Judge Evaluation Diagnostics & Verification Report

## 1. Root Cause of Previous Failures

- **Initial OpenRouter Free-Tier Exhaustion:** The prior evaluation relied on OpenRouter's free-tier model (`nvidia/nemotron-3.5-lightning:free`). While cases 1–20 (defective) and case 21 (control 1) executed, cases 22–30 (controls 2–10) failed with `HTTP Error 429: Rate limit exceeded: free-models-per-day` (50 request daily limit).
- **Masked Metric Accounting Artifact:** In the previous script, failed requests (`decision: ERROR`) were excluded from `false_alarm` calculations (`ground_truth == 'CORRECT' and decision == 'REJECTED'`), resulting in `False alarms: 0` despite 9 of 10 controls failing execution.
- **Latency Overhead:** The previous run took 616.18s because each call to Nemotron spent ~1,500–2,200 tokens on thinking/reasoning before emitting output.

## 2. Code & Configuration Changes Made

- **Secure Provider Migration:** Migrated the LLM-as-judge evaluation path to BEACON's native `GeminiProvider` using the newly configured API key in `.env` (`GEMINI_API_KEY`).
- **Bounded Exponential Backoff with Jitter:** Enhanced `LlmAsJudgeEvaluator` with bounded exponential backoff (base 1.0s, max 12.0s, 4 retries) with jitter.
- **Strict Metrics & Confusion Matrix:** Implemented formal binary classification metrics (TP, FN, TN, FP, Precision, Recall, Specificity, F1) that explicitly treat `ERROR` and `INCONCLUSIVE` as unresolved outcomes without counting them as successes.
- **Preserved Scope:** Differential (random), BEACON R-only, and BEACON Full implementations, test suites, and results were preserved completely intact.

## 3. Dataset Composition & Ground Truth

- **Total Cases Evaluated:** 30
- **Verified Effective Defects ($K$):** 20 (across 8 enterprise modernization categories)
- **Unmodified Controls:** 10
- **Prompt Template:** Formal behavioral equivalence specification against AWS CardDemo `COACTUPC` (SHA-256: `5375139bf1c363979b25e54e40102aeffb741531090fa38ce4a809e7167902a1`).

## 4. Empirical Rerun Results

- **Provider:** gemini
- **Model:** gemini-flash-lite-latest
- **Completion Status:** COMPLETE
- **Coverage:** 100.0% (30/30)
- **Detected / $K$:** 20/20 (100.0%)
- **False Certifications:** 0 (0.0%)
- **False Alarms:** 0 (0.0%)
- **Precision:** 1.0000
- **Recall:** 1.0000
- **Specificity:** 1.0000
- **F1 Score:** 1.0000
- **Measured End-to-End Runtime:** 169.35 s
- **Latency Statistics:** Mean: 1.44s, Median: 1.25s, p95: 2.15s
- **API Failures / Unresolved Requests:** 0
- **Total API Attempts:** 30 (Retries: 0)

## 5. Conclusion

All 30 cases were successfully adjudicated with zero API failures. The LLM-as-judge metric is fully validated and ready for Table XVII publication.
