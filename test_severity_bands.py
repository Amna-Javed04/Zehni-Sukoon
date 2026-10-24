"""Deterministic tests for the band-based severity scoring.

Run with:  python test_severity_bands.py

Severity comes ONLY from the standard validated clinical score bands:

  PHQ-9  0-4 minimal · 5-9 mild · 10-14 moderate ·
         15-19 moderately severe · 20-27 severe
  GAD-7  0-4 minimal · 5-9 mild · 10-14 moderate · 15-21 severe

The ML ensemble (Random Forest / XGBoost / SVM) has been removed along with
its model files, so these tests also prove that POST /api/screening/result
works with no *.pkl present and that the response carries no per-model fields.

Uses an isolated temporary SQLite database — it never touches the dev DB.
"""
import glob
import os
import sys
import tempfile
import uuid

sys.path.insert(0, ".")

# ── Isolated temp DB: patch config BEFORE create_app reads it ──────────
_tmpdir = tempfile.mkdtemp(prefix="zs_severity_test_")
_db_uri = "sqlite:///" + os.path.join(_tmpdir, "severity_test.db")

import backend.config as cfg  # noqa: E402
for _cls in cfg.config.values():
    if hasattr(_cls, "SQLALCHEMY_DATABASE_URI"):
        _cls.SQLALCHEMY_DATABASE_URI = _db_uri

from backend.app import create_app  # noqa: E402
from backend.models import db, GuestSession  # noqa: E402

app = create_app()
FAILURES = []

# Fields the ML ensemble used to return — none may appear now.
ML_FIELDS = ("model_votes", "random_forest", "xgboost", "svm",
             "ensemble_agreement", "confidence")


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(name)
    print(f"  [{status}] {name}{('  -> ' + str(detail)) if detail and not cond else ''}")


def guest_headers():
    """A fresh anonymous guest session, used for /api/screening/result auth."""
    session_id = str(uuid.uuid4())
    with app.app_context():
        db.session.add(GuestSession(session_id=session_id))
        db.session.commit()
    return {"X-Guest-Session": session_id}


def post_result(answers, assessment_type="phq9", headers=None, **extra):
    body = {"assessment_type": assessment_type, "answers": answers,
            "age_group": "25-34", "gender": "Female", "language": "en"}
    body.update(extra)
    with app.test_client() as c:
        r = c.post("/api/screening/result", json=body, headers=headers or guest_headers())
    return r.status_code, r.get_json(silent=True) or {}


def build_answers(total, n_items, q9_zero=False):
    """n_items scores of 0-3 summing exactly to total (optionally forcing q9=0)."""
    scores = []
    remaining = total
    limit = n_items - 1 if q9_zero else n_items
    for i in range(n_items):
        if i < limit and remaining > 0:
            take = min(3, remaining)
            scores.append(take)
            remaining -= take
        else:
            scores.append(0)
    assert sum(scores) == total, (total, scores)
    return scores


def phq9_band(total):
    if total >= 20: return "Severe"
    if total >= 15: return "Moderately Severe"
    if total >= 10: return "Moderate"
    if total >= 5:  return "Mild"
    return "Minimal"


def gad7_band(total):
    if total >= 15: return "Severe"
    if total >= 10: return "Moderate"
    if total >= 5:  return "Mild"
    return "Minimal"


# ── 1. PHQ-9: every total 0-27 maps to the validated band ──────────────
print("=" * 74)
print("1. PHQ-9 severity band for EVERY total 0-27")
print("=" * 74)
bad = []
for total in range(0, 28):
    # Keep q9 at 0 while the total still fits in q1..q8 (0-24), so the crisis
    # rule never interferes with the band assertion; 25-27 require q9 > 0.
    answers = build_answers(total, 9, q9_zero=total <= 24)
    code, d = post_result(answers)
    expected = phq9_band(total)
    if code != 200 or d.get("total_score") != total or d.get("severity") != expected:
        bad.append((total, code, d.get("total_score"), d.get("severity"), expected))
check(f"all 28 PHQ-9 totals map to the correct band", not bad, bad)
check("minimal exists as a category (total 0 -> 'Minimal')",
      post_result(build_answers(0, 9))[1].get("severity") == "Minimal")
# spot-check the band boundaries explicitly
for t, exp in [(4, "Minimal"), (5, "Mild"), (9, "Mild"), (10, "Moderate"),
               (14, "Moderate"), (15, "Moderately Severe"),
               (19, "Moderately Severe"), (20, "Severe"), (27, "Severe")]:
    got = post_result(build_answers(t, 9, q9_zero=t <= 24))[1].get("severity")
    check(f"PHQ-9 {t} -> {exp}", got == exp, got)

# ── 2. GAD-7 bands unchanged ──────────────────────────────────────────
print("\n" + "=" * 74)
print("2. GAD-7 severity bands unchanged (0-4/5-9/10-14/15-21)")
print("=" * 74)
bad = []
for total in range(0, 22):
    code, d = post_result(build_answers(total, 7), assessment_type="gad7")
    expected = gad7_band(total)
    if code != 200 or d.get("total_score") != total or d.get("severity") != expected:
        bad.append((total, code, d.get("total_score"), d.get("severity"), expected))
check(f"all 22 GAD-7 totals map to the correct band", not bad, bad)

# ── 3. Crisis rule unchanged ──────────────────────────────────────────
print("\n" + "=" * 74)
print("3. Crisis rule: PHQ-9 item 9 > 0 sets crisis_redirect")
print("=" * 74)
_, d0 = post_result([1, 1, 1, 1, 1, 1, 1, 1, 0])
check("q9 = 0 -> crisis_redirect false", d0.get("crisis_redirect") is False, d0)
_, d1 = post_result([1, 1, 1, 1, 1, 1, 1, 1, 1])
check("q9 = 1 -> crisis_redirect true", d1.get("crisis_redirect") is True, d1)
_, d3 = post_result([0] * 8 + [3])
check("q9 = 3 -> crisis_redirect true", d3.get("crisis_redirect") is True, d3)
check("crisis still returns a score + severity (no short-circuit)",
      d3.get("total_score") == 3 and d3.get("severity") == "Minimal", d3)
# GAD-7 has no item 9 and never flags crisis
_, dg = post_result([3] * 7, assessment_type="gad7")
check("GAD-7 never flags crisis", dg.get("crisis_redirect") is False, dg)

# ── 4. Works with NO model files present ──────────────────────────────
print("\n" + "=" * 74)
print("4. Screening API works with no model files present")
print("=" * 74)
root = os.path.dirname(os.path.abspath(__file__))
pkl_at_root = [p for p in glob.glob(os.path.join(root, "*.pkl"))]
check("no *.pkl at repo root (artifacts live in ml_research/ only)", not pkl_at_root, pkl_at_root)
code, d = post_result([2, 2, 3, 2, 1, 2, 1, 0, 1])   # total 14
check("POST /api/screening/result -> 200 without models", code == 200, code)
check("total computed from answers", d.get("total_score") == 14, d.get("total_score"))
check("severity from bands (14 -> Moderate)", d.get("severity") == "Moderate", d.get("severity"))

# ── 5. Response carries NO per-model fields ───────────────────────────
print("\n" + "=" * 74)
print("5. Response contains no ML/per-model fields")
print("=" * 74)
_, d = post_result([2, 2, 3, 2, 1, 2, 1, 0, 1])
top_hits = [f for f in ML_FIELDS if f in d]
check("no ML fields at top level", not top_hits, top_hits)
blob = str(d).lower()
check("no model names anywhere in the payload",
      not any(name in blob for name in ("random_forest", "xgboost", "ensemble", "confidence")), d)
check("core fields still present",
      all(k in d for k in ("screening_id", "assessment_type", "total_score",
                           "severity", "crisis_redirect", "created_at")), sorted(d))

# ── 6. Validation still intact ────────────────────────────────────────
print("\n" + "=" * 74)
print("6. Existing validation unchanged")
print("=" * 74)
code, d = post_result([1, 2, 3])  # 3 of 9 items
check("missing items rejected (400)", code == 400, code)
check("missing items listed", d.get("missing_items") == ["q4", "q5", "q6", "q7", "q8", "q9"], d)
code, d = post_result([1, 1, 1, 1, 1, 1, 1, 1, 4])  # score out of 0-3
check("score outside 0-3 rejected (400)", code == 400, code)
code, d = post_result([1, 1, 1, 1, 1, 1, 1, 1, 1, 1])  # 10 items
check("extra item rejected (400)", code == 400, code)

# ── Summary ───────────────────────────────────────────────────────────
print("\n" + "=" * 74)
if FAILURES:
    print(f"{len(FAILURES)} SEVERITY TEST(S) FAILED: {FAILURES}")
    sys.exit(1)
print("ALL SEVERITY BAND TESTS PASSED")
sys.exit(0)
