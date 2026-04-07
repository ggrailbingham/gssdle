# GSSdle Card Generation Pipeline

Generates GSSdle question cards from the R-extracted GSS dataset using Claude Haiku.

## Files

```
run_pipeline.py      — Main entrypoint
router.py            — Routes each variable to the correct generator (no API calls)
generators.py        — Calls Haiku to generate question text per variable type
reviewer.py          — Batched Haiku reviewer audits each generated card
prompts.py           — All system prompts (edit here to tune output quality)
haiku_client.py      — Anthropic API wrapper with retry logic
export.py            — Writes the review CSV for the GUI
explode_decades.py   — Post-review: explodes to one row per variable × decade
requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Workflow

### Step 1 — Dry run (check routing, no API calls)
```bash
python run_pipeline.py \
  --input gss_filtered_extract.csv \
  --output review_cards.csv \
  --dry-run
```
Outputs `review_cards.routing_debug.csv` — inspect the `pipeline_route` column.

### Step 2 — Full generation + review pass
```bash
python run_pipeline.py \
  --input gss_filtered_extract.csv \
  --output review_cards.csv
```
Outputs `review_cards.csv` sorted with flagged cards first.

### Step 3 — Human review
Load `review_cards.csv` into the review GUI.

Key new columns added to the GUI:
- `question_text` — the original GSS question text (for verification)
- `norc_url` — link to the GSS variable page at NORC
- `suggested_fix` — reviewer agent's suggested edit
- `flag_reason` — plain-English reason for flagging

### Step 4 — Decade explosion (after review sign-off)
Save your approved rows back to a CSV (e.g. `review_cards_approved.csv`)
with the `human_review` column set to False for approved rows, then:

```bash
python explode_decades.py \
  --input review_cards_approved.csv \
  --output game/data/cards.json
```

This generates one card entry per variable × decade (plus an "overall" entry),
replacing `game/data/cards.json`.

## Variable Routing Logic

| Route | Trigger | Generator |
|---|---|---|
| `binary` | var_type_guess=binary | Picks positive/affirming response |
| `binary_other` | var_type_guess=binary_other | Haiku sub-classifies, then applies relevant rules |
| `ordinal` | var_type_guess=ordinal or ordinal_multi | Detects scale type, combines top 2 positive |
| `multinomial` | var_type_guess=multinomial | Picks most interpretable response(s) |
| `unknown_skip` | var_type_guess=unknown | Skipped; flagged for human review |

## Conditional Risk Handling

- **HIGH risk**: Generator rewrites question as "Among Americans who [condition], % who..."
  Reviewer checks the reframe. If reviewer agrees → auto-approved. If disagrees → flagged.
- **MEDIUM/LOW risk**: Standard question generation; no special handling.

## Review CSV Flag Priority

| Condition | human_review |
|---|---|
| edit_type = HIGH_EDIT | True |
| confidence < 0.70 | True |
| HIGH risk + reviewer disagrees with reframe | True |
| Generation or reviewer failed | True |
| All other cases | False |

## Output Format (cards.json)

Each entry:
```json
{
  "variable": "grass",
  "question": "% of Americans who think marijuana USE should be LEGAL",
  "pct": 52.3,
  "decade": "2010s",
  "chosen_response": "yes",
  "description": "Should marijuana be made legal",
  "norc_url": "https://gssdataexplorer.norc.org/variables/285/vshow",
  "subjects": "...",
  "module": "...",
  "risk_tier": "LOW",
  "var_type": "binary",
  "pipeline_route": "binary"
}
```

`pct` is always stored as 0–100, not 0–1.

## Future Work (noted in spec)

- Module-themed card sets: query by `module` column in the review CSV
- Cross-sectional breakdowns (by race, gender, income): will require additional
  R extraction of weighted subgroup percentages before this pipeline runs