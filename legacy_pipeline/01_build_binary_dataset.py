# 01_build_binary_dataset.py
#
# Scans all variables in the GSS cumulative dataset and identifies those
# that are binary in practice: the top two response codes account for 90%+
# of valid responses, with at least 1,000 valid responses and a minority
# answer of at least 5%.
#
# Also merges the correct survey weights for 2021+ waves.
#
# Input:  gss.dta  (GSS cumulative dataset — download from https://gss.norc.org)
# Output: gss_binary_candidates.parquet

import pyreadstat
import pandas as pd
import os

# ── Config ────────────────────────────────────────────────────────────────────
DTA_FILE    = "gss.dta"
OUTPUT_FILE = "gss_binary_candidates.parquet"
BATCH_DIR   = "batches"
ENCODING    = "latin1"
BATCH_SIZE  = 300       # columns per batch — conservative to avoid memory errors
THRESHOLD   = 0.90      # top 2 codes must cover 90%+ of valid responses
MIN_N       = 1000      # minimum valid responses
MIN_MINOR   = 0.05      # minority answer must be at least 5%

# These columns are always loaded regardless of binary detection
ALWAYS_KEEP = ['year', 'id', 'wtssall']

# GSS letter-coded missing values — present across all variables
SKIP_VALS = {'d', 'i', 'j', 'm', 'n', 'p', 'r', 's', 'u', 'x', 'y', 'z'}

os.makedirs(BATCH_DIR, exist_ok=True)

# ── Step 1: Load metadata ─────────────────────────────────────────────────────
print("Loading metadata...")
_, meta = pyreadstat.read_dta(DTA_FILE, metadataonly=True, encoding=ENCODING)
all_cols = meta.column_names
print(f"Total variables in .dta: {len(all_cols)}")

scan_cols = [c for c in all_cols if c not in ALWAYS_KEEP]
batches   = [scan_cols[i:i+BATCH_SIZE] for i in range(0, len(scan_cols), BATCH_SIZE)]
print(f"Scanning {len(scan_cols)} variables in {len(batches)} batches of {BATCH_SIZE}")

# ── Step 2: Batch scan — identify binary variables ────────────────────────────
binary_vars = []
skipped     = 0

for batch_num, batch in enumerate(batches):
    print(f"\nBatch {batch_num+1}/{len(batches)} — loading {len(batch)} columns...", end=" ")

    try:
        df_batch, _ = pyreadstat.read_dta(
            DTA_FILE,
            usecols=ALWAYS_KEEP + batch,
            encoding=ENCODING
        )
    except Exception as e:
        print(f"ERROR: {e} — skipping batch")
        skipped += len(batch)
        continue

    for var in batch:
        if var not in df_batch.columns:
            continue

        col = df_batch[var].dropna()
        col = col[~col.isin(SKIP_VALS)]
        if pd.api.types.is_numeric_dtype(col):
            col = col[col >= 0]

        if len(col) < MIN_N:
            continue

        top2 = col.value_counts(normalize=True).head(2)
        if len(top2) < 2:
            continue
        if top2.sum() < THRESHOLD:
            continue
        if top2.iloc[1] < MIN_MINOR:
            continue

        binary_vars.append(var)

    print(f"→ running total: {len(binary_vars)} binary vars")

print(f"\n{'='*60}")
print(f"Binary variables found: {len(binary_vars)}")
print(f"Skipped due to batch errors: {skipped}")

# ── Step 3: Load final dataset with binary columns only ───────────────────────
print(f"\nLoading final dataset ({len(binary_vars)} binary columns)...")

final_batches = [binary_vars[i:i+BATCH_SIZE] for i in range(0, len(binary_vars), BATCH_SIZE)]
batch_files   = []

for i, batch in enumerate(final_batches):
    path = os.path.join(BATCH_DIR, f"final_batch_{i}.parquet")
    print(f"  Final batch {i+1}/{len(final_batches)}...", end=" ")
    df_b, _ = pyreadstat.read_dta(
        DTA_FILE,
        usecols=ALWAYS_KEEP + batch,
        encoding=ENCODING
    )
    df_b.to_parquet(path, index=False)
    batch_files.append(path)
    print(f"saved {df_b.shape}")

# ── Step 4: Merge batches ─────────────────────────────────────────────────────
print("\nMerging batches...")
dfs = [pd.read_parquet(p) for p in batch_files]
df_final = pd.concat(
    [dfs[0]] + [d.drop(columns=ALWAYS_KEEP, errors='ignore') for d in dfs[1:]],
    axis=1
)
print(f"Merged shape: {df_final.shape}")

# ── Step 5: Fix weights for 2021+ waves ───────────────────────────────────────
# GSS switched from wtssall to wtssnrps/wtssps for 2021 onwards
print("\nFixing weights for 2021+ waves...")
df_wt, _ = pyreadstat.read_dta(
    DTA_FILE,
    usecols=['id', 'year', 'wtssall', 'wtssnrps', 'wtssps'],
    encoding=ENCODING
)

# Build combined weight: wtssall where available, then wtssnrps, then wtssps
df_wt['weight'] = df_wt['wtssall']
if 'wtssnrps' in df_wt.columns:
    df_wt['weight'] = df_wt['weight'].fillna(df_wt['wtssnrps'])
if 'wtssps' in df_wt.columns:
    df_wt['weight'] = df_wt['weight'].fillna(df_wt['wtssps'])

print("Weight coverage by year (recent):")
print(df_wt[df_wt['year'] >= 2016].groupby('year')['weight'].agg(
    n_valid=lambda x: (x > 0).sum(),
    n_null=lambda x: x.isna().sum()
).to_string())

# Merge combined weight back, replacing old wtssall
df_final = df_final.drop(columns=['wtssall'], errors='ignore')
df_final = df_final.merge(
    df_wt[['id', 'year', 'weight']].rename(columns={'weight': 'wtssall'}),
    on=['id', 'year'],
    how='left'
)

# ── Step 6: Save ──────────────────────────────────────────────────────────────
df_final.to_parquet(OUTPUT_FILE, index=False)
print(f"\n✅ Saved {OUTPUT_FILE}")
print(f"   Shape: {df_final.shape}")
print(f"   Years: {int(df_final['year'].min())} – {int(df_final['year'].max())}")
print(f"   Weight null rate 2021+: {df_final[df_final['year']>=2021]['wtssall'].isna().mean():.1%}")
