# audit_interpretability.py
import pandas as pd
import pyreadstat
import requests
import json
import time
import os

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    raise ValueError("ANTHROPIC_API_KEY environment variable not set!")

_, meta = pyreadstat.read_dta("gss.dta", metadataonly=True, encoding='latin1')

SKIP_KEYS = {'d','i','j','m','n','p','r','s','u','x','y','z'}

def get_clean_labels(var):
    labels = meta.variable_value_labels.get(var, {})
    return {k: v for k, v in labels.items()
            if k not in SKIP_KEYS and isinstance(k, (int, float))}

# ── Load variables ────────────────────────────────────────────────────────────
df_cards = pd.read_csv("game_cards_with_text.csv")
df_vars  = df_cards.drop_duplicates(subset='variable')[
    ['variable','description','question','stat_label',
     'pos_label','neg_label','pos_pct','confidence','review_note']
].copy()

# ── Python flip error detection (no model needed) ─────────────────────────────
NEGATIVE_LABELS = {'no','oppose','disagree','false','should not be legal',
                   'not allowed','not remove','disapprove','against','someone else'}
POSITIVE_LABELS = {'yes','favor','agree','true','should be legal',
                   'allowed','approve','for','self-employed'}

def detect_flip_error(row):
    label = str(row['pos_label']).strip().lower()
    pct   = float(row['pos_pct']) if row['pos_pct'] else 0.5
    # Positive label but very low % — likely flipped
    if label in POSITIVE_LABELS and pct < 0.05:
        return True, f"pos_label '{row['pos_label']}' but pct is only {pct:.1%}"
    # Negative label but very high % — likely flipped
    if label in NEGATIVE_LABELS and pct > 0.90:
        return True, f"pos_label '{row['pos_label']}' but pct is {pct:.1%}"
    return False, ''

df_vars[['flip_error','flip_note']] = df_vars.apply(
    lambda r: pd.Series(detect_flip_error(r)), axis=1
)

flip_errors = df_vars[df_vars['flip_error']]
print(f"Flip errors detected by Python: {len(flip_errors)}")
if len(flip_errors):
    print(flip_errors[['variable','pos_label','pos_pct','flip_note']].to_string(index=False))

# ── Claude interpretability audit ────────────────────────────────────────────
AUDIT_CHECKPOINT = "audit_interpretability_checkpoint.csv"

if os.path.exists(AUDIT_CHECKPOINT):
    df_done = pd.read_csv(AUDIT_CHECKPOINT)
    done_vars = set(df_done['variable'].tolist())
    results = df_done.to_dict('records')
    print(f"\nResuming — {len(done_vars)} already done")
else:
    done_vars = set()
    results = []

errors  = []
df_todo = df_vars[~df_vars['variable'].isin(done_vars)]
print(f"Total to audit: {len(df_vars)}  Remaining: {len(df_todo)}\n")

def audit_variable(variable, description, question, pos_label, neg_label,
                   response_labels, confidence, review_note):
    options_str = ", ".join([str(v) for v in response_labels.values()])

    prompt = f"""You are a quality reviewer for "GSSdle", a web game where players guess 
what % of Americans surveyed answered a question a certain way.

A card is GOOD if a player reading the question would correctly understand 
what the statistic measures, without needing any extra context.

A card is BAD if any of these are true:
- The question is conditional on a prior answer or subgroup, and the question 
  text doesn't make that clear (e.g. a question only asked to gun owners, 
  only asked to people who answered yes to a prior question, only asked to 
  married people, only asked to immigrants, etc.)
- The question is too vague to be meaningful without more context
  (e.g. "answered correctly on probability test 1" — which probability question?)
- The AI-generated question text is clearly wrong or doesn't match the variable
- The card is an internal survey/admin variable, not a real survey question
- The question is so niche that it's not interesting as a "% of Americans" stat

Variable: {variable}
Description: {description}
Current question text: {question}
Response options: {options_str}
Positive answer shown: "{pos_label}"
Alternative answer: "{neg_label}"
AI confidence score: {confidence}
AI review note: {review_note}

Reason step by step:
1. What does this variable actually measure?
2. Would a player reading the question text correctly understand that?
3. If not — what is the specific problem, and is it fixable with a rewrite?

Return ONLY a JSON object with these fields:
- "interpretable": true if card is good as-is, false if there is a problem
- "problem": if interpretable=false, one of:
    "conditional"        — only asked to a subgroup, player would misread universe
    "underspecified"     — not enough context to know what was actually asked
    "wrong_question_text"— AI generated incorrect or hallucinated question text
    "admin_variable"     — internal survey variable, not a real question
    "too_niche"          — too specific to a rare experience to be interesting
    "other"              — some other interpretability problem
  Empty string if interpretable=true.
- "problem_detail": max 15 words describing the specific issue. 
  Empty string if interpretable=true.
- "action": 
    "keep_as_is" — card is good, player would understand it correctly
    "reframe"    — problem is fixable with a rewrite
    "remove"     — not fixable, or not interesting as a game card
- "reframed_question": if action=reframe, rewrite starting with 
  "What % of Americans surveyed..." in 12-15 words that correctly conveys 
  what the statistic measures including any necessary context.
  Empty string otherwise.

No markdown, no explanation, JSON only."""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01"
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 400,
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

# ── Main loop ─────────────────────────────────────────────────────────────────
for _, row in df_todo.iterrows():
    response_labels = get_clean_labels(row['variable'])
    try:
        result = audit_variable(
            row['variable'],
            row['description'],
            row['question'],
            row['pos_label'],
            row['neg_label'],
            response_labels,
            row.get('confidence', ''),
            row.get('review_note', '')
        )
        result['variable']    = row['variable']
        result['description'] = row['description']
        result['question']    = row['question']
        result['flip_error']  = row['flip_error']
        result['flip_note']   = row['flip_note']
        results.append(result)

        action  = result.get('action','?')
        problem = result.get('problem','')
        marker  = '🔴' if action=='remove' else '🟡' if action=='reframe' else '✓'
        print(f"  {marker} {row['variable']:<20} {action:<12} {problem}")

        if len(results) % 25 == 0:
            pd.DataFrame(results).to_csv(AUDIT_CHECKPOINT, index=False)
            print(f"  💾 Checkpoint — {len(results)}/{len(df_vars)} done")

        time.sleep(0.25)

    except Exception as e:
        print(f"  ERROR on {row['variable']}: {e}")
        errors.append({'variable': row['variable'], 'error': str(e)})
        time.sleep(1)

# ── Final save ────────────────────────────────────────────────────────────────
pd.DataFrame(results).to_csv(AUDIT_CHECKPOINT, index=False)
if errors:
    pd.DataFrame(errors).to_csv("audit_errors.csv", index=False)
    print(f"\n{len(errors)} errors saved to audit_errors.csv")

# ── Summary ───────────────────────────────────────────────────────────────────
df_audit = pd.read_csv(AUDIT_CHECKPOINT)

print(f"\n{'='*60}")
print("AUDIT SUMMARY")
print(f"{'='*60}")
print(f"Total audited: {len(df_audit)}")
print(f"\nAction distribution:")
print(df_audit['action'].value_counts().to_string())
print(f"\nProblem types:")
print(df_audit[df_audit['problem']!='']['problem'].value_counts().to_string())
print(f"\nFlip errors (Python-detected): {df_audit['flip_error'].sum()}")

print(f"\n{'='*60}")
print("REMOVE")
print(f"{'='*60}")
removes = df_audit[df_audit['action']=='remove']
print(removes[['variable','problem','problem_detail']].to_string(index=False))

print(f"\n{'='*60}")
print("REFRAME")
print(f"{'='*60}")
reframes = df_audit[df_audit['action']=='reframe']
print(reframes[['variable','problem','reframed_question']].to_string(index=False))

print(f"\n{'='*60}")
print("FLIP ERRORS")
print(f"{'='*60}")
flips = df_audit[df_audit['flip_error']==True]
print(flips[['variable','description','flip_note']].to_string(index=False))

df_audit.to_csv("audit_results.csv", index=False)
print(f"\n✅ Saved audit_results.csv")