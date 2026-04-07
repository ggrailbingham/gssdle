"""
run_pipeline_resumable.py — Resumable card generation pipeline.

Processes variables in batches, writes results after every reviewer batch,
and can be stopped and restarted without losing work.

Usage:
    # First run (or fresh start):
    python run_pipeline_resumable.py --input gss_filtered_extract.csv --output review_cards.csv

    # Stop after first ~150 variables to inspect output:
    python run_pipeline_resumable.py --input gss_filtered_extract.csv --output review_cards.csv --stop-after 150

    # Resume from where you left off (skips already-processed variables):
    python run_pipeline_resumable.py --input gss_filtered_extract.csv --output review_cards.csv --resume

    # Dry run (routing only, no API calls):
    python run_pipeline_resumable.py --input gss_filtered_extract.csv --output review_cards.csv --dry-run
"""

import argparse
import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime

from router import route_variables
from export import export_review_csv, REVIEW_CSV_COLS


# ── Configuration ─────────────────────────────────────────────────────────────
REVIEWER_BATCH_SIZE = 20       # cards per Haiku reviewer call
PROGRESS_REPORT_EVERY = 500   # print stats summary every N variables
WRITE_AFTER_EVERY_BATCH = True # always write to disk after each reviewer batch


def main():
    parser = argparse.ArgumentParser(description="Resumable GSSdle card generation pipeline")
    parser.add_argument("--input",       required=True, help="Path to gss_filtered_extract.csv")
    parser.add_argument("--output",      required=True, help="Path for review CSV output")
    parser.add_argument("--resume",      action="store_true",
                        help="Skip variables already present in output file")
    parser.add_argument("--stop-after",  type=int, default=None,
                        help="Stop after processing this many variables (for staged review)")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Route and print summary only; no API calls")
    parser.add_argument("--batch-size",  type=int, default=REVIEWER_BATCH_SIZE)
    args = parser.parse_args()

    output_path = Path(args.output)

    # ── Load input ─────────────────────────────────────────────────────────────
    print(f"\nLoading {args.input}...")
    df = pd.read_csv(args.input)
    print(f"  {df['variable'].nunique()} unique variables, {len(df)} rows total")

    # ── Route all variables ────────────────────────────────────────────────────
    print("Routing variables...")
    routed = route_variables(df)
    _print_routing_summary(routed)

    if args.dry_run:
        print("\n--dry-run: stopping before API calls.")
        routed.to_csv(output_path.with_suffix(".routing_debug.csv"), index=False)
        return

    # ── Resume: skip already-processed variables ───────────────────────────────
    already_done = set()
    existing_rows = []
    if args.resume and output_path.exists():
        existing_df = pd.read_csv(output_path)
        already_done = set(existing_df["variable"].dropna().unique())
        existing_rows = [existing_df]
        print(f"\nResuming — {len(already_done)} variables already processed, skipping.")

    remaining = routed[~routed["variable"].isin(already_done)].reset_index(drop=True)

    if args.stop_after:
        remaining = remaining.iloc[:args.stop_after]
        print(f"--stop-after {args.stop_after}: will process {len(remaining)} variables then stop.")

    print(f"\nVariables to process this run: {len(remaining)}")
    if len(remaining) == 0:
        print("Nothing to do.")
        return

    # ── Process in reviewer-sized batches, writing after each ─────────────────
    all_new_cards = []
    total_processed = 0
    total_since_last_report = 0

    gen_batch = []   # accumulate generated cards until we have a full reviewer batch

    for idx, row in remaining.iterrows():
        # Generate card for this variable
        card = _generate_one(row)
        gen_batch.append(card)
        total_processed += 1
        total_since_last_report += 1

        # When batch is full (or we're at the last variable), run reviewer + write
        is_last = (total_processed == len(remaining))
        if len(gen_batch) >= args.batch_size or is_last:
            reviewed_batch = _review_and_flag(gen_batch, row)
            all_new_cards.extend(reviewed_batch)
            gen_batch = []

            # Write to disk immediately after every reviewer batch
            if WRITE_AFTER_EVERY_BATCH:
                _write_output(existing_rows, all_new_cards, output_path)

        # Progress report every N variables
        if total_since_last_report >= PROGRESS_REPORT_EVERY or is_last:
            _print_progress_report(existing_rows, all_new_cards, total_processed, len(remaining))
            total_since_last_report = 0

    # Final write (in case last batch wasn't a multiple of batch_size)
    _write_output(existing_rows, all_new_cards, output_path)

    print(f"\n{'='*60}")
    print(f"Run complete. {total_processed} variables processed.")
    print(f"Output: {output_path}")
    _print_progress_report(existing_rows, all_new_cards, total_processed, len(remaining))


# ─────────────────────────────────────────────────────────────────────────────
# Single-variable generation (wraps generators.py)
# ─────────────────────────────────────────────────────────────────────────────

def _generate_one(row: pd.Series) -> dict:
    """Generate a card for a single routed variable. Returns a dict."""
    from generators import _generate_card, _passthrough, _make_skip_record
    route = row["pipeline_route"]

    if route == "unknown_skip":
        return _make_skip_record(row, "ROUTE_UNKNOWN")

    try:
        card = _generate_card(row, route)
        return {**_passthrough(row), **card, "generation_error": None}
    except Exception as e:
        return {
            **_passthrough(row),
            "question_text_generated": None,
            "chosen_response": None,
            "pct_overall": None,
            "generation_error": str(e),
            "human_review": True,
            "flag_reason": f"Generation failed: {e}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Batch review (wraps reviewer.py)
# ─────────────────────────────────────────────────────────────────────────────

def _review_and_flag(gen_batch: list[dict], last_row: pd.Series) -> list[dict]:
    """
    Run the reviewer over a batch of generated card dicts.
    Returns the same dicts with reviewer columns merged in.
    """
    import pandas as pd
    from reviewer import _review_batch

    batch_df = pd.DataFrame(gen_batch)

    # Cards with no generated text skip the reviewer
    no_text = batch_df["question_text_generated"].isna()
    reviewable = batch_df[~no_text].copy()
    skipped = batch_df[no_text].copy()
    skipped["human_review"] = True
    skipped["flag_reason"] = skipped.get("flag_reason", "No question text generated")

    results = []
    if len(reviewable) > 0:
        review_results = _review_batch(reviewable)
        review_df = pd.DataFrame(review_results)
        merged = reviewable.merge(
            review_df[["variable", "confidence", "edit_type",
                        "suggested_fix", "flag_reason", "human_review"]],
            on="variable", how="left", suffixes=("", "_reviewer")
        )
        if "human_review_reviewer" in merged.columns:
            merged["human_review"] = merged["human_review_reviewer"].fillna(False)
            merged.drop(columns=["human_review_reviewer"], inplace=True)
        results.extend(merged.to_dict(orient="records"))

    results.extend(skipped.to_dict(orient="records"))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Output writing
# ─────────────────────────────────────────────────────────────────────────────

def _write_output(existing_rows: list, new_cards: list[dict], output_path: Path) -> None:
    """Merge existing + new cards and write to CSV atomically (write to temp then rename)."""
    import pandas as pd
    from export import _extract_chosen_decade_pcts, REVIEW_CSV_COLS

    new_df = pd.DataFrame(new_cards)
    new_df = _extract_chosen_decade_pcts(new_df)

    # Add question_text_final to new rows before concat — editable copy for GUI.
    # Must happen before concat so existing_rows (which may already have the column)
    # don't cause a shape mismatch.
    if "question_text_final" not in new_df.columns:
        new_df["question_text_final"] = new_df["question_text_generated"]

    all_frames = existing_rows + [new_df]
    combined = pd.concat(all_frames, ignore_index=True)

    # Backfill question_text_final for any older rows that predate this column
    if "question_text_final" in combined.columns:
        mask = combined["question_text_final"].isna() & combined["question_text_generated"].notna()
        combined.loc[mask, "question_text_final"] = combined.loc[mask, "question_text_generated"]

    # Sort: flagged first, then by edit severity
    edit_order = {"HIGH_EDIT": 0, "MINOR_PHRASING": 1, "NONE": 2, None: 3}
    combined["_sort_edit"] = combined.get("edit_type", pd.Series(dtype=str)).map(edit_order).fillna(3)
    combined["_sort_review"] = (~combined.get("human_review", pd.Series(False)).fillna(False)).astype(int)
    combined = combined.sort_values(["_sort_review", "_sort_edit"]).drop(
        columns=["_sort_edit", "_sort_review"], errors="ignore"
    )

    present_cols = [c for c in REVIEW_CSV_COLS if c in combined.columns]
    extra_cols = [c for c in combined.columns if c not in present_cols and not c.startswith("_")]
    output_df = combined[present_cols + extra_cols]

    # Atomic write: temp file → rename
    tmp_path = output_path.with_suffix(".tmp.csv")
    output_df.to_csv(tmp_path, index=False)
    tmp_path.replace(output_path)


# ─────────────────────────────────────────────────────────────────────────────
# Progress reporting
# ─────────────────────────────────────────────────────────────────────────────

def _print_progress_report(
    existing_rows: list,
    new_cards: list[dict],
    processed_this_run: int,
    total_this_run: int,
) -> None:
    import pandas as pd

    if not new_cards:
        return

    new_df = pd.DataFrame(new_cards)
    all_frames = existing_rows + [new_df]
    combined = pd.concat(all_frames, ignore_index=True)

    total = len(combined)
    timestamp = datetime.now().strftime("%H:%M:%S")

    print(f"\n{'─'*60}")
    print(f"  PROGRESS REPORT  [{timestamp}]  "
          f"{processed_this_run}/{total_this_run} this run  |  {total} total in file")
    print(f"{'─'*60}")

    # Human review breakdown
    hr = combined.get("human_review", pd.Series(dtype=bool)).fillna(False)
    n_review = hr.sum()
    n_auto   = (~hr).sum()
    print(f"  Human review required : {n_review:>5}  ({100*n_review/total:.1f}%)")
    print(f"  Auto-approved         : {n_auto:>5}  ({100*n_auto/total:.1f}%)")

    # Edit type breakdown
    if "edit_type" in combined.columns:
        et = combined["edit_type"].value_counts(dropna=False)
        print(f"\n  Edit type breakdown:")
        for etype in ["HIGH_EDIT", "MINOR_PHRASING", "NONE", None]:
            n = et.get(etype, 0)
            label = str(etype) if etype else "None/missing"
            print(f"    {label:<20} {n:>5}")

    # Rejects
    if "reject" in combined.columns:
        n_reject = combined["reject"].fillna(False).astype(bool).sum()
        print(f"\n  Generator rejects     : {n_reject:>5}")
        if n_reject > 0 and "reject_reason" in combined.columns:
            reasons = (combined[combined["reject"].fillna(False).astype(bool)]
                       ["reject_reason"].value_counts().head(5))
            for reason, count in reasons.items():
                snippet = str(reason)[:55]
                print(f"    {count:>3}x  {snippet}")

    # Confidence bands
    if "confidence" in combined.columns:
        conf = pd.to_numeric(combined["confidence"], errors="coerce").dropna()
        if len(conf) > 0:
            print(f"\n  Confidence bands (of {len(conf)} reviewed cards):")
            print(f"    < 0.60  : {(conf < 0.60).sum():>5}")
            print(f"    0.60–0.79: {((conf >= 0.60) & (conf < 0.80)).sum():>5}")
            print(f"    0.80–0.89: {((conf >= 0.80) & (conf < 0.90)).sum():>5}")
            print(f"    ≥ 0.90  : {(conf >= 0.90).sum():>5}")

    print(f"{'─'*60}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Routing summary
# ─────────────────────────────────────────────────────────────────────────────

def _print_routing_summary(df: pd.DataFrame) -> None:
    counts = df["pipeline_route"].value_counts()
    print(f"\n  {'Route':<25} {'Variables':>10}")
    print(f"  {'─'*35}")
    for route, count in counts.items():
        print(f"  {route:<25} {count:>10}")
    print()


if __name__ == "__main__":
    main()