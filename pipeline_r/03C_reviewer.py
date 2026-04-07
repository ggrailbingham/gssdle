"""
reviewer.py — Review pass.

Sends cards to Haiku in batches for quality auditing.
Returns the input DataFrame with reviewer columns appended.
"""

import json
import pandas as pd
from tqdm import tqdm

from haiku_client import call_haiku
from prompts import REVIEWER


def run_review_pass(generated_df: pd.DataFrame, batch_size: int = 20) -> pd.DataFrame:
    """
    Batches generated cards and calls the reviewer agent.
    Skips rows that already have human_review=True (generation failures, skips).
    Returns the full DataFrame with reviewer columns merged in.
    """
    # Split into reviewable vs already-flagged
    already_flagged = generated_df[generated_df.get("human_review", False) == True].copy()
    to_review = generated_df[generated_df.get("human_review", False) != True].copy()

    # Cards with no generated question text can't be reviewed — move to flagged
    no_text_mask = to_review["question_text_generated"].isna()
    also_flagged = to_review[no_text_mask].copy()
    also_flagged["human_review"] = True
    also_flagged["flag_reason"] = also_flagged.get("flag_reason", "No question text generated")

    reviewable = to_review[~no_text_mask].copy()

    if len(reviewable) == 0:
        print("  No reviewable cards — all were skipped or failed generation.")
        return pd.concat([already_flagged, also_flagged], ignore_index=True)

    # Run batched review
    review_results = []
    batches = _make_batches(reviewable, batch_size)

    for batch_df in tqdm(batches, desc="Reviewing"):
        batch_results = _review_batch(batch_df)
        review_results.extend(batch_results)

    # Merge reviewer output back onto reviewable rows
    review_df = pd.DataFrame(review_results)
    reviewable = reviewable.merge(
        review_df[["variable", "confidence", "edit_type", "suggested_fix",
                   "flag_reason", "human_review"]],
        on="variable",
        how="left",
        suffixes=("", "_reviewer"),
    )

    # If reviewer set human_review, prefer it; else default False
    if "human_review_reviewer" in reviewable.columns:
        reviewable["human_review"] = reviewable["human_review_reviewer"].fillna(False)
        reviewable.drop(columns=["human_review_reviewer"], inplace=True)
    else:
        reviewable["human_review"] = reviewable.get("human_review", False)

    return pd.concat([reviewable, already_flagged, also_flagged], ignore_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Batch construction + API call
# ─────────────────────────────────────────────────────────────────────────────

def _make_batches(df: pd.DataFrame, batch_size: int) -> list[pd.DataFrame]:
    return [df.iloc[i:i + batch_size] for i in range(0, len(df), batch_size)]


def _review_batch(batch_df: pd.DataFrame) -> list[dict]:
    """
    Serialises a batch of cards into a user message and calls the reviewer.
    Returns a list of reviewer result dicts (one per card).
    """
    cards_payload = []
    for _, row in batch_df.iterrows():
        pcts = row.get("response_pcts", [])
        if isinstance(pcts, str):
            import ast
            try:
                pcts = ast.literal_eval(pcts)
            except Exception:
                pcts = []

        # Strip decade columns from response_pcts — reviewer only needs pct_overall per response
        pcts_for_review = [
            {"resp_label": r.get("resp_label"), "pct_overall": r.get("pct_overall")}
            for r in pcts
        ]

        cards_payload.append({
            "variable":              row.get("variable"),
            "var_type":              row.get("var_type_guess"),
            "inferred_type":         row.get("inferred_type"),
            "scale_type":            row.get("scale_type"),
            "risk_tier":             row.get("risk_tier"),
            "original_question":     row.get("question_text"),
            "generated_question":    row.get("question_text_generated"),
            "chosen_response":       row.get("chosen_response"),
            "pct_overall_claimed":   row.get("pct_overall"),
            "pct_reasoning":         row.get("pct_reasoning"),
            "conditional_reframe":   row.get("conditional_reframe"),
            "generator_reject":      row.get("reject", False),
            "generator_reject_reason": row.get("reject_reason"),
            "response_pcts":         pcts_for_review,
        })

    user_msg = (
        "Please review the following batch of generated GSSdle cards.\n\n"
        + json.dumps(cards_payload, indent=2)
    )

    try:
        results = call_haiku(
            system_prompt=REVIEWER,
            user_message=user_msg,
            max_tokens=4096,
            expect_json=True,
        )
    except Exception as e:
        # Reviewer failure — flag the whole batch for human review
        return [
            {
                "variable": row.get("variable"),
                "confidence": 0.0,
                "edit_type": "HIGH_EDIT",
                "suggested_fix": None,
                "flag_reason": f"Reviewer agent failed: {e}",
                "human_review": True,
            }
            for _, row in batch_df.iterrows()
        ]

    # results should be a list; validate length matches batch
    if not isinstance(results, list):
        # Haiku returned a dict instead of array — wrap it
        results = [results]

    # Pad with failure records if Haiku returned fewer items than expected
    expected = len(batch_df)
    if len(results) < expected:
        variables_in_batch = list(batch_df["variable"])
        returned_vars = {r.get("variable") for r in results}
        for var in variables_in_batch:
            if var not in returned_vars:
                results.append({
                    "variable": var,
                    "confidence": 0.0,
                    "edit_type": "HIGH_EDIT",
                    "suggested_fix": None,
                    "flag_reason": "Reviewer did not return a result for this card",
                    "human_review": True,
                })

    return results