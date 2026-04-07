"""
generators.py — Generation pass.

For each routed variable, calls the appropriate Haiku generator prompt
and returns a flat DataFrame of generated cards.
"""

import json
import pandas as pd
from tqdm import tqdm

from haiku_client import call_haiku
from prompts import (
    BINARY_GENERATOR,
    BINARY_OTHER_GENERATOR,
    ORDINAL_GENERATOR,
    MULTINOMIAL_GENERATOR,
)


# Columns forwarded into the final card (everything else is pipeline-internal)
PASSTHROUGH_COLS = [
    "variable",
    "description",
    "question_text",       # original GSS question text (for reviewer GUI)
    "value_labels",
    "n_responses",
    "var_type_guess",
    "actual_iap",
    "conditional_risk",
    "final_cond_risk",
    "risk_tier",
    "n_years_asked",
    "subjects",
    "module",
    "norc_url",
    "pipeline_route",
    "response_pcts",       # nested list of {resp_label, pct_overall, pct_1970s, …}
]


def run_generation_pass(routed_df: pd.DataFrame) -> pd.DataFrame:
    """
    Iterates over routed variables, calls the appropriate generator,
    and returns one row per generated card.

    unknown_skip variables are preserved with a flag but no generation.
    """
    records = []

    for _, row in tqdm(routed_df.iterrows(), total=len(routed_df), desc="Generating"):
        route = row["pipeline_route"]

        if route == "unknown_skip":
            records.append(_make_skip_record(row, "ROUTE_UNKNOWN"))
            continue

        try:
            card = _generate_card(row, route)
            records.append({**_passthrough(row), **card, "generation_error": None})
        except Exception as e:
            records.append({
                **_passthrough(row),
                "generation_error": str(e),
                "human_review": True,
                "flag_reason": f"Generation failed: {e}",
            })

    return pd.DataFrame(records)


# ─────────────────────────────────────────────────────────────────────────────
# Route dispatch
# ─────────────────────────────────────────────────────────────────────────────

def _generate_card(row: pd.Series, route: str) -> dict:
    user_msg = _build_user_message(row)

    prompt_map = {
        "binary":       BINARY_GENERATOR,
        "binary_other": BINARY_OTHER_GENERATOR,
        "ordinal":      ORDINAL_GENERATOR,
        "multinomial":  MULTINOMIAL_GENERATOR,
    }
    system_prompt = prompt_map[route]

    result = call_haiku(system_prompt=system_prompt, user_message=user_msg)

    # Normalise output schema across generator types
    return _normalise_card(result, row)


def _build_user_message(row: pd.Series) -> str:
    """
    Serialises all variable context into a structured text block for Haiku.
    Decade pct columns are included so Haiku can see the data but is not
    asked to use them in question text generation.
    """
    pcts = row.get("response_pcts", [])
    if isinstance(pcts, str):
        # Can happen if df was read from CSV (nested dicts serialised as string)
        import ast
        try:
            pcts = ast.literal_eval(pcts)
        except Exception:
            pcts = []

    # Format response options as a readable table.
    # Source data is in 0–1 range; multiply by 100 so Haiku sees "5.55%" not "0.06%".
    # Decade columns are intentionally excluded — generator never uses them,
    # and they account for ~150-300 tokens of unnecessary input per variable.
    pct_lines = []
    for r in pcts:
        label = r.get("resp_label") or "?"
        overall = r.get("pct_overall")
        overall_str = f"{overall * 100:.2f}%" if overall is not None else "N/A"
        pct_lines.append(f"  {label:<30} overall={overall_str}")

    pct_block = chr(10).join(pct_lines) if pct_lines else "  (no response data available)"
    return (
        f"VARIABLE: {row.get('variable')}\n"
        f"DESCRIPTION: {row.get('description')}\n"
        f"QUESTION TEXT (original GSS): {row.get('question_text')}\n"
        f"VAR TYPE: {row.get('var_type_guess')}\n"
        f"RISK TIER: {row.get('risk_tier')}\n"
        f"N RESPONSES: {row.get('n_responses')}\n"
        f"SUBJECTS: {row.get('subjects')}\n"
        f"\n"
        f"RESPONSE OPTIONS AND PERCENTAGES\n"
        f"(values are in 0-100 scale; 42.30 means 42.30%, not 0.423):\n"
        f"{pct_block}\n"
        f"\n"
        f"PRECISION RULE: Use the exact percentage values shown above in pct_overall.\n"
        f"Keep at least 2 decimal places (e.g. report 5.55, not 5.6 or 6).\n"
        f"When combining responses, sum their exact values and keep 2 decimal places."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Schema normalisation — unify fields across generator types
# ─────────────────────────────────────────────────────────────────────────────

def _bare_label(label: str) -> str:
    """
    Extract the bare resp_label value from a potentially decorated string.
    Haiku sometimes returns "1 - hard-working" or "2 (lean holy)" when we only
    want "1" or "2" for matching against resp_label values in response_pcts.

    Rules:
    - If the label starts with a number, return just that number (integer or float).
    - If the label is a plain word like "yes" / "no" / "agree", return as-is lowercased.
    - Strip anything after " - ", " (", or " —" that looks like a description.
    """
    s = str(label).strip()
    # Remove description suffixes: " - ...", " (..."," — ..."
    import re
    s = re.split(r'\s[-—(]', s)[0].strip()
    # If it's purely numeric (possibly with decimals), normalise
    try:
        num = float(s)
        return str(int(num)) if num == int(num) else str(num)
    except ValueError:
        return s.lower()


def _normalise_card(raw: dict, row: pd.Series) -> dict:
    """
    Different generators return slightly different schemas (e.g. ordinal returns
    'chosen_responses' as a list, others return 'chosen_response' as a string).
    Normalise to a single flat schema here.

    Also stores 'chosen_response_raw_labels': the individual response label values
    (as a list of strings) used for decade pct extraction in export.py.
    This is more reliable than parsing the human-readable 'chosen_response' string.
    """
    # chosen_response: always a string; keep raw list for decade extraction
    if "chosen_responses" in raw and isinstance(raw["chosen_responses"], list):
        raw_labels = [_bare_label(r) for r in raw["chosen_responses"]]
        raw["chosen_response_raw_labels"] = raw_labels
        raw["chosen_response"] = " + ".join(str(r) for r in raw["chosen_responses"])
        del raw["chosen_responses"]
    elif "chosen_response" in raw:
        raw["chosen_response_raw_labels"] = [
            _bare_label(p.strip()) for p in str(raw["chosen_response"]).split("+")
        ]

    # inferred_type from binary_other — promote to top-level
    raw.setdefault("inferred_type", None)
    raw.setdefault("scale_type", None)
    raw.setdefault("conditional_reframe", None)
    raw.setdefault("pct_reasoning", None)
    raw.setdefault("pct_overall", None)
    raw.setdefault("chosen_response_raw_labels", [])
    raw.setdefault("question_text_generated", None)  # Haiku writes this directly now
    raw.setdefault("reject", False)
    raw.setdefault("reject_reason", None)

    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _passthrough(row: pd.Series) -> dict:
    return {
        col: row.get(col)
        for col in PASSTHROUGH_COLS
        if col in row.index
    }


def _make_skip_record(row: pd.Series, reason: str) -> dict:
    return {
        **_passthrough(row),
        "question_text_generated": None,
        "chosen_response": None,
        "pct_overall": None,
        "inferred_type": None,
        "scale_type": None,
        "conditional_reframe": None,
        "pct_reasoning": None,
        "generation_error": reason,
        "human_review": True,
        "flag_reason": reason,
    }