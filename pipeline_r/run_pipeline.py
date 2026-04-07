"""
GSSdle card generation pipeline.

Usage:
    python run_pipeline.py --input gss_filtered_extract.csv --output review_cards.csv
    python run_pipeline.py --input gss_filtered_extract.csv --output review_cards.csv --dry-run
"""

import argparse
import pandas as pd
from pathlib import Path

from router import route_variables
from generators import run_generation_pass
from reviewer import run_review_pass
from export import export_review_csv


def main():
    parser = argparse.ArgumentParser(description="GSSdle card generation pipeline")
    parser.add_argument("--input", required=True, help="Path to gss_filtered_extract.csv")
    parser.add_argument("--output", required=True, help="Path for review CSV output")
    parser.add_argument("--dry-run", action="store_true",
                        help="Route and print routing summary only; no API calls")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="Cards per reviewer batch (default: 20)")
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    df = pd.read_csv(args.input)
    print(f"  {len(df)} rows, {df['variable'].nunique()} unique variables")

    # ── Step 1: Route ─────────────────────────────────────────────────────────
    print("\nRouting variables...")
    routed = route_variables(df)
    _print_routing_summary(routed)

    if args.dry_run:
        print("\n--dry-run: stopping before API calls.")
        routed.to_csv(Path(args.output).with_suffix(".routing_debug.csv"), index=False)
        return

    # ── Step 2: Generate ──────────────────────────────────────────────────────
    print("\nRunning generation pass (Haiku)...")
    generated = run_generation_pass(routed)
    print(f"  {len(generated)} cards generated")

    # ── Step 3: Review ────────────────────────────────────────────────────────
    print(f"\nRunning reviewer pass (Haiku, batch_size={args.batch_size})...")
    reviewed = run_review_pass(generated, batch_size=args.batch_size)
    n_flagged = reviewed["human_review"].sum()
    print(f"  {n_flagged} cards flagged for human review")
    print(f"  {len(reviewed) - n_flagged} cards auto-approved")

    # ── Step 4: Export ────────────────────────────────────────────────────────
    print(f"\nExporting to {args.output}...")
    export_review_csv(reviewed, args.output)
    print("Done.")


def _print_routing_summary(df: pd.DataFrame) -> None:
    counts = df["pipeline_route"].value_counts()
    print(f"  {'Route':<30} {'Variables':>10}")
    print(f"  {'-'*40}")
    for route, count in counts.items():
        print(f"  {route:<30} {count:>10}")


if __name__ == "__main__":
    main()