"""Statistical metrics and significance tests for BEACON Research Evaluation.

Provides:
- 95% Wilson Score Confidence Interval for binomial proportions.
- Exact McNemar Paired Test (two-tailed binomial on discordant pairs).
- Spearman rank correlation rho and p-value.
- Formal confusion matrix outcome classification (TP, FP, TN, FN, FC, IC, RI).
- Standardized metric dictionaries with explicit numerator/denominator strings.
"""

from __future__ import annotations
import math
from typing import Any
import scipy.stats as stats


def wilson_ci(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Calculates the 95% Wilson score confidence interval for proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    z = stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0)
    p = k / n
    denominator = 1.0 + z * z / n
    centre_adjusted_probability = p + z * z / (2.0 * n)
    adjusted_limits = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)
    lower = max(0.0, (centre_adjusted_probability - adjusted_limits) / denominator)
    upper = min(1.0, (centre_adjusted_probability + adjusted_limits) / denominator)
    return (round(lower, 4), round(upper, 4))


def exact_mcnemar_test(b: int, c: int) -> float:
    """Exact two-tailed McNemar test for paired binary outcomes.

    b: Method 1 positive, Method 2 negative (discordant cell 0,1)
    c: Method 1 negative, Method 2 positive (discordant cell 1,0)
    """
    n = b + c
    if n == 0:
        return 1.0
    # Two-tailed binomial test with p=0.5
    res = stats.binomtest(b, n, 0.5, alternative="two-sided")
    return round(float(res.pvalue), 6)


def spearman_correlation(x: list[float], y: list[float]) -> tuple[float, float]:
    """Computes Spearman rank correlation rho and p-value."""
    if len(x) < 3 or len(y) < 3:
        return (0.0, 1.0)
    if len(set(x)) <= 1 or len(set(y)) <= 1:
        return (0.0, 1.0)
    res = stats.spearmanr(x, y)
    rho = float(res.statistic) if not math.isnan(res.statistic) else 0.0
    pval = float(res.pvalue) if not math.isnan(res.pvalue) else 1.0
    return (round(rho, 4), round(pval, 6))


def classify_outcome(ground_truth: str, verdict: str) -> str:
    """Classifies an individual case outcome according to the research protocol.

    ground_truth: 'DEFECTIVE' or 'EQUIVALENT'
    verdict: 'CERTIFIED', 'CERTIFIED_WITH_WARNINGS', 'NOT_CERTIFIED', 'INSUFFICIENT_COVERAGE', 'REFERENCE_INCONSISTENT'

    Returns one of:
    - TP: defective & NOT_CERTIFIED (demonstrated mismatch)
    - FC: defective & (CERTIFIED | CERTIFIED_WITH_WARNINGS) (false certification!)
    - IC_defective: defective & INSUFFICIENT_COVERAGE
    - RI_defective: defective & REFERENCE_INCONSISTENT
    - TN: equivalent & (CERTIFIED | CERTIFIED_WITH_WARNINGS)
    - FP: equivalent & NOT_CERTIFIED
    - IC_equivalent: equivalent & INSUFFICIENT_COVERAGE
    - RI_equivalent: equivalent & REFERENCE_INCONSISTENT
    """
    gt = ground_truth.upper()
    v = verdict.upper()

    if gt == "DEFECTIVE":
        if v == "NOT_CERTIFIED":
            return "TP"
        elif v in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS"):
            return "FC"
        elif v == "INSUFFICIENT_COVERAGE":
            return "IC_defective"
        elif v == "REFERENCE_INCONSISTENT":
            return "RI_defective"
        else:
            return "TP" if "NOT" in v else "FC"
    else:  # EQUIVALENT
        if v in ("CERTIFIED", "CERTIFIED_WITH_WARNINGS"):
            return "TN"
        elif v == "NOT_CERTIFIED":
            return "FP"
        elif v == "INSUFFICIENT_COVERAGE":
            return "IC_equivalent"
        elif v == "REFERENCE_INCONSISTENT":
            return "RI_equivalent"
        else:
            return "TN" if "CERT" in v else "FP"


def compute_aggregate_metrics(outcome_classes: list[str]) -> dict[str, Any]:
    """Computes full suite of metrics from list of outcome_class strings."""
    counts = {
        "TP": outcome_classes.count("TP"),
        "FP": outcome_classes.count("FP"),
        "TN": outcome_classes.count("TN"),
        "FC": outcome_classes.count("FC"),
        "IC_defective": outcome_classes.count("IC_defective"),
        "IC_equivalent": outcome_classes.count("IC_equivalent"),
        "RI_defective": outcome_classes.count("RI_defective"),
        "RI_equivalent": outcome_classes.count("RI_equivalent"),
    }
    counts["IC_total"] = counts["IC_defective"] + counts["IC_equivalent"]
    counts["RI_total"] = counts["RI_defective"] + counts["RI_equivalent"]
    counts["FN_total"] = counts["FC"] + counts["IC_defective"] + counts["RI_defective"]

    n_defective = counts["TP"] + counts["FC"] + counts["IC_defective"] + counts["RI_defective"]
    n_equivalent = counts["TN"] + counts["FP"] + counts["IC_equivalent"] + counts["RI_equivalent"]
    n_all = len(outcome_classes)

    tp, fp, tn, fc = counts["TP"], counts["FP"], counts["TN"], counts["FC"]
    ic_tot = counts["IC_total"]

    recall = round(tp / n_defective, 4) if n_defective > 0 else 0.0
    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 1.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0
    fcr = round(fc / n_defective, 4) if n_defective > 0 else 0.0
    fcr_among_certified = round(fc / (fc + tn), 4) if (fc + tn) > 0 else 0.0
    ic_rate = round(ic_tot / n_all, 4) if n_all > 0 else 0.0
    certified_prop = round((fc + tn) / n_all, 4) if n_all > 0 else 0.0

    return {
        "counts": counts,
        "n_defective": n_defective,
        "n_equivalent": n_equivalent,
        "n_all": n_all,
        "recall": recall,
        "recall_ci": wilson_ci(tp, n_defective),
        "recall_denominator": f"TP / N_defective ({tp} / {n_defective})",
        "precision": precision,
        "precision_ci": wilson_ci(tp, tp + fp),
        "precision_denominator": f"TP / (TP + FP) ({tp} / {tp + fp})",
        "f1_score": f1,
        "false_certification_rate": fcr,
        "false_certification_rate_ci": wilson_ci(fc, n_defective),
        "false_certification_rate_denominator": f"FC / N_defective ({fc} / {n_defective})",
        "error_rate_among_certified": fcr_among_certified,
        "error_rate_among_certified_ci": wilson_ci(fc, fc + tn),
        "error_rate_among_certified_denominator": f"FC / (FC + TN) ({fc} / {fc + tn})",
        "insufficient_coverage_rate": ic_rate,
        "insufficient_coverage_rate_ci": wilson_ci(ic_tot, n_all),
        "insufficient_coverage_rate_denominator": f"IC_total / N_all ({ic_tot} / {n_all})",
        "certified_proportion": certified_prop,
        "certified_proportion_ci": wilson_ci(fc + tn, n_all),
        "certified_proportion_denominator": f"(FC + TN) / N_all ({fc + tn} / {n_all})",
    }
