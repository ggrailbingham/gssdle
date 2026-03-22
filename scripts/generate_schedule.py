# generate_schedule.py
# Generates candidate daily card sets for GSSdle
# Output: candidate_schedule.csv — review this, then run approve_schedule.py

import pandas as pd
import json
import random
from datetime import date, timedelta
from itertools import combinations

# ── Config ────────────────────────────────────────────────────────────────────
CARDS_FILE   = "game/data/cards.json"
OUTPUT_CSV   = "candidate_schedule.csv"
DAYS_AHEAD   = 30        # generate this many days
CARDS_PER_DAY = 8
MIN_GAP      = 2.0       # minimum % difference between any two cards
SEED         = 42        # for reproducibility

# ── Load cards ────────────────────────────────────────────────────────────────
with open(CARDS_FILE) as f:
    all_cards = json.load(f)

df = pd.DataFrame(all_cards)
print(f"Total cards available: {len(df)}")
print(f"% range: {df['pct'].min():.1f}% – {df['pct'].max():.1f}%")

# ── Helper: check if a set of cards is valid ──────────────────────────────────
def is_valid_set(cards):
    pcts = sorted([c['pct'] for c in cards])
    for i in range(len(pcts) - 1):
        if pcts[i+1] - pcts[i] < MIN_GAP:
            return False
    return True

# ── Generate candidate sets ───────────────────────────────────────────────────
random.seed(SEED)
start_date = date.today() + timedelta(days=1)  # start from tomorrow

rows = []
used_ids = set()  # track used card IDs to avoid repeats across days

for day_offset in range(DAYS_AHEAD):
    target_date = start_date + timedelta(days=day_offset)
    
    # Try to build a valid set
    # Strategy: pick from different categories for variety
    candidates = df[~df['id'].isin(used_ids)].to_dict('records')
    
    if len(candidates) < CARDS_PER_DAY:
        # Reset used pool if running low
        candidates = df.to_dict('records')
        used_ids = set()
    
    # Shuffle and try to pick a valid set
    random.shuffle(candidates)
    best_set = None
    
    for attempt in range(1000):
        random.shuffle(candidates)
        picked = candidates[:CARDS_PER_DAY]
        if is_valid_set(picked):
            best_set = picked
            break
    
    if not best_set:
        # Fallback: pick greedily by spreading across % range
        sorted_cards = sorted(candidates, key=lambda x: x['pct'])
        best_set = []
        for card in sorted_cards:
            if len(best_set) >= CARDS_PER_DAY:
                break
            if all(abs(card['pct'] - c['pct']) >= MIN_GAP for c in best_set):
                best_set.append(card)

    # Sort by pct for display in CSV
    best_set = sorted(best_set, key=lambda x: x['pct'])
    
    for c in best_set:
        used_ids.add(c['id'])
    
    # Build row for CSV
    row = {
        'date':     target_date.isoformat(),
        'approved': '',   # you fill this in: 'yes' or 'no'
        'notes':    '',   # your notes
    }
    for i, card in enumerate(best_set):
        row[f'card_{i+1}_id']       = card['id']
        row[f'card_{i+1}_question'] = card['question']
        row[f'card_{i+1}_pct']      = f"{card['pct']:.1f}%"
        row[f'card_{i+1}_category'] = card['category']
        row[f'card_{i+1}_decade']   = card['decade']
    
    rows.append(row)

df_out = pd.DataFrame(rows)
df_out.to_csv(OUTPUT_CSV, index=False)

print(f"\n✅ Generated {len(rows)} candidate days")
print(f"📋 Review {OUTPUT_CSV}")
print(f"   Fill in 'approved' column with 'yes' for each day you approve")
print(f"   Then run: python approve_schedule.py")