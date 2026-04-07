"""
export.py — Export reviewed cards to CSV for the human review GUI.

Column order is designed to match the GUI's expected intake format,
with new columns added for this pipeline (full_question_text, norc_url).
"""

import pandas as pd
LOGFILE = "export_warnings.log"

# Columns surfaced in the review CSV, in display order.
# The GUI shows these left-to-right.
REVIEW_CSV_COLS = [
    # ── Review metadata ───────────────────────────────────────────────────────
    "human_review",        # True = needs review; False = auto-approved
    "edit_type",           # NONE / MINOR_PHRASING / HIGH_EDIT
    "confidence",          # 0.0–1.0 reviewer confidence
    "flag_reason",         # plain-English reason for flagging
    "suggested_fix",       # reviewer's suggested edit, if any
    "reject",              # True = generator flagged as hypothetical/unsuitable
    "reject_reason",       # generator's rejection explanation

    # ── Generated card content ────────────────────────────────────────────────
    "variable",
    "question_text_generated",    # what the game will show (generator output)
    "question_text_final",        # editable copy — reviewers update this column in GUI
    "chosen_response",            # response(s) the pct represents (human-readable)
    "chosen_response_raw_labels", # raw label values used (for audit/decade extraction)
    "pct_overall",                # the headline percentage (0–100)

    # ── Source context (for reviewer to verify) ───────────────────────────────
    "question_text",             # original GSS question text
    "norc_url",                  # link to GSS variable page
    "description",               # GSS variable short description
    "var_type_guess",
    "inferred_type",             # set by binary_other sub-classifier
    "scale_type",                # set by ordinal generator
    "risk_tier",
    "conditional_reframe",       # the reframe prefix used, if any
    "pct_reasoning",             # how the pct was computed

    # ── Pipeline metadata ─────────────────────────────────────────────────────
    "pipeline_route",
    "generation_error",
    "n_responses",
    "n_years_asked",
    "subjects",
    "module",

    # ── Decade percentages (kept for downstream explode step) ─────────────────
    "pct_1970s",
    "pct_1980s",
    "pct_1990s",
    "pct_2000s",
    "pct_2010s",
    "pct_2020s",
]


def export_review_csv(reviewed_df: pd.DataFrame, output_path: str) -> None:
    """
    Flattens nested response_pcts into decade columns and writes the review CSV.

    Rows are sorted: human_review=True first (HIGH_EDIT before MINOR_PHRASING),
    then auto-approved rows.
    """
    df = reviewed_df.copy()

    # ── Add question_text_final ───────────────────────────────────────────────
    # Pre-populated from question_text_generated. Reviewers edit this column
    # directly in the GUI; suggested_fix sits next to it as reference.
    if "question_text_final" not in df.columns:
        df.insert(
            df.columns.get_loc("question_text_generated") + 1,
            "question_text_final",
            df["question_text_generated"]
        )

    # ── Flatten decade pct columns from nested response_pcts ─────────────────
    # response_pcts is a list of {resp_label, pct_overall, pct_1970s, …} dicts.
    # We need the decade values for the *chosen* response only.
    df = _extract_chosen_decade_pcts(df)

    # ── Sort for reviewer ergonomics ──────────────────────────────────────────
    edit_order = {"HIGH_EDIT": 0, "MINOR_PHRASING": 1, "NONE": 2, None: 3}
    df["_sort_edit"] = df["edit_type"].map(edit_order).fillna(3)
    df["_sort_review"] = (~df["human_review"].fillna(False)).astype(int)
    df = df.sort_values(["_sort_review", "_sort_edit"]).drop(
        columns=["_sort_edit", "_sort_review"]
    )

    # ── Select and order columns ──────────────────────────────────────────────
    present_cols = [c for c in REVIEW_CSV_COLS if c in df.columns]
    # Append any extra columns not in our list (future-proofing)
    extra_cols = [c for c in df.columns if c not in present_cols and not c.startswith("_")]
    output_df = df[present_cols + extra_cols]

    output_df.to_csv(output_path, index=False)
    print(f"  Written: {output_path} ({len(output_df)} rows)")


def _extract_chosen_decade_pcts(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each row, look up the chosen response(s) in response_pcts and
    extract decade percentages into flat columns, summing across combined responses.

    Uses 'chosen_response_raw_labels' (a list of individual label strings) when
    available — this is more reliable than parsing the human-readable chosen_response
    string, especially for combined ordinal responses like ["1", "2", "3"].

    Source pct values are in 0–1 range; multiplied by 100 here for output.
    """
    decade_cols = ["pct_1970s", "pct_1980s", "pct_1990s", "pct_2000s", "pct_2010s", "pct_2020s"]

    def _get_decade_pcts(row):
        pcts = row.get("response_pcts", [])
        if isinstance(pcts, str):
            import ast
            try:
                pcts = ast.literal_eval(pcts)
            except Exception:
                pcts = []

        if not pcts:
            return pd.Series({col: None for col in decade_cols})

        # Prefer raw labels list; fall back to parsing chosen_response string
        raw_labels = row.get("chosen_response_raw_labels")
        if isinstance(raw_labels, str):
            import ast
            try:
                raw_labels = ast.literal_eval(raw_labels)
            except Exception:
                raw_labels = None
        varname = row.get("variable", "UNKNOWN_VARIABLE") # for logging context in case of parsing issues
#        if not raw_labels: replace with explicit check for None/NaN/empty list, since an empty list is a valid value meaning "no labels matched"
        if (
            raw_labels is None
            or (isinstance(raw_labels, float) and pd.isna(raw_labels))
            or not isinstance(raw_labels, (list, tuple))
        ):
            print(f"====[WARN] Missing or invalid raw_labels for variable: {varname}====")
            chosen = row.get("chosen_response")
            if not chosen:
                return pd.Series({col: None for col in decade_cols})
            raw_labels = [p.strip() for p in str(chosen).split("+")]

        # Sanity check: raw_labels should now be a list of strings. If not, log an error and return empty decade values.
        if not isinstance(raw_labels, (list, tuple)):
            print(f"[ERROR] raw_labels not iterable for variable: {varname}")
            print(f"[ERROR] raw_labels value: {raw_labels}")
            return pd.Series({col: None for col in decade_cols})

        # Normalise labels to lowercase strings for matching
        raw_labels_norm = [str(l).strip().lower() for l in raw_labels]

        matched = [
            r for r in pcts
            if str(r.get("resp_code", "")).strip().lower() in raw_labels_norm #changed from resp_label to resp_code since generators return raw_labels in code form ("1", "2") rather than label form ("agree", "disagree") — matching against resp_code is more reliable across generators
        ]

        if not matched:
            varname = row.get("variable", "UNKNOWN_VARIABLE")
            #print(f"[WARN] No matching responses found for variable: {varname}")
            #print(f"[WARN] raw_labels_norm: {raw_labels_norm}")
            return pd.Series({col: None for col in decade_cols})

        # Sum across matched responses for each decade; multiply by 100 (source is 0–1)
        result = {}
        for col in decade_cols:
            vals = [
                r[col] for r in matched
                if r.get(col) is not None
                and not (isinstance(r[col], float) and r[col] != r[col])  # skip NaN
            ]
            result[col] = round(sum(vals) * 100, 2) if vals else None

        return pd.Series(result)

    def safe_get_decades_pcts(row):
        try:
            return _get_decade_pcts(row)
        except Exception as e:
            varname = row.get("variable", "UNKNOWN_VARIABLE")
            print(f"[ERROR] Exception while extracting decade pcts for variable: {varname}")
            print(f"[ERROR] Exception details: {e}")
            return pd.Series({col: None for col in decade_cols})


    decade_df = df.apply(safe_get_decades_pcts, axis=1)
    # Drop any existing decade cols before re-adding (avoid duplicate columns)
    df = df.drop(columns=[c for c in decade_cols if c in df.columns], errors="ignore")
    return pd.concat([df, decade_df], axis=1)