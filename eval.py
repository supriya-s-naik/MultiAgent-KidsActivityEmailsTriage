"""
eval.py: measures classifier_agent's recall against the hand-labeled ground truth.

recall = (true activity emails correctly classified as activity) / (total true activity emails)

This is the one metric this project tracks. Precision, latency, and
handoff-accuracy aren't measured here (see README.md).

Run with:  python eval.py
"""

import json
from pathlib import Path

from agents import classifier_agent

DATA_DIR = Path(__file__).resolve().parent / "data"


def main() -> None:
    with open(DATA_DIR / "sample_emails.json", encoding="utf-8") as f:
        emails = json.load(f)
    with open(DATA_DIR / "ground_truth.json", encoding="utf-8") as f:
        ground_truth = json.load(f)

    predicted = classifier_agent.classify_all(emails)

    true_activity_ids = [
        email_id for email_id, labels in ground_truth.items() if labels["is_activity"]
    ]
    correctly_found = [
        email_id for email_id in true_activity_ids if predicted.get(email_id) is True
    ]

    recall = len(correctly_found) / len(true_activity_ids)

    print(f"True activity emails in ground truth: {len(true_activity_ids)}")
    print(f"Correctly classified as activity:     {len(correctly_found)}")
    print(f"RECALL: {recall:.2%}")

    missed = [eid for eid in true_activity_ids if eid not in correctly_found]
    if missed:
        print(f"\nMissed (false negatives): {missed}")


if __name__ == "__main__":
    main()
