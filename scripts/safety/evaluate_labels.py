"""Offline comparison of supplied model predictions with current reviewed labels.

No network, inference, activation or publication. Inputs stay in ignored storage.
Agreement with reviewed labels is not population accuracy or evidence validation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

TAGS = {"violent_assault", "robbery", "threat", "sexual_offence", "property_offence", "possible_hate_crime"}


def ratio(n, d):
    return {"numerator": n, "denominator": d, "value": n / d if d else None}


def score(gold: dict, predictions: dict) -> dict:
    if gold.get("schema_version") != 1 or predictions.get("schema_version") != 1:
        raise ValueError("Unsupported evaluation schema")
    for key in ("model", "prompt_sha256"):
        if not predictions.get(key):
            raise ValueError(f"Missing {key}")
    expected, observed = {}, {}
    for item in gold["samples"]:
        ident = item["sample_id"]
        if ident in expected or not all(item.get(k) for k in ("source_sha256", "review_sha256", "category")):
            raise ValueError("Duplicate or incomplete current reviewed sample")
        if type(item.get("complete_tag_assessment")) is not bool or not set(item["tags"]) <= TAGS:
            raise ValueError("Invalid reviewed labels")
        expected[ident] = item
    for item in predictions["samples"]:
        ident = item["sample_id"]
        if ident not in expected or ident in observed or item["source_sha256"] != expected[ident]["source_sha256"]:
            raise ValueError("Unknown, duplicate or stale prediction")
        if not set(item["tags"]) <= TAGS:
            raise ValueError("Unrecognized model label")
        observed[ident] = item
    tag_counts = {tag: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for tag in sorted(TAGS)}
    category_match = 0
    tag_eligible = 0
    for ident, reference in expected.items():
        predicted = observed.get(ident)
        if predicted is None:
            continue
        category_match += predicted.get("category") == reference["category"]
        if not reference["complete_tag_assessment"]:
            continue
        tag_eligible += 1
        for tag, counts in tag_counts.items():
            present = tag in reference["tags"]
            claimed = tag in predicted["tags"]
            counts["tp" if present and claimed else "fp" if claimed else "fn" if present else "tn"] += 1
    for counts in tag_counts.values():
        counts["precision"] = ratio(counts["tp"], counts["tp"] + counts["fp"])
        counts["recall"] = ratio(counts["tp"], counts["tp"] + counts["fn"])
    return {
        "schema_version": 1, "method_version": "reviewed-label-comparison-v1",
        "model": predictions["model"], "prompt_sha256": predictions["prompt_sha256"],
        "gold_samples": len(expected), "returned_predictions": len(observed),
        "missing_predictions": len(expected) - len(observed),
        "category_agreement_among_returned": ratio(category_match, len(observed)),
        "category_match_among_all_offered": ratio(category_match, len(expected)),
        "tag_comparison_samples": tag_eligible,
        "tag_assessment_incomplete_excluded": sum(not r["complete_tag_assessment"] for r in expected.values()),
        "tags": tag_counts,
        "population_accuracy_established": False,
        "source_quote_evidence_validated_by_this_scorer": False,
        "limitations": ["Small selected reviewed labels are not independent population ground truth.",
                        "Missing predictions are reported separately, never counted as correct.",
                        "Incomplete tag assessment cannot establish negative labels.",
                        "No reviewed or published result is changed."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = score(json.loads(args.gold.read_text()), json.loads(args.predictions.read_text()))
    result["input_sha256"] = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for name, path in (("gold", args.gold), ("predictions", args.predictions))}
    if ".runtime" not in args.out.resolve().parts:
        raise ValueError("Evaluation output must remain in ignored .runtime storage")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
