# export_game_json.py
import pandas as pd
import json

df = pd.read_csv("game_cards_reviewed.csv")

# ── Filter: exclude removed cards only ───────────────────────────────────────
removed = df[df['review_status'] == 'removed']['variable'].unique()
df = df[~df['variable'].isin(removed)]
print(f"After removing rejected cards: {df['variable'].nunique()} unique variables")

# ── Filter: exclude decade-cards with no valid pct ────────────────────────────
df = df[df['pos_pct'].notna()]
df = df[df['pos_pct'] != '']

# ── Build one card per variable+decade row ────────────────────────────────────
DECADES = ['1970s','1980s','1990s','2000s','2010s','2020s']

cards = []
for _, row in df.iterrows():
    # Skip if no question text
    if not row.get('question') or str(row['question']).strip() == '':
        continue

    pct = float(row['pos_pct'])

    card = {
        "id":          f"{row['variable']}_{row['decade']}",
        "variable":    row['variable'],
        "decade":      row['decade'],
        "question":    str(row['question']).strip(),
        "stat_label":  str(row['stat_label']).strip(),
        "category":    str(row['category']).strip(),
        "pct":         round(pct * 100, 1),   # store as 0-100 not 0-1
        "pos_label":   str(row['pos_label']).strip(),
        "neg_label":   str(row['neg_label']).strip(),
        "n_valid":     int(row['n_valid']) if pd.notna(row['n_valid']) else 0,
        "year_min":    int(row['year_min']) if pd.notna(row['year_min']) else 0,
        "year_max":    int(row['year_max']) if pd.notna(row['year_max']) else 0,
    }
    cards.append(card)

print(f"Total game cards: {len(cards)}")

# ── Sanity check ──────────────────────────────────────────────────────────────
df_cards = pd.DataFrame(cards)
print(f"\nCards per decade:")
print(df_cards['decade'].value_counts().sort_index().to_string())
print(f"\nCards per category:")
print(df_cards['category'].value_counts().sort_index().to_string())
print(f"\n% distribution:")
print(df_cards['pct'].describe().round(1).to_string())
print(f"\nSample cards:")
print(df_cards[['id','question','pct','category']].sample(8).to_string(index=False))

# ── Save ──────────────────────────────────────────────────────────────────────
with open("game/data/cards.json", "w") as f:
    json.dump(cards, f, indent=2)

print(f"\n✅ Saved game/data/cards.json ({len(cards)} cards)")