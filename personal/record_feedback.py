#!/usr/bin/env python3
"""Import a review-page JSON export into the private taste dataset."""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWED = {"post", "watch", "skip"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("review_json", type=Path)
    args = parser.parse_args()
    review = json.loads(args.review_json.read_text())
    date = review["date"]
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise SystemExit("Invalid review date")
    path = HERE / "feedback" / f"{date}.json"
    existing = json.loads(path.read_text()) if path.exists() else {"date": date, "decisions": []}
    merged = {item["id"]: item for item in existing["decisions"]}
    for item in review["decisions"]:
        if item["vote"] not in ALLOWED or not item.get("id"):
            raise SystemExit("Invalid review decision")
        merged[item["id"]] = item
    path.parent.mkdir(parents=True, exist_ok=True)
    existing["decisions"] = list(merged.values())
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
    print(f"Saved {len(existing['decisions'])} decisions to {path}")


if __name__ == "__main__":
    main()
