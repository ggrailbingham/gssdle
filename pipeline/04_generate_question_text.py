# generate_question_text.py
import pandas as pd
import pyreadstat
import requests
import json
import time
import os

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    raise ValueError("ANTHROPIC_API_KEY environment variable not set!")

# ── Load data ─────────────────────────────────────────────────────────────────
df = pd.read_csv("game_cards_exploded.csv")
_, meta = pyreadstat.read_dta("gss.dta", metadataonly=True, encoding='latin1')

SKIP_KEYS = {'d','i','j','m','n','p','r','s','u','x','y','z'}

def get_clean_labels(var):
    labels = meta.variable_value_labels.get(var, {})
    return {
        k: v for k, v in labels.items()
        if k not in SKIP_KEYS and isinstance(k, (int, float))
    }

df_vars = df.drop_duplicates(subset='variable')[
    ['variable','description','pos_label','neg_label']
].copy()

print(f"Unique variables to generate text for: {len(df_vars)}")

def generate_question_text(variable, description, pos_label, neg_label, response_labels):
    options_str = ", ".join([f"{v}" for v in response_labels.values()])

    prompt = f"""You are writing question cards for a web game about American public opinion \
called "GSSdle". Players see a question and guess what percentage of Americans \
answered it a certain way, based on the General Social Survey (a large academic \
survey conducted since 1972).

Given this GSS survey variable, write a clean game card.

Variable name: {variable}
Short description: {description}
All valid response options: {options_str}
The answer we show % for: "{pos_label}"
The alternative answer: "{neg_label}"

Rules:
- "question": A clear, natural question, ideally 12-15 words. Always start with "What % of Americans \
surveyed...". Be specific enough that the question is unambiguous. Use the \
response options to understand exactly what was asked. For example if options \
are "self-employed / someone else" clarify it means current employment. If \
options are "yes/no" to "ever worked" clarify it means ever, not currently.
- "stat_label": 4-8 words, no "What %", just the plain fact. \
e.g. "Favor death penalty for murder" or "Have gun at home"
- "category": One of exactly these: Politics, Crime & Law, Religion, Family, \
Work, Education, Health, Sex & Relationships, Race & Equality, Civil Liberties, Social Trust
- "confidence": Integer 1-3 where:
    1 = Clear and confident. Question wording is unambiguous.
    2 = Somewhat confident but question could be interpreted multiple ways, \
or the variable description is vague.
    3 = Low confidence. Needs human review — e.g. unclear universe, \
ambiguous wording, question meaning changed over time, or stat is not \
interesting/meaningful as a game card.
- "review_note": If confidence is 2 or 3, write a SHORT note (max 15 words) \
explaining what a human reviewer should check. Empty string if confidence is 1.

Return ONLY a JSON object with keys: question, stat_label, category, confidence, review_note. \
No markdown, no explanation."""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01"
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=30
    )

    if response.status_code != 200:
        raise ValueError(f"API error {response.status_code}: {response.text}")

    data = response.json()
    text = data['content'][0]['text'].strip()
    text = text.replace('```json','').replace('```','').strip()
    return json.loads(text)

# ── Resume from checkpoint if it exists ──────────────────────────────────────
CHECKPOINT_FILE = "question_text_v2_checkpoint.csv"

if os.path.exists(CHECKPOINT_FILE):
    df_done = pd.read_csv(CHECKPOINT_FILE)
    done_vars = set(df_done['variable'].tolist())
    print(f"Resuming from checkpoint — {len(done_vars)} already done")
    results = df_done.to_dict('records')
else:
    df_done = pd.DataFrame()
    done_vars = set()
    results = []

errors = []
df_todo = df_vars[~df_vars['variable'].isin(done_vars)]
print(f"Remaining: {len(df_todo)} variables")

# ── Main loop ─────────────────────────────────────────────────────────────────
for i, row in df_todo.iterrows():
    response_labels = get_clean_labels(row['variable'])
    try:
        result = generate_question_text(
            row['variable'],
            row['description'],
            row['pos_label'],
            row['neg_label'],
            response_labels
        )
        result['variable'] = row['variable']
        results.append(result)
        print(f"  ✓ {row['variable']}: {result['question']}")

        if len(results) % 25 == 0:
            pd.DataFrame(results).to_csv(CHECKPOINT_FILE, index=False)
            print(f"  💾 Checkpoint saved — {len(results)}/{len(df_vars)} done")

        time.sleep(0.25)

    except Exception as e:
        print(f"  ERROR on {row['variable']}: {e}")
        errors.append({'variable': row['variable'], 'error': str(e)})
        time.sleep(1)

# ── Final save ────────────────────────────────────────────────────────────────
pd.DataFrame(results).to_csv(CHECKPOINT_FILE, index=False)
print(f"\nDone! Generated: {len(results)}  Errors: {len(errors)}")
if errors:
    pd.DataFrame(errors).to_csv("generation_errors.csv", index=False)
    print(f"Errors saved to generation_errors.csv")

# ── Merge onto cards ──────────────────────────────────────────────────────────
df_text  = pd.read_csv(CHECKPOINT_FILE)
df_cards = pd.read_csv("game_cards_exploded.csv")
df_final = df_cards.merge(
    df_text[['variable','question','stat_label','category','confidence','review_note']],
    on='variable', how='left'
)
df_final.to_csv("game_cards_with_text.csv", index=False)
print(f"✅ Saved game_cards_with_text.csv ({len(df_final)} cards)")