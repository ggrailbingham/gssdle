"""
explode_decades.py — Post-review decade explosion.

Run AFTER human review is complete on the review CSV.
Reads approved cards, explodes to one row per variable × decade,
and outputs cards.json for the game.

Usage:
    python explode_decades.py \
        --input  game_cards_reviewed.csv \
        --years  years_lookup.csv \
        --output cards.json

Requirements:
    pip install pandas
"""

import argparse
import ast
import json
import math
import re
import pandas as pd


DECADE_COLS = {
    "pct_1970s": "1970s",
    "pct_1980s": "1980s",
    "pct_1990s": "1990s",
    "pct_2000s": "2000s",
    "pct_2010s": "2010s",
    "pct_2020s": "2020s",
}




def main():
    parser = argparse.ArgumentParser(description="Explode reviewed cards to per-decade JSON")
    parser.add_argument("--input",  required=True, help="game_cards_reviewed.csv path")
    parser.add_argument("--years",  required=True, help="years_lookup.csv path")
    parser.add_argument("--output", required=True, help="Output cards.json path")
    args = parser.parse_args()

    # ── Load reviewed cards ───────────────────────────────────────────────────
    df = pd.read_csv(args.input, dtype=str)
    print(f"Loaded {len(df)} rows from {args.input}")

    # Normalise the status column — blank / NaN → ""
    status_col = "Human review status"
    if status_col not in df.columns:
        print(f"  WARNING: '{status_col}' column not found — treating all rows as approved")
        df[status_col] = ""
    df[status_col] = df[status_col].fillna("").str.strip().str.lower()

    # One row per variable (the CSV has one row per variable, not per response)
    # but guard against accidental duplicates by keeping the first occurrence.
    before = len(df)
    df = df.drop_duplicates(subset="variable", keep="first")
    if len(df) < before:
        print(f"  Dropped {before - len(df)} duplicate variable rows")

    # Exclude only explicitly rejected/deferred cards.
    # 'pending' = never reviewed in GUI → auto-approved, include.
    # blank/NaN = same.
    EXCLUDE_STATUSES = {"removed", "deferred", "skipped"}
    excluded = df[df[status_col].isin(EXCLUDE_STATUSES)]
    approved = df[~df[status_col].isin(EXCLUDE_STATUSES)].copy()
    excl_counts = excluded[status_col].value_counts().to_dict()
    print(f"  Included: {len(approved)}  |  Excluded: {len(excluded)}  {excl_counts}")

    # ── Load years lookup ─────────────────────────────────────────────────────
    years_df = pd.read_csv(args.years, dtype=str)
    # Build dict: (variable, decade) → "1972, 1974, 1976"
    years_lookup: dict[tuple[str, str], str] = {}
    for _, row in years_df.iterrows():
        years_lookup[(row["variable"], row["decade"])] = row["years_asked"]
    print(f"Loaded {len(years_lookup)} variable × decade entries from {args.years}")

    # ── Explode ───────────────────────────────────────────────────────────────
    cards = []
    skipped_no_data = 0
    skipped_no_pct  = 0

    for _, row in approved.iterrows():
        var = str(row.get("variable", "")).strip()

        # Parse chosen response labels once (used for every decade of this var)
        chosen_nums = _parse_chosen_nums(
            row.get("chosen_response_raw_labels", ""),
            row.get("chosen_response", ""),
        )

        # Parse full response_pcts structure once
        resp_pcts = _parse_response_pcts(row.get("response_pcts", ""))

        for pct_col, decade_label in DECADE_COLS.items():
            # ── Compute pct for this decade ───────────────────────────────
            # Strategy: sum the chosen response labels' decade-specific pcts
            # from response_pcts (which has per-decade breakdown).
            # Fall back to the scalar pct_XXXX column if response_pcts is unavailable.
            pct_value = _compute_decade_pct(
                chosen_nums  = chosen_nums,
                resp_pcts    = resp_pcts,
                decade_label = decade_label,
                fallback_col = row.get(pct_col),
            )

            if pct_value is None:
                skipped_no_data += 1
                continue

            # ── Get years asked ───────────────────────────────────────────
            years_asked = years_lookup.get((var, decade_label), "")

            # ── Build card ────────────────────────────────────────────────
            card = _build_card(row, var, decade_label, pct_value, years_asked, chosen_nums)
            if card is None:
                skipped_no_pct += 1
                continue
            cards.append(card)

    print(f"\nGenerated {len(cards)} cards")
    print(f"  Skipped (no decade data): {skipped_no_data}")
    print(f"  Skipped (pct invalid):    {skipped_no_pct}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Written: {args.output}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_chosen_nums(raw_labels: str, chosen_response: str) -> set[float]:
    """Return a set of float response-label numbers that are chosen."""
    # Try chosen_response_raw_labels first: "['1', '2']"
    raw = str(raw_labels).strip()
    if raw and raw.lower() not in ("nan", "none", ""):
        try:
            lst = ast.literal_eval(raw.replace("'", "'").replace("'", "'"))
            nums = {float(v) for v in lst if _is_number(v)}
            if nums:
                return nums
        except Exception:
            pass

    # Fallback: chosen_response "1.0 + 2.0"
    cr = str(chosen_response).strip()
    if cr and cr.lower() not in ("nan", "none", ""):
        nums = set()
        for part in re.split(r"\+", cr):
            part = part.strip()
            if _is_number(part):
                nums.add(float(part))
        if nums:
            return nums

    return set()


def _parse_response_pcts(resp_pcts_str: str) -> list[dict]:
    """
    Parse the response_pcts Python-literal column into a list of dicts.
    Each dict has keys: resp_label (float), pct_overall, pct_1970s, …
    Values are 0–1 fractions (or None/NaN).
    Returns [] on failure.
    """
    s = str(resp_pcts_str).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return []
    try:
        # Convert Python literal to JSON-parseable string
        s2 = (s
              .replace("'", '"')
              .replace("nan", "null")
              .replace("None", "null")
              .replace("True", "true")
              .replace("False", "false"))
        lst = json.loads(s2)
        return lst if isinstance(lst, list) else []
    except Exception:
        return []


def _compute_decade_pct(
    chosen_nums:  set[float],
    resp_pcts:    list[dict],
    decade_label: str,           # e.g. "1980s"
    fallback_col,                # scalar value from pct_1980s column
) -> float | None:
    """
    Return the summed percentage (0–100) for chosen labels in this decade.
    Returns None if data is absent.
    """
    decade_key = f"pct_{decade_label}"   # e.g. "pct_1980s"

    # ── Primary: sum from response_pcts ──────────────────────────────────────
    if resp_pcts and chosen_nums:
        total = 0.0
        found_any = False
        for entry in resp_pcts:
            try:
                label = float(entry.get("resp_label", "nan"))
            except (TypeError, ValueError):
                continue
            if label not in chosen_nums:
                continue
            raw = entry.get(decade_key)
            if raw is None or (isinstance(raw, float) and math.isnan(raw)):
                continue
            try:
                val = float(raw)
                if not math.isnan(val):
                    total += val
                    found_any = True
            except (TypeError, ValueError):
                continue
        if found_any:
            # response_pcts values are 0–1 fractions → convert to 0–100
            return round(total * 100, 2)

    # ── Fallback: scalar pct_XXXX column ─────────────────────────────────────
    if fallback_col is not None:
        try:
            val = float(fallback_col)
            if not math.isnan(val):
                # Same 0–1 → 0–100 conversion
                converted = val * 100 if val <= 1.0 else val
                return round(converted, 2)
        except (TypeError, ValueError):
            pass

    return None


def _build_card(
    row:         pd.Series,
    variable:    str,
    decade:      str,
    pct:         float,
    years_asked: str,
    chosen_nums: set[float],
) -> dict | None:
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return None

    # Question text: prefer human-reviewed, fall back to generated
    q_human = str(row.get("Question_text_human_review", "")).strip()
    q_gen   = str(row.get("question_text_generated", "")).strip()
    question = q_human if (q_human and q_human.lower() not in ("nan", "none")) else q_gen

    # value_labels — kept as raw string for the modal; game.js already knows how to parse it
    value_labels = _clean_str(row.get("value_labels"))

    # Chosen response labels as a clean JSON-serialisable list of ints
    chosen_list = sorted(int(n) if n == int(n) else n for n in chosen_nums)

    return {
        # ── Core game fields ──────────────────────────────────────────────────
        "id":              f"{variable}_{decade}",
        "variable":        variable,
        "decade":          decade,
        "question":        question,
        "pct":             pct,

        # ── "More info" modal fields ──────────────────────────────────────────
        "question_text_verbatim": _clean_str(row.get("question_text")),   # full GSS survey wording
        "value_labels":           value_labels,                           # "[1] yes / [2] no / ..."
        "chosen_response_nums":   chosen_list,                            # [1] or [1, 2]
        "years_in_decade":        years_asked,                            # "1972, 1974, 1976"

        # ── Metadata ──────────────────────────────────────────────────────────
        "description":     _clean_str(row.get("description")),
        "norc_url":        _clean_str(row.get("norc_url")),
        "subjects":        _clean_str(row.get("subjects")),
        "module":          _clean_str(row.get("module")),
        "risk_tier":       _clean_str(row.get("risk_tier")),
        "pipeline_route":  _clean_str(row.get("pipeline_route")),
    }


def _clean_str(val) -> str | None:
    """Return a clean string, or None if blank/NaN."""
    s = str(val).strip() if val is not None else ""
    return None if s.lower() in ("", "nan", "none") else s


def _is_number(v) -> bool:
    try:
        float(str(v))
        return True
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    main()
