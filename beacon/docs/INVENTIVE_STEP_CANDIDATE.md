# BEACON Evidence-Adjusted Certification: Candidate Technical Contribution

> **Status:** Engineering disclosure for project discussion, not a patentability
> opinion or a claim that the contribution is novel. Obtain a qualified patent
> professional's review before relying on this document for a filing.

## Technical problem

Behavioral equivalence scores can look strong even when the run has weak or
incomplete evidence. A score based only on observed output agreement does not,
by itself, communicate whether the inputs exercised the relevant oracles, the
executions completed reliably, or the compared sources and input set were
integrity-checked.

## Candidate contribution

BEACON keeps the raw behavioral-equivalence score separate from a deterministic
evidence-quality adjustment. For each completed run, it derives quality factors
from available execution and provenance evidence, including oracle coverage,
input coverage, execution reliability, oracle confidence, input-set integrity,
and source-hash integrity. The configured factor weights are renormalized over
the factors that are actually available:

```text
quality = sum(weight[i] * factor[i]) / sum(weight[i])
adjusted_score = raw_behavioral_score * quality
```

The resulting artifact retains the raw score, quality score, adjusted score,
and factors rather than replacing the raw behavioral result. Certification
policy gates, including coverage and execution checks, remain authoritative;
the adjustment is not a substitute for those gates. Missing evidence is not
implicitly assigned a perfect factor.

The broader workflow binds the result to a run, source identities, and the
canonical input-set identity. An AI-generated explanation may summarize the
completed evidence, but it cannot supply missing execution outputs or change
the deterministic verdict.

## Implementation evidence

- The factor weights and availability-aware calculation are implemented in
  [`scorer.py`](../backend/certification/scorer.py).
- The certification engine derives factors and applies the adjusted score in
  both certification paths in
  [`certification_engine.py`](../backend/certification/certification_engine.py).
- Factor values are included in certificate metrics and report output.
- Unit tests cover weight renormalization, score calculation, omitted factors,
  and invalid numeric values in
  [`test_evidence_scoring.py`](../backend/tests/test_evidence_scoring.py).

For example, a raw score of `0.80` and evidence quality of `0.90` produce an
adjusted score of `0.72`. This is a project heuristic, not a probability,
statistical confidence interval, or proof of universal equivalence.

## Verification status and limitations

The formula and its invalid-input handling are covered by automated tests. The
compatibility harness now captures simple BMS output-map fields and accepts
matching map-input fields. In a live check, the compiled legacy `COACTUPC`
program emitted screen fields, while the modern implementation returned its
own structured result. A lookup case still showed a legacy validation message
where the modern side reported a successful lookup, and the stateful,
multi-interaction CICS flow has not been demonstrated. A successful paired
certificate for this representative source pair has **not** been demonstrated.
Compatibility emulation is not genuine CICS execution.

## Novelty and patentability questions

This document describes a candidate contribution, not an established inventive
step. Evidence coverage, reliability scoring, confidence weighting,
content-addressed provenance, and thresholded certification are each areas
that may have prior art. A proper assessment must compare the particular
combination and decision flow above against relevant publications and patent
claims, and determine whether the differences would have been obvious to a
person skilled in the field. No conclusion on novelty, inventive step, or
patentability is made here.

### Bounded prior-art scan

The following sources were reviewed as relevant published teachings. This is
not an exhaustive search and does not establish that no closer prior art exists.

- **Diffy**, Twitter's differential-testing product, compares candidate-to-
  primary differences against primary-to-secondary differences to estimate
  nondeterministic noise. It is relevant to evidence-responsive comparison,
  but its README does not describe coverage-calibrated equivalence confidence.
  [Project README](https://github.com/twitter-archive/diffy#what-is-diffy)
- **"On Adaptive Sampling-Based Testing for Software Reliability Assessment"**
  (IEEE ISSRE 2016, DOI
  [10.1109/ISSRE.2016.50](https://doi.org/10.1109/ISSRE.2016.50)) studies
  adaptive sampling and confidence intervals for reliability assessment, not
  cross-version equivalence certification.
- **"Assessing Test Adequacy for Black-Box Systems without Specifications"**
  (ICTSS 2011, DOI
  [10.1007/978-3-642-24580-0_15](https://doi.org/10.1007/978-3-642-24580-0_15))
  uses statistical inference to reason about test evidence and adequacy, not a
  paired-version certification gate.
- **"Looking for More Confidence in Refactoring? How to Assess Adequacy of Your
  Refactoring Tests"** (QSIC 2008, DOI
  [10.1109/QSIC.2008.49](https://doi.org/10.1109/QSIC.2008.49)) relates coverage
  of refactoring scope and impact to confidence in regression tests.
- **"Coverage-guided differential testing of TLS implementations based on
  syntax mutation"** (*PLOS ONE* 17(1), 2022, DOI
  [10.1371/journal.pone.0262176](https://doi.org/10.1371/journal.pone.0262176))
  combines coverage-guided differential-test generation with behavioral
  comparison; the paper's use of coverage guides test generation rather than
  acceptance confidence.
- **"Shadow test replay service" (US9672137B1)** replays requests to candidate
  and authority versions, compares responses, and tracks difference metrics
  and trends. [Patent publication](https://patents.google.com/patent/US9672137B1/en)
- **"Shadow testing services" (US8001422B1)** describes testing candidate
  functionality against production requests and comparing responses.
  [Patent publication](https://patents.google.com/patent/US8001422B1/en)
- **"ChatUniTest: A Framework for LLM-Based Test Generation"** (arXiv:2305.04764)
  describes LLM test generation with compilation/runtime validation and repair;
  it is adjacent to test discovery, not evidence-adaptive equivalence scoring.
  [Paper](https://arxiv.org/abs/2305.04764)

In this bounded scan, the sources separately cover shadow/paired execution,
noise baselines, adaptive reliability sampling, coverage-aware test adequacy,
coverage-guided differential-test generation, and execution-validated LLM test
discovery. A possible area for further investigation is the **particular
combination** of measured test adequacy/coverage, evidence quality, and
uncertainty in a legacy-to-modernized equivalence certification score or
acceptance rule. This scan did not establish whether that combination is novel,
non-obvious, or patentable; the patent search was incomplete and legal review
is required.

The demonstrated technical effect should be evaluated with controlled test
runs: hold the observed behavioral result constant, vary one evidence factor
at a time, verify the reported raw and adjusted scores, and confirm that
insufficient execution evidence still blocks a successful certification.
