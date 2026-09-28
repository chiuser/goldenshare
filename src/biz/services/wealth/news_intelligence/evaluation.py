from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    labels: Mapping[str, Mapping[str, float | int]]
    macro_f1: float
    micro_f1: float
    core_recall: float


def classification_metrics(
    gold: Sequence[set[str]],
    predicted: Sequence[set[str]],
    *,
    core_labels: frozenset[str] = frozenset(),
) -> ClassificationMetrics:
    if len(gold) != len(predicted):
        raise ValueError("gold and predicted must have equal length")
    labels = sorted(set().union(*gold, *predicted)) if gold else []
    per_label: dict[str, dict[str, float | int]] = {}
    total_tp = total_fp = total_fn = 0
    core_tp = core_fn = 0
    for label in labels:
        tp = sum(
            label in expected and label in actual
            for expected, actual in zip(gold, predicted, strict=True)
        )
        fp = sum(
            label not in expected and label in actual
            for expected, actual in zip(gold, predicted, strict=True)
        )
        fn = sum(
            label in expected and label not in actual
            for expected, actual in zip(gold, predicted, strict=True)
        )
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        f1 = _f1(precision, recall)
        per_label[label] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn
        if label in core_labels:
            core_tp += tp
            core_fn += fn
    micro_precision = _ratio(total_tp, total_tp + total_fp)
    micro_recall = _ratio(total_tp, total_tp + total_fn)
    return ClassificationMetrics(
        labels=per_label,
        macro_f1=_mean([float(metrics["f1"]) for metrics in per_label.values()]),
        micro_f1=_f1(micro_precision, micro_recall),
        core_recall=_ratio(core_tp, core_tp + core_fn),
    )


def candidate_recall(gold: Sequence[set[str]], candidates: Sequence[set[str]]) -> float:
    if len(gold) != len(candidates):
        raise ValueError("gold and candidates must have equal length")
    expected = sum(len(labels) for labels in gold)
    recalled = sum(
        len(labels & proposed)
        for labels, proposed in zip(gold, candidates, strict=True)
    )
    return _ratio(recalled, expected)


def pairwise_clustering_metrics(
    gold_cluster_by_sample: Mapping[str, str],
    predicted_cluster_by_sample: Mapping[str, str],
) -> Mapping[str, float | int]:
    sample_ids = sorted(set(gold_cluster_by_sample) & set(predicted_cluster_by_sample))
    tp = fp = fn = 0
    for left_index, left in enumerate(sample_ids):
        for right in sample_ids[left_index + 1 :]:
            gold_same = gold_cluster_by_sample[left] == gold_cluster_by_sample[right]
            predicted_same = (
                predicted_cluster_by_sample[left] == predicted_cluster_by_sample[right]
            )
            if gold_same and predicted_same:
                tp += 1
            elif predicted_same:
                fp += 1
            elif gold_same:
                fn += 1
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
    }


def ranking_metrics(
    ranked_ids: Sequence[str],
    *,
    relevant_ids: frozenset[str],
    relevance_grades: Mapping[str, int],
    critical_ids: frozenset[str] = frozenset(),
) -> Mapping[str, float | int | list[str]]:
    top15 = tuple(ranked_ids[:15])
    top30 = tuple(ranked_ids[:30])
    precision_at_15 = _ratio(sum(item in relevant_ids for item in top15), len(top15))
    recall_at_30 = _ratio(
        sum(item in relevant_ids for item in top30), len(relevant_ids)
    )
    dcg = _dcg([relevance_grades.get(item, 0) for item in top15])
    ideal = _dcg(sorted(relevance_grades.values(), reverse=True)[:15])
    missed = sorted(critical_ids - set(top30))
    return {
        "precision_at_15": precision_at_15,
        "recall_at_30": recall_at_30,
        "ndcg_at_15": _ratio(dcg, ideal),
        "critical_miss_count": len(missed),
        "critical_missed_ids": missed,
    }


def krippendorff_alpha_nominal(rounds: Sequence[Sequence[str | None]]) -> float:
    """Nominal alpha for repeat annotations; missing values are ignored."""
    usable = [tuple(value for value in unit if value is not None) for unit in rounds]
    usable = [unit for unit in usable if len(unit) >= 2]
    if not usable:
        raise ValueError("at least one unit with two annotations is required")
    observed_disagreements = sum(
        sum(
            left != right
            for index, left in enumerate(unit)
            for right in unit[index + 1 :]
        )
        for unit in usable
    )
    observed_pairs = sum(len(unit) * (len(unit) - 1) // 2 for unit in usable)
    observed = _ratio(observed_disagreements, observed_pairs)
    values = [value for unit in usable for value in unit]
    counts = Counter(values)
    total = len(values)
    expected_agreement = sum((count / total) ** 2 for count in counts.values())
    expected = 1.0 - expected_agreement
    if expected == 0:
        return 1.0 if observed == 0 else 0.0
    return 1.0 - observed / expected


def summary_audit_metrics(
    records: Iterable[Mapping[str, object]],
) -> Mapping[str, int | bool]:
    records = tuple(records)
    numeric_entity_errors = sum(
        bool(record.get("numeric_or_entity_error")) for record in records
    )
    unsupported_claims = sum(
        bool(record.get("unsupported_claim")) for record in records
    )
    uncaught_parse_failures = sum(
        bool(record.get("parse_failed")) and not bool(record.get("failure_captured"))
        for record in records
    )
    return {
        "reviewed": len(records),
        "numeric_or_entity_errors": numeric_entity_errors,
        "unsupported_claims": unsupported_claims,
        "uncaught_parse_failures": uncaught_parse_failures,
        "passed": numeric_entity_errors == 0
        and unsupported_claims == 0
        and uncaught_parse_failures == 0,
    }


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _f1(precision: float, recall: float) -> float:
    return _ratio(2 * precision * recall, precision + recall)


def _mean(values: Sequence[float]) -> float:
    return 0.0 if not values else sum(values) / len(values)


def _dcg(grades: Sequence[int]) -> float:
    return sum(
        (2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades)
    )
