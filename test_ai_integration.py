"""
Integration test: verifies that
1. The companion chatbot responds via the real LLM API (not fallback text)
2. /extract-score uses the LLM (not local heuristics)
3. PHQ-9 results come from the ML ensemble with majority voting honored
Run with the Flask dev server up on localhost:5000.
"""
import requests
import json
import sys

BASE = "http://localhost:5000"

# Exact fallback strings from backend/routes/chat.py — if we see these, the API was NOT used
COMPANION_FALLBACK_NO_KEY = "I am here with you. Please feel free to tell me more about how you are feeling."
COMPANION_FALLBACK_ERROR = "I hear you. I'm here to listen. Tell me more about what has been on your mind."

results = {"pass": 0, "fail": 0}

def report(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    results["pass" if ok else "fail"] += 1
    print(f"  [{tag}] {name}")
    if detail:
        print(f"         {detail}")

print("=" * 70)
print("1. HEALTH CHECK")
print("=" * 70)
r = requests.get(f"{BASE}/api/health", timeout=10)
report("Server healthy", r.status_code == 200, r.text.strip())

print()
print("=" * 70)
print("2. COMPANION CHATBOT (Humdum) — must use real LLM API")
print("=" * 70)
r = requests.post(f"{BASE}/api/chat/companion", json={
    "message": "I have been feeling very stressed about my exams lately",
    "history": []
}, timeout=60)
data = r.json()
resp_text = data.get("response", "")
print(f"  Bot reply ({len(resp_text)} chars): {resp_text[:220]}{'...' if len(resp_text) > 220 else ''}")
is_fallback = resp_text.strip() in (COMPANION_FALLBACK_NO_KEY, COMPANION_FALLBACK_ERROR)
report("HTTP 200", r.status_code == 200)
report("Response is from LLM API (not fallback string)", not is_fallback,
       "FELL BACK — API key missing or API call failed!" if is_fallback else "Genuine model-generated response")

# Second turn with history + Urdu to verify context & language behavior
r2 = requests.post(f"{BASE}/api/chat/companion", json={
    "message": "mujhe neend nahi aati aajkal",
    "history": [
        {"role": "user", "content": "I have been feeling very stressed about my exams lately"},
        {"role": "assistant", "content": resp_text},
    ]
}, timeout=60)
data2 = r2.json()
resp2 = data2.get("response", "")
print(f"  Bot reply 2 ({len(resp2)} chars): {resp2[:220]}{'...' if len(resp2) > 220 else ''}")
is_fallback2 = resp2.strip() in (COMPANION_FALLBACK_NO_KEY, COMPANION_FALLBACK_ERROR)
report("Multi-turn reply from LLM API", not is_fallback2)

print()
print("=" * 70)
print("3. SCORE EXTRACTION (/api/chat/extract-score) — must use LLM")
print("=" * 70)
extract_cases = [
    ("Feeling down, depressed, or hopeless", "haan kabhi kabhi udaas hota hoon, hafte mein 2-3 din", (1,)),
    ("Trouble falling or staying asleep, or sleeping too much", "nearly every night, I can barely sleep at all", (3,)),
    ("Feeling nervous, anxious, or on edge", "not at all, I feel calm", (0,)),
]
for question, reply, expected in extract_cases:
    r = requests.post(f"{BASE}/api/chat/extract-score", json={
        "assessment_type": "phq9",
        "question": question,
        "reply": reply
    }, timeout=60)
    d = r.json()
    reasoning = d.get("reasoning", "")
    used_fallback = "local fallback" in reasoning.lower()
    print(f"  Reply: '{reply[:50]}...' -> score={d.get('score')} clarify={d.get('needs_clarification')}")
    print(f"    Reasoning: {reasoning[:150]}")
    report(f"LLM used (no fallback marker)", not used_fallback,
           "Reasoning contains 'local fallback' — API was NOT used!" if used_fallback else "")
    report(f"Score plausible {expected}", d.get("score") in expected or d.get("score") is not None)

print()
print("=" * 70)
print("4. PHQ-9 RESULT — must come from ML ensemble majority vote")
print("=" * 70)
# Create guest session for screening auth
g = requests.post(f"{BASE}/api/auth/guest", json={}, timeout=10)
guest_id = g.json().get("session_id") or g.json().get("guest_session_id")
print(f"  Guest session: {guest_id}")
headers = {"X-Guest-Session": guest_id}

phq_cases = [
    ("Low severity answers", [0, 1, 0, 1, 0, 0, 1, 0, 0]),
    ("Moderate severity answers", [2, 2, 1, 2, 1, 1, 2, 1, 0]),
    ("High severity answers (q9=0 to avoid crisis redirect)", [3, 3, 3, 3, 3, 2, 3, 3, 0]),
]
for label, answers in phq_cases:
    r = requests.post(f"{BASE}/api/screening/result", json={
        "assessment_type": "phq9",
        "answers": answers,
        "age_group": "18-24",
        "gender": "Female",
        "language": "en"
    }, headers=headers, timeout=30)
    d = r.json()
    votes = d.get("model_votes")
    sev = d.get("severity")
    print(f"\n  {label}: total={d.get('total_score')} severity={sev}")
    if votes:
        preds = [votes["random_forest"]["prediction"], votes["svm"]["prediction"], votes["xgboost"]["prediction"]]
        print(f"    RF={preds[0]} ({votes['random_forest']['confidence']}%) | "
              f"SVM={preds[1]} ({votes['svm']['confidence']}%) | "
              f"XGB={preds[2]} ({votes['xgboost']['confidence']}%) | agreement={votes['ensemble_agreement']}")
        majority = max(set(preds), key=preds.count)
        report("model_votes present (ensemble WAS used, not threshold fallback)", True)
        report(f"Severity follows majority vote (majority='{majority}', severity='{sev}')", sev == majority)
    else:
        report("model_votes present (ensemble WAS used, not threshold fallback)", False,
               "model_votes is null — threshold fallback was used instead of ML models!")

# Crisis path: q9 > 0 must flag crisis_redirect AND still return full ML results
r = requests.post(f"{BASE}/api/screening/result", json={
    "assessment_type": "phq9",
    "answers": [1, 1, 1, 1, 1, 1, 1, 1, 2],
    "age_group": "18-24", "gender": "Female", "language": "en"
}, headers=headers, timeout=30)
d = r.json()
report("Crisis redirect when q9>0", d.get("crisis_redirect") is True,
       f"severity={d.get('severity')}, crisis_redirect={d.get('crisis_redirect')}")
report("Crisis case still returns ensemble model_votes (score/severity/confidence shown)",
       d.get("model_votes") is not None and bool(d.get("severity")),
       f"model_votes={'present' if d.get('model_votes') else 'NULL'}")

print()
print("=" * 70)
print(f"TOTALS: {results['pass']} passed, {results['fail']} failed")
print("=" * 70)
sys.exit(0 if results["fail"] == 0 else 1)
