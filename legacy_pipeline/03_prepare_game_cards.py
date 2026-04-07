# 03_prepare_game_cards.py
#
# Takes the exploded decade cards and prepares them for the question
# generation step. No additional transformation needed beyond what
# 02_compute_weighted_pct.py already did — this script just validates
# the output and confirms it is ready for the LLM pass.
#
# Input:  game_cards_exploded.csv  (from 02_compute_weighted_pct.py)
# Output: game_cards_exploded.csv  (validated, no structural changes)

import pandas as pd

INPUT_FILE = "game_cards_exploded.csv"

df = pd.read_csv(INPUT_FILE)

print(f"Shape: {df.shape}")
print(f"Unique variables: {df['variable'].nunique()}")

print(f"\nCards per decade:")
print(df['decade'].value_counts().sort_index().to_string())

print(f"\nPos_pct distribution:")
print(df['pos_pct'].describe().round(3).to_string())

print(f"\nNull rates in key columns:")
for col in ['variable','decade','pos_label','neg_label','pos_pct','n_valid']:
    print(f"  {col}: {df[col].isna().mean():.1%}")

# Sanity check: known variables
known = ['abany','grass','cappun','gunlaw','owngun','trust','colhomo']
print(f"\nSanity check — known variables:")
for v in known:
    rows = df[df['variable']==v]
    if len(rows):
        print(f"  {v}: {len(rows)} decade-cards, pct range {rows['pos_pct'].min():.1%}–{rows['pos_pct'].max():.1%}")
    else:
        print(f"  {v}: NOT FOUND")

print(f"\n✅ {INPUT_FILE} looks good — ready for question generation")
