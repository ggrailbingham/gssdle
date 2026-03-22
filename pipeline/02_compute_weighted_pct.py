# 02_compute_weighted_pct.py
#
# For each binary variable identified in step 1, computes:
#   - Weighted % for the "positive" answer overall and by decade
#   - Auto-flips variables so % always reflects the more interesting answer
#   - Removes admin/coding variables
#   - Computes a trend score (most recent - earliest decade)
#   - Explodes into one row per variable per decade
#
# Input:  gss_binary_candidates.parquet  (from 01_build_binary_dataset.py)
#         gss.dta                         (for metadata/labels)
# Output: game_cards_final.csv           (one row per variable, with decade columns)
#         game_cards_exploded.csv         (one row per variable per decade)

import pyreadstat
import pandas as pd
import numpy as np

# ── Config ────────────────────────────────────────────────────────────────────
PARQUET_FILE   = "gss_binary_candidates.parquet"
DTA_FILE       = "gss.dta"
OUTPUT_FINAL   = "game_cards_final.csv"
OUTPUT_EXPLODED= "game_cards_exploded.csv"
ENCODING       = "latin1"

THRESHOLD  = 0.90   # top 2 codes must cover 90%+ of valid responses
MIN_N      = 1000   # minimum overall valid responses
MIN_MINOR  = 0.05   # minority answer floor
MIN_N_DEC  = 200    # minimum responses to report a decade figure

DECADES = {
    '1970s': (1970, 1979),
    '1980s': (1980, 1989),
    '1990s': (1990, 1999),
    '2000s': (2000, 2009),
    '2010s': (2010, 2019),
    '2020s': (2020, 2029),
}

# Admin/coding variables to exclude — not real survey questions
ADMIN_VARS = [
    'form', 'vpsu', 'respnum', 'hefinfo', 'whoelse6',
    'famgen_7522', 'gender1', 'gender2', 'gender3',
    'gender4', 'gender5', 'gender6', 'gender7', 'gender8',
    'palive', 'palive1', 'formwt', 'oversamp', 'sampcode', 'sample',
    'random', 'adminconsent',
]

# Admin keyword filter for variable descriptions
ADMIN_KEYWORDS = [
    'coding', 'verbatim', 'status', 'tag', 'retrieved',
    'retrievable', 'imputed', 'allocation', 'assign', 'version',
    'weight', 'segment', 'ballot', 'mode', 'panel'
]

# Labels that indicate the "negative" answer — we flip these so % = positive
NEGATIVE_LABELS = {
    'no', 'oppose', 'disagree', 'not remove', 'not allowed',
    'should not be legal', 'against', 'disapprove', 'false',
    'someone else', 'private',
}

# GSS letter-coded missing values
SKIP_VALS = {'d', 'i', 'j', 'm', 'n', 'p', 'r', 's', 'u', 'x', 'y', 'z'}

# ── Load data + metadata ──────────────────────────────────────────────────────
print("Loading data and metadata...")
df   = pd.read_parquet(PARQUET_FILE)
_, meta = pyreadstat.read_dta(DTA_FILE, metadataonly=True, encoding=ENCODING)
print(f"Data shape: {df.shape}")

# ── Identify binary variables and their top-2 codes ──────────────────────────
print("\nIdentifying binary variables and top-2 codes...")

def get_top2(var):
    """Return (code_a, label_a, share_a, code_b, label_b, share_b) or None."""
    col = df[var].dropna()
    col = col[~col.isin(SKIP_VALS)]
    if pd.api.types.is_numeric_dtype(col):
        col = col[col >= 0]
    if len(col) < MIN_N:
        return None
    top2 = col.value_counts(normalize=True).head(2)
    if len(top2) < 2 or top2.sum() < THRESHOLD or top2.iloc[1] < MIN_MINOR:
        return None
    labels = meta.variable_value_labels.get(var, {})
    ca, cb = top2.index[0], top2.index[1]
    return (ca, labels.get(ca,'?'), top2.iloc[0],
            cb, labels.get(cb,'?'), top2.iloc[1])

scan_cols = [c for c in df.columns if c not in ('year','id','wtssall')]
records   = []

for var in scan_cols:
    result = get_top2(var)
    if not result:
        continue
    ca, la, sa, cb, lb, sb = result
    idx = meta.column_names.index(var) if var in meta.column_names else -1
    desc = meta.column_labels[idx] if idx >= 0 and meta.column_labels else ''

    # Skip admin variables
    if var in ADMIN_VARS:
        continue
    text = (var + ' ' + str(desc)).lower()
    if any(kw in text for kw in ADMIN_KEYWORDS):
        continue

    records.append({
        'variable':    var,
        'description': desc,
        'code_a':      ca,
        'label_a':     str(la),
        'share_a':     round(sa, 4),
        'code_b':      cb,
        'label_b':     str(lb),
        'share_b':     round(sb, 4),
    })

df_vars = pd.DataFrame(records)
print(f"Binary survey variables found: {len(df_vars)}")

# ── Auto-flip so pos_label = interesting/positive answer ─────────────────────
def flip_if_needed(row):
    label_a = str(row['label_a']).strip().lower()
    if label_a in NEGATIVE_LABELS:
        return pd.Series({
            'pos_label': row['label_b'],
            'pos_code':  row['code_b'],
            'neg_label': row['label_a'],
            'neg_code':  row['code_a'],
            'was_flipped': True,
        })
    return pd.Series({
        'pos_label': row['label_a'],
        'pos_code':  row['code_a'],
        'neg_label': row['label_b'],
        'neg_code':  row['code_b'],
        'was_flipped': False,
    })

flipped = df_vars.apply(flip_if_needed, axis=1)
df_vars = pd.concat([df_vars, flipped], axis=1)
print(f"Flipped {df_vars['was_flipped'].sum()} variables to positive framing")

# ── Weighted % calculation ────────────────────────────────────────────────────
def weighted_pct(sub, var, pos_code):
    """Weighted % for pos_code in sub."""
    w_total = sub['wtssall'].sum()
    if w_total == 0:
        return None
    return sub.loc[sub[var] == pos_code, 'wtssall'].sum() / w_total

print("\nComputing weighted percentages (overall + by decade)...")
results = []

for _, row in df_vars.iterrows():
    var      = row['variable']
    pos_code = row['pos_code']
    neg_code = row['neg_code']

    if var not in df.columns:
        continue

    # Clean subset: only valid binary responses
    sub = df[[var, 'wtssall', 'year']].copy()
    sub = sub[sub[var].notna() & ~sub[var].isin(SKIP_VALS)]
    if pd.api.types.is_numeric_dtype(df[var]):
        sub = sub[df.loc[sub.index, var] >= 0]
    sub = sub[sub[var].isin([pos_code, neg_code])]

    if len(sub) < MIN_N:
        continue

    pct_overall = weighted_pct(sub, var, pos_code)
    yr_min      = int(sub['year'].min())
    yr_max      = int(sub['year'].max())
    n_years     = sub['year'].nunique()

    record = {
        'variable':     var,
        'description':  row['description'],
        'pos_label':    row['pos_label'],
        'pos_code':     pos_code,
        'neg_label':    row['neg_label'],
        'neg_code':     neg_code,
        'was_flipped':  row['was_flipped'],
        'pct_overall':  round(pct_overall, 4) if pct_overall else None,
        'n_valid':      len(sub),
        'year_min':     yr_min,
        'year_max':     yr_max,
        'n_years':      n_years,
        'minority_share': min(row['share_a'], row['share_b']),
    }

    # Decade breakdowns
    for decade, (yr_lo, yr_hi) in DECADES.items():
        sub_dec = sub[(sub['year'] >= yr_lo) & (sub['year'] <= yr_hi)]
        n_dec   = len(sub_dec)
        if n_dec >= MIN_N_DEC:
            pct_dec = weighted_pct(sub_dec, var, pos_code)
            record[f'pct_{decade}'] = round(pct_dec, 4) if pct_dec else None
        else:
            record[f'pct_{decade}'] = None
        record[f'n_{decade}'] = n_dec

    results.append(record)

df_out = pd.DataFrame(results)

# Trend: most recent decade with data minus earliest decade with data
decade_cols = [f'pct_{d}' for d in DECADES]
def compute_trend(row):
    vals = [(d, row[f'pct_{d}']) for d in DECADES if pd.notna(row.get(f'pct_{d}'))]
    if len(vals) < 2:
        return None
    return round(vals[-1][1] - vals[0][1], 4)

df_out['trend'] = df_out.apply(compute_trend, axis=1)

df_out.to_csv(OUTPUT_FINAL, index=False)
print(f"\n✅ Saved {OUTPUT_FINAL} ({len(df_out)} variables)")

# ── Decade coverage summary ───────────────────────────────────────────────────
print("\nDecade coverage:")
for d in DECADES:
    n = df_out[f'pct_{d}'].notna().sum()
    print(f"  {d}: {n} variables")

print("\nBiggest attitude shifts (top 10 by absolute trend):")
df_trend = df_out.dropna(subset=['trend']).copy()
df_trend['abs_trend'] = df_trend['trend'].abs()
top = df_trend.nlargest(10, 'abs_trend')[['variable','description','trend'] + decade_cols]
print(top.to_string(index=False))

# ── Explode into one row per variable per decade ──────────────────────────────
print("\nExploding into decade cards...")
decade_rows = []

for _, row in df_out.iterrows():
    for decade in DECADES:
        pct = row.get(f'pct_{decade}')
        n   = row.get(f'n_{decade}', 0)
        if pd.isna(pct) or n < MIN_N_DEC:
            continue
        decade_rows.append({
            'variable':      row['variable'],
            'description':   row['description'],
            'decade':        decade,
            'pos_label':     row['pos_label'],
            'neg_label':     row['neg_label'],
            'pos_pct':       round(pct, 4),
            'n_valid':       int(n),
            'year_min':      row['year_min'],
            'year_max':      row['year_max'],
            'n_years':       row['n_years'],
            'trend':         row.get('trend'),
            'was_flipped':   row['was_flipped'],
            # Include all decade pct columns for context
            **{f'pos_pct_{d}': row.get(f'pct_{d}') for d in DECADES},
        })

df_exploded = pd.DataFrame(decade_rows)
df_exploded.to_csv(OUTPUT_EXPLODED, index=False)

print(f"✅ Saved {OUTPUT_EXPLODED} ({len(df_exploded)} decade-cards)")
print(f"\nCards per decade:")
print(df_exploded['decade'].value_counts().sort_index().to_string())
