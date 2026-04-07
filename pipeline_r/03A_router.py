"""
router.py — Variable routing

Assigns each variable a pipeline_route before any Haiku calls.
All logic here is deterministic (no LLM).

Routes:
  binary              — var_type_guess=binary, labels present
  binary_other        — var_type_guess=binary_other (Haiku sub-classifies)
  ordinal             — var_type_guess=ordinal or ordinal_multi, labels present
  multinomial         — var_type_guess=multinomial, labels present
  unknown_skip        — var_type_guess=unknown, cannot route
"""

import pandas as pd


# One row per variable in the filtered extract.
# The CSV has multiple rows per variable (one per response option),
# so we deduplicate to variable-level for routing, then re-join.
VARIABLE_COLS = [
    "variable",
    "description",
    "question_text",
    "value_labels",
    "response_labels",
    "n_responses",
    "var_type_guess",
    "actual_iap",
    "expected_iap",
    "excess_iap",
    "iap_full_years",
    "conditional_risk",
    "final_cond_risk",
    "n_years_asked",
    "subjects",
    "module",
    "norc_url",
]

PCT_COLS_PREFIX = "pct_"  # pct_overall, pct_1970s, pct_1980s, …


def route_variables(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the full filtered extract (one row per variable×response_option).
    Returns one row per variable with routing metadata attached.
    """
    # Collapse to variable level — take first row per variable for metadata cols
    meta_cols = [c for c in VARIABLE_COLS if c in df.columns]
    var_df = df[meta_cols].drop_duplicates(subset="variable").copy()

    # Attach aggregated pct data as a nested structure per variable
    pct_cols = [c for c in df.columns if c.startswith(PCT_COLS_PREFIX)]
    response_rows = (
        df[["variable", "response_label"] + pct_cols]
        .copy()
        .rename(columns={"response_label": "resp_label"})
    )
    # Store as list of dicts per variable (will be serialised for prompt injection)
    pct_by_var = (
        response_rows
        .groupby("variable")
    #   .apply(lambda g: g.drop(columns="variable").to_dict(orient="records")) <-- variable is needed for merging back, so don't drop it here
        .apply(lambda g: g.reset_index(drop=True).to_dict(orient="records"))
        .rename("response_pcts")
        .reset_index()
    )
    var_df = var_df.merge(pct_by_var, on="variable", how="left")

    # ── Assign route ──────────────────────────────────────────────────────────
    var_df["pipeline_route"] = var_df.apply(_assign_route, axis=1)

    # ── Attach conditional risk tier ──────────────────────────────────────────
    # Prefer final_cond_risk, fall back to conditional_risk
    var_df["risk_tier"] = var_df.apply(
        lambda r: r.get("final_cond_risk") or r.get("conditional_risk") or "UNKNOWN",
        axis=1,
    )

    return var_df


def _assign_route(row: pd.Series) -> str:
    vtype = str(row.get("var_type_guess", "")).strip().lower()

    if vtype == "unknown":
        return "unknown_skip"

    if vtype == "binary":
        return "binary"

    if vtype == "binary_other":
        return "binary_other"

    if vtype in ("ordinal", "ordinal_multi"):
        return "ordinal"

    if vtype == "multinomial":
        return "multinomial"

    # Fallback — treat as binary_other so Haiku can attempt classification
    return "binary_other"