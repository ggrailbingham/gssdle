# GSSdle

A daily ranking game built on data from the **General Social Survey (GSS)** — one of the longest-running and most comprehensive surveys of American public opinion, conducted by NORC at the University of Chicago since 1972.

Each day, players are shown 8 survey statistics and must rank them from least to most common among Americans surveyed. How well do you know what America thinks?

**Play at:** [gssdle.vercel.app](https://gssdle.vercel.app)

---

## How to Play

- Each card shows a survey question and the decade it was asked
- Drag each card to its correct position on the timeline, ordered from **least common** (left) to **most common** (right)
- After each placement, the actual percentage is revealed
- **Scoring:** Card N is worth N points, minus one point for each wrong attempt (floor 0). Maximum score is 28 points across 7 cards (the first card is placed for free)
- A new puzzle is available every day at midnight Pacific time

---

## Data Source

All statistics come from the **General Social Survey (GSS)**, a project of the independent research organization NORC at the University of Chicago, with principal funding from the National Science Foundation.

> Smith, Tom W., Davern, Michael, Freese, Jeremy, and Morgan, Stephen L., *General Social Surveys, 1972-2022* [machine-readable data file]. Principal Investigator, Tom W. Smith; Co-Principal Investigators, Michael Davern, Jeremy Freese, and Stephen L. Morgan; Sponsored by National Science Foundation. --NORC ed.-- Chicago: NORC, 2023.

The GSS data file (`gss.dta`) is **not included in this repository** and must be downloaded directly from [NORC](https://gss.norc.org/get-the-data). This project uses the cumulative cross-sectional dataset.

---

## Repository Structure

```
gssdle/
│
├── README.md                           # this file
│
├── pipeline/                           # data transformation scripts
│   ├── 01_build_binary_dataset.py      # identify binary yes/no variables from GSS
│   ├── 02_compute_weighted_pct.py      # compute weighted % by decade
│   ├── 03_prepare_game_cards.py        # clean, flip, and explode cards by decade
│   ├── 04_generate_question_text.py    # LLM pass 1: generate question text
│   ├── 05_audit_interpretability.py    # LLM pass 2: flag misleading or unclear cards
│   └── 06_export_game_json.py          # export final cards.json for the game
│
├── review_tool/
│   └── card_review.html                # browser-based UI for manual card curation
│
├── scripts/
│   ├── generate_schedule.py            # generate 30-day candidate schedule
│   └── approve_schedule.py            # convert approved schedule to schedule.js
│
└── game/                               # the playable game (static site)
    ├── index.html
    ├── css/style.css
    ├── js/
    │   ├── game.js                     # all game logic
    │   └── schedule.js                 # daily card sets
    └── data/
        └── cards.json                  # full card deck (~1,900 cards)
```

---

## Pipeline Overview

The data pipeline transforms the raw GSS dataset into game-ready cards in six steps. To reproduce it, you will need the GSS cumulative dataset (`gss.dta`) and Python 3.10+ with the dependencies listed below.

### Step 1 — Identify binary variables (`01_build_binary_dataset.py`)

Scans all ~6,900 variables in the GSS and identifies those that are binary in practice: the top two response codes account for 90%+ of valid responses, with at least 1,000 valid responses and a minority answer of at least 5%. Letter-coded missing values (`i`, `d`, `n`, etc.) and negative numeric codes are excluded.

**Output:** `gss_binary_candidates.parquet`

### Step 2 — Compute weighted percentages (`02_compute_weighted_pct.py`)

For each binary variable, computes the weighted percentage of respondents giving the "positive" answer — overall and broken down by decade (1970s through 2020s). Uses `wtssall` for pre-2021 waves and `wtssnrps` for 2021 onwards. Requires at least 200 responses per decade to report a decade figure. Also computes a trend score (most recent decade minus earliest).

**Output:** `game_cards_final.csv`

### Step 3 — Prepare game cards (`03_prepare_game_cards.py`)

Cleans the dataset by removing admin and coding variables, auto-flips variables so the percentage always reflects the more interesting or "positive" answer, and explodes the data into one row per variable per decade. Each row is a playable game card.

**Output:** `game_cards_exploded.csv` (~2,481 cards)

### Step 4 — Generate question text (`04_generate_question_text.py`)

Uses the Claude API (Haiku model) to generate human-readable question text for each unique variable. The prompt includes the variable name, short GSS description, response option labels, and the positive/negative answer pair. Also generates a stat label, category, confidence score (1–3), and a review note for low-confidence cards.

Runs once per unique variable (~1,200 API calls, ~$0.30 at Haiku pricing). Checkpoints every 25 calls to allow resuming if interrupted.

**Requires:** `ANTHROPIC_API_KEY` environment variable  
**Output:** `game_cards_with_text.csv`

### Step 5 — Audit interpretability (`05_audit_interpretability.py`)

A second Claude API pass that reviews each card for interpretability problems: conditional questions (only asked to a subgroup), underspecified questions (missing context), wrong question text (AI hallucination), admin variables, and questions too niche for a general audience. Also runs a Python-based flip error detector. Produces an `action` recommendation (keep, reframe, remove) and a reframed question where fixable.

**Requires:** `ANTHROPIC_API_KEY` environment variable  
**Output:** `audit_results.csv`

### Step 6 — Export game JSON (`06_export_game_json.py`)

Merges audit results onto cards, applies decisions from the manual review tool, and exports the final game-ready JSON. Excludes removed cards. Stores percentages as 0–100 values.

**Output:** `game/data/cards.json`

---

## Manual Review

Between steps 5 and 6, cards are reviewed manually using the browser-based review tool at `review_tool/card_review.html`. Open it in any browser and load `game_cards_with_text.csv` (after merging audit results using `pre_review_prep.py`).

The tool shows each card with its AI-generated question text, the audit recommendation, and the decade breakdown. Actions available: approve as-is, edit question text or category, or remove. Exports a reviewed CSV that feeds into step 6.

---

## Scheduling

Daily card sets are managed in two steps:

```bash
# Generate 30 candidate days (cards at least 2% apart)
python scripts/generate_schedule.py

# Review candidate_schedule.csv — mark 'yes' in the approved column
# Then convert approved days to schedule.js
python scripts/approve_schedule.py
```

To publish new schedules, commit the updated `game/js/schedule.js` and push to GitHub. Vercel redeploys automatically.

---

## Running Locally

```bash
cd game
python -m http.server 8000
# Open http://localhost:8000
```

The game requires a local server (not `file://`) because it fetches `cards.json` via a relative URL.

---

## Dependencies

**Python:**
```
pandas
pyreadstat
pyarrow
requests
```

Install with:
```bash
pip install pandas pyreadstat pyarrow requests
```

**API:**  
Question generation and audit steps require an Anthropic API key. Set it as an environment variable:
```bash
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Mac/Linux
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Notes and Known Limitations

- **Conditional questions:** Some GSS variables are only asked to a subgroup of respondents (e.g. only gun owners, only married people). The audit pass flags many of these, but some may remain. The question text for these cards attempts to make the condition explicit.
- **Weighted percentages:** Figures use survey weights (`wtssall`/`wtssnrps`) to approximate population-level estimates. The GSS uses a split-ballot design, so not all questions are asked to all respondents in a given year.
- **Decade coverage:** Some variables were only asked in certain years. Decade figures are only shown when at least 200 valid weighted responses exist for that period.
- **Question text:** AI-generated question text has been manually reviewed but may not perfectly match the original GSS question wording. The original GSS codebook is the authoritative source.

---

## Future Plans

- Extended variable pass covering ordinal, multinomial, and continuous GSS variables (~5,700 additional candidates)
- Full question text integration using the `gssrdoc` R package
- Score distribution comparison (what % of players scored higher than you)
- R + gssrdoc integration for universe conditions and original question wording

---

## License

Game code: MIT License  
GSS data: subject to [NORC terms of use](https://gss.norc.org/get-the-data)
