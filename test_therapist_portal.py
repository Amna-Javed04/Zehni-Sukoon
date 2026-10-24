"""Deterministic tests for the Therapist Portal.

Run with:  python test_therapist_portal.py

Covers the portal's privacy and security contract:
  (a) a patient cannot call therapist endpoints
  (b) an unverified therapist gets 403
  (c) therapist A cannot access therapist B's patient (403)
  (d) access disappears right after the patient revokes the link
  (e) guests (no JWT) cannot link
  (f) therapist responses never contain chat content
  (g) signup can never create an admin (patient or therapist path)
  (h) a duplicate active link is rejected
plus the consent gate (consent flag required) and invalid-code handling.

Uses an isolated temporary SQLite database — it never touches the dev DB.
"""
import json
import os
import sys
import tempfile
import zlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

# ── Isolated temp DB: patch config BEFORE create_app reads it ──────────
_tmpdir = tempfile.mkdtemp(prefix="zs_therapist_test_")
_db_uri = "sqlite:///" + os.path.join(_tmpdir, "therapist_test.db")

import backend.config as cfg  # noqa: E402
for _cls in cfg.config.values():
    if hasattr(_cls, "SQLALCHEMY_DATABASE_URI"):
        _cls.SQLALCHEMY_DATABASE_URI = _db_uri

from backend.app import create_app  # noqa: E402
from backend.models import db, User, Screening, TherapistPatientLink  # noqa: E402
from backend.routes.auth import _generate_token  # noqa: E402

app = create_app()
FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(name)
    print(f"  [{status}] {name}{('  -> ' + str(detail)) if detail and not cond else ''}")


# ── DB helpers ─────────────────────────────────────────────────────────
def reset_db():
    with app.app_context():
        db.session.remove()
        Screening.query.delete()
        TherapistPatientLink.query.delete()
        User.query.delete()
        db.session.commit()


def make_user(email, role="patient", is_admin=False, is_verified=False,
              name=None, invite_code=None):
    with app.app_context():
        u = User(
            email=email, role=role, is_admin=is_admin, is_verified=is_verified,
            display_name=name, invite_code=invite_code,
        )
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        return u.id


def make_screening(user_id, answers=None, score=12, severity="Moderate",
                   atype="phq9", at=None):
    with app.app_context():
        s = Screening(
            user_id=user_id,
            assessment_type=atype,
            answers=answers if answers is not None
            else {f"q{i}": (1 if i < 9 else 0) for i in range(1, 10)},
            age_group="26-35",
            gender="Female",
            total_score=score,
            severity=severity,
            language="en",
        )
        s.created_at = at if at is not None else datetime.now(timezone.utc)
        db.session.add(s)
        db.session.commit()
        return s.id


def token_for(user_id, is_admin=False):
    with app.app_context():
        return _generate_token(user_id, is_admin)


def auth_headers(user_id, is_admin=False):
    return {"Authorization": f"Bearer {token_for(user_id, is_admin)}"}


def api(method, path, user_id=None, is_admin=False, json_body=None):
    with app.test_client() as c:
        headers = auth_headers(user_id, is_admin) if user_id else {}
        r = c.open(path, method=method, headers=headers, json=json_body)
    return r.status_code, r.get_json(silent=True) or {}


def link_patient(therapist_id, patient_id, code):
    """Directly create an active link (used to set up scenarios quickly)."""
    with app.app_context():
        link = TherapistPatientLink(
            therapist_id=therapist_id, patient_id=patient_id,
            status="active", consented_at=datetime.now(timezone.utc),
        )
        db.session.add(link)
        db.session.commit()
        return link.id


print("=" * 74)
print("Setup: one verified therapist, one patient with screenings")
reset_db()
ther_a = make_user("ther-a@test.local", role="therapist", is_verified=True,
                   name="Dr A", invite_code="AAA111")
ther_b = make_user("ther-b@test.local", role="therapist", is_verified=True,
                   name="Dr B", invite_code="BBB222")
ther_pending = make_user("ther-p@test.local", role="therapist", is_verified=False,
                         name="Dr Pending", invite_code="PPP333")
admin = make_user("admin@test.local", is_admin=True, name="Admin")
patient = make_user("pat@test.local", name="Amna")
make_screening(patient, answers={f"q{i}": 2 for i in range(1, 10)}, score=18,
               severity="Moderately Severe")
link_patient(ther_b, patient, "BBB222")

print("=" * 74)
print("(a) A patient must NOT be able to call therapist endpoints")
code, d = api("GET", "/api/therapist/patients", user_id=patient)
check("patient GET /therapist/patients -> 403", code == 403, code)
code, d = api("GET", "/api/therapist/invite-code", user_id=patient)
check("patient GET /therapist/invite-code -> 403", code == 403, code)
code, d = api("GET", "/api/therapist/patients/1/screenings", user_id=patient)
check("patient GET patient screenings -> 403", code == 403, code)
code, d = api("GET", "/api/therapist/patients")
check("no token at all -> 401", code == 401, code)
code, d = api("GET", "/api/therapist/patients", user_id=admin, is_admin=True)
check("admin is not a therapist -> 403", code == 403, code)

print("=" * 74)
print("(b) An UNVERIFIED therapist gets 403 on every therapist endpoint")
for path in ("/api/therapist/invite-code", "/api/therapist/patients",
             "/api/therapist/patients/%d/screenings" % patient):
    code, d = api("GET", path, user_id=ther_pending)
    check(f"unverified therapist {path} -> 403", code == 403, code)

print("=" * 74)
print("(c) Therapist A cannot access therapist B's patient")
code, d = api("GET", "/api/therapist/patients", user_id=ther_a)
check("A's patient list is empty", d.get("total") == 0 and d.get("patients") == [], d)
code, d = api("GET", f"/api/therapist/patients/{patient}/screenings", user_id=ther_a)
check("A reading B's patient -> 403", code == 403, code)
code, d = api("GET", "/api/therapist/patients/999999/screenings", user_id=ther_a)
check("non-existent patient -> 403 (same response, no existence leak)", code == 403, code)

print("=" * 74)
print("(d) Access disappears immediately after the patient revokes")
code, d = api("GET", f"/api/therapist/patients/{patient}/screenings", user_id=ther_b)
check("B can read patient while link is active", code == 200, code)
code, d = api("GET", "/api/therapist/patients", user_id=ther_b)
check("patient visible in B's list while active",
      code == 200 and d.get("total") == 1, d)

code, d = api("DELETE", "/api/patient/therapist/link", user_id=patient)
check("patient revoke -> 200", code == 200, code)

code, d = api("GET", f"/api/therapist/patients/{patient}/screenings", user_id=ther_b)
check("B read after revoke -> 403", code == 403, code)
code, d = api("GET", "/api/therapist/patients", user_id=ther_b)
check("patient gone from B's list after revoke",
      code == 200 and d.get("total") == 0, d)

print("=" * 74)
print("(e) Guests cannot link (registered patient accounts only)")
with app.test_client() as c:
    r = c.post("/api/patient/therapist/link",
               headers={"X-Guest-Session": "11111111-2222-3333-4444-555555555555"},
               json={"invite_code": "AAA111", "consent": True})
check("guest link attempt -> 401", r.status_code == 401, r.status_code)

print("=" * 74)
print("(f) Therapist responses NEVER contain chat content")
# (d) revoked B's link, so give A a fresh active link for these checks —
# and revoke it again below so (h) starts from a clean slate.
link_patient(ther_a, patient, "AAA111")
code, d = api("GET", "/api/therapist/patients", user_id=ther_a)
text = json.dumps(d).lower()
check("patients list has no chat-ish keys",
      not any(k in text for k in ('"transcript"', '"messages"', '"conversation"', '"companion"', '"chat"')), text[:200])
code, d = api("GET", f"/api/therapist/patients/{patient}/screenings", user_id=ther_a)
check("A reads patient screenings with active link", code == 200, code)
text = json.dumps(d).lower()
check("screenings response has no chat-ish keys",
      not any(k in text for k in ('"transcript"', '"messages"', '"conversation"', '"companion"', '"chat"')), text[:200])
allowed = {"patient", "screenings", "total", "trend", "analysis", "situation"}
check("screenings response keys are exactly the allowed set",
      set(d.keys()) <= allowed, sorted(d.keys()))
if d.get("screenings"):
    s_keys = set(d["screenings"][0].keys())
    check("per-screening keys carry no chat fields",
          not (s_keys & {"transcript", "messages", "conversation", "companion", "chat"}), sorted(s_keys))
# clean slate for (h): patient disconnects again
api("DELETE", "/api/patient/therapist/link", user_id=patient)

print("=" * 74)
print("(g) Signup can never create an admin")
code, d = api("POST", "/api/auth/signup",
              json_body={"email": "plain@test.local", "password": "password123",
                         "role": "admin", "is_admin": True})
check("patient signup accepted", code == 201, (code, d))
with app.app_context():
    u = User.query.filter_by(email="plain@test.local").first()
    check("patient signup: is_admin False, role patient",
          u is not None and u.is_admin is False and u.role == "patient",
          (u and (u.is_admin, u.role)))

code, d = api("POST", "/api/auth/signup-therapist",
              json_body={"name": "Dr Sneaky", "email": "sneaky@test.local",
                         "password": "password123", "license_number": "PMC-000",
                         "role": "admin", "is_admin": True, "is_verified": True})
check("therapist signup accepted", code == 201, (code, d))
with app.app_context():
    u = User.query.filter_by(email="sneaky@test.local").first()
    check("therapist signup: is_admin False, role therapist, unverified",
          u is not None and u.is_admin is False and u.role == "therapist"
          and u.is_verified is False, (u and (u.is_admin, u.role, u.is_verified)))
    check("therapist signup: got an invite code", bool(u.invite_code))
    sneaky_id = u.id
code, d = api("GET", "/api/therapist/patients", user_id=sneaky_id)
check("freshly signed-up therapist is blocked until verified -> 403",
      code == 403, code)

print("=" * 74)
print("(h) Duplicate active link is rejected + consent is enforced")
code, d = api("POST", "/api/patient/therapist/link", user_id=patient,
              json_body={"invite_code": "AAA111"})   # no consent flag
check("link without consent flag -> 400", code == 400, code)

code, d = api("POST", "/api/patient/therapist/link", user_id=patient,
              json_body={"invite_code": "ZZZZ99", "consent": True})
check("invalid code -> 404", code == 404, code)

code, d = api("POST", "/api/patient/therapist/link", user_id=patient,
              json_body={"invite_code": "PPP333", "consent": True})
check("unverified therapist's code -> 403", code == 403, code)

code, d = api("POST", "/api/patient/therapist/link", user_id=patient,
              json_body={"invite_code": "AAA111", "consent": True})
check("consented link -> 201", code == 201, (code, d))
code, d = api("GET", "/api/patient/therapist", user_id=patient)
check("patient sees linked therapist by name",
      code == 200 and d.get("link", {}).get("therapist_name") == "Dr A", d)

code, d = api("POST", "/api/patient/therapist/link", user_id=patient,
              json_body={"invite_code": "AAA111", "consent": True})
check("duplicate active link (same therapist) -> 409", code == 409, code)
code, d = api("POST", "/api/patient/therapist/link", user_id=patient,
              json_body={"invite_code": "BBB222", "consent": True})
check("second active therapist for same patient -> 409", code == 409, code)

print("=" * 74)
print("(i) New therapist shows in the admin pending list, vanishes after approval")
code, d = api("POST", "/api/auth/signup-therapist",
              json_body={"name": "Dr Fresh", "email": "fresh@test.local",
                         "password": "password123"})          # no license number
check("therapist signup WITHOUT license -> 400", code == 400, (code, d))

code, d = api("POST", "/api/auth/signup-therapist",
              json_body={"name": "Dr Fresh", "email": "fresh@test.local",
                         "password": "password123", "license_number": "PMC-4242"})
check("therapist signup WITH license -> 201", code == 201, (code, d))
with app.app_context():
    fresh_id = User.query.filter_by(email="fresh@test.local").first().id

code, d = api("GET", "/api/admin/therapists?status=pending", user_id=admin, is_admin=True)
rows = d.get("therapists") or []
fresh_row = next((t for t in rows if t.get("id") == fresh_id), None)
check("newly registered therapist appears in admin pending list",
      code == 200 and fresh_row is not None, d)
if fresh_row:
    check("pending row shows name, email and license number",
          fresh_row.get("name") == "Dr Fresh"
          and fresh_row.get("email") == "fresh@test.local"
          and fresh_row.get("license_number") == "PMC-4242", fresh_row)
    check("pending row exposes account metadata only",
          not (set(fresh_row.keys()) & {"patients", "answers", "screenings", "score"}),
          sorted(fresh_row.keys()))

code, d = api("POST", f"/api/admin/therapists/{fresh_id}/verify",
              user_id=admin, is_admin=True)
check("admin approves -> 200", code == 200, code)
code, d = api("GET", "/api/admin/therapists?status=pending", user_id=admin, is_admin=True)
check("approved therapist DISAPPEARS from pending list",
      all(t.get("id") != fresh_id for t in (d.get("therapists") or [])), d)
code, d = api("GET", "/api/admin/therapists?status=verified", user_id=admin, is_admin=True)
check("approved therapist now appears in verified list",
      any(t.get("id") == fresh_id for t in (d.get("therapists") or [])), d)

# An admin created before roles existed (is_admin=True, role defaults to
# 'patient') must still pass every admin-only check.
legacy = make_user("legacy-admin@test.local", is_admin=True)
code, d = api("GET", "/api/admin/therapists?status=pending", user_id=legacy, is_admin=True)
check("legacy is_admin user still passes the admin check", code == 200, code)
code, d = api("GET", "/api/therapist/patients", user_id=legacy, is_admin=True)
check("legacy admin is still not a therapist -> 403", code == 403, code)

print("=" * 74)
print("Bonus: admin verify/reject flow + patient visibility after link")
code, d = api("GET", "/api/admin/therapists?status=pending", user_id=admin, is_admin=True)
check("admin sees pending therapists", code == 200 and d.get("pending_count", 0) >= 1, d)
code, d = api("POST", f"/api/admin/therapists/{ther_pending}/verify",
              user_id=admin, is_admin=True)
check("admin verify -> 200", code == 200, code)
code, d = api("GET", "/api/therapist/invite-code", user_id=ther_pending)
check("verified therapist can now fetch invite code", code == 200 and d.get("invite_code"), d)
code, d = api("DELETE", f"/api/admin/therapists/{ther_pending}",
              user_id=admin, is_admin=True)
check("admin reject (no links) -> 200", code == 200, code)
code, d = api("GET", "/api/therapist/patients", user_id=ther_pending)
check("rejected therapist's token is now invalid -> 401/403", code in (401, 403), code)

print("=" * 74)
print("Bonus: therapist patient list payload shape (name, age, gender, crisis)")
code, d = api("GET", "/api/therapist/patients", user_id=ther_a)
p = (d.get("patients") or [None])[0]
check("list has exactly one linked patient", p is not None, d)
if p:
    check("list row exposes allowed fields only",
          set(p.keys()) <= {"patient_id", "name", "age_range", "gender", "language",
                            "screening_count", "latest_date", "latest_score",
                            "latest_type", "latest_severity", "crisis", "consented_at"},
          sorted(p.keys()))
    check("crisis indicator present", p.get("crisis") is True, p)

print("=" * 74)
print("(j) PDF export: own history only, active-link gate, never chat content")


def pdf_searchable(data: bytes) -> bytes:
    """Raw bytes plus decoded streams, so text assertions work regardless of
    reportlab's compression (it chains ASCII85Decode + FlateDecode)."""
    import base64
    parts = [data]
    idx = 0

    def _decode(raw):
        try:
            return zlib.decompress(raw)
        except Exception:
            pass
        try:  # ASCII85 (reportlab a85enc output ends with '~>') then Flate
            a = raw.strip()
            if a.endswith(b"~>"):
                a = a[:-2]
            return zlib.decompress(base64.a85decode(a))
        except Exception:
            return None

    while True:
        s = data.find(b"stream", idx)
        if s == -1:
            break
        e = data.find(b"endstream", s)
        if e == -1:
            break
        chunk = data[s + 6:e].strip(b"\r\n")
        decoded = _decode(chunk)
        if decoded is not None:
            parts.append(decoded)
        idx = e + len(b"endstream")
    return b"\n".join(parts)


# A second patient, so cross-patient checks have a target.
patient_two = make_user("pat2@test.local", name="Two Patient")
make_screening(patient_two, score=9, severity="Moderate")

with app.test_client() as c:
    r = c.get("/api/screening/export-pdf")
check("guest PDF download -> 401", r.status_code == 401, r.status_code)

with app.test_client() as c:
    r = c.get("/api/screening/export-pdf", headers=auth_headers(patient))
own = r.get_data()
check("patient own PDF -> 200 application/pdf",
      r.status_code == 200 and r.mimetype == "application/pdf" and own[:4] == b"%PDF",
      (r.status_code, r.mimetype, own[:8]))
check("PDF sets attachment + no-store",
      "attachment" in r.headers.get("Content-Disposition", "")
      and "no-store" in r.headers.get("Cache-Control", ""),
      (r.headers.get("Content-Disposition"), r.headers.get("Cache-Control")))

own_text = pdf_searchable(own)
check("PDF contains patient name", b"Amna" in own_text)
check("PDF contains instrument + score data", b"PHQ-9" in own_text and b"18" in own_text)
check("PDF contains the diagnosis disclaimer",
      b"not a diagnosis" in own_text)
check("PDF contains the trend summary section", b"Trend summary" in own_text)
check("own PDF never contains ANOTHER patient's data",
      b"Two Patient" not in own_text)
check("PDF contains no chat text",
      not any(w in own_text.lower() for w in
              (b"transcript", b"humdum", b"companion", b"conversation")))

# A patient cannot reach the therapist export route for anyone else's data.
code, d = api("GET", f"/api/therapist/patients/{patient_two}/export-pdf",
              user_id=patient)
check("patient cannot export another patient's PDF -> 403", code == 403, code)

# An unlinked therapist gets the same 403 as for a non-existent patient.
code, d = api("GET", f"/api/therapist/patients/{patient_two}/export-pdf",
              user_id=ther_a)
check("unlinked therapist PDF -> 403", code == 403, code)
code, d = api("GET", "/api/therapist/patients/999999/export-pdf", user_id=ther_a)
check("non-existent patient -> 403 (same response)", code == 403, code)

# Linked therapist (ther_a <-> patient, active since (h)) can download.
with app.test_client() as c:
    r = c.get(f"/api/therapist/patients/{patient}/export-pdf",
              headers=auth_headers(ther_a))
linked_pdf = r.get_data()
check("linked therapist PDF -> 200 %PDF",
      r.status_code == 200 and linked_pdf[:4] == b"%PDF",
      (r.status_code, r.mimetype))
check("therapist PDF says who it was prepared for",
      b"Dr A" in pdf_searchable(linked_pdf))

# Revoked link blocks the PDF immediately (fresh pair).
code, d = api("POST", "/api/patient/therapist/link", user_id=patient_two,
              json_body={"invite_code": "BBB222", "consent": True})
check("patient_two links ther_b -> 201", code == 201, (code, d))
with app.test_client() as c:
    r = c.get(f"/api/therapist/patients/{patient_two}/export-pdf",
              headers=auth_headers(ther_b))
check("active link PDF -> 200", r.status_code == 200, r.status_code)
api("DELETE", "/api/patient/therapist/link", user_id=patient_two)
code, d = api("GET", f"/api/therapist/patients/{patient_two}/export-pdf",
              user_id=ther_b)
check("revoked link blocks the PDF -> 403", code == 403, code)

print("=" * 74)
print("(k) Triage ordering: crisis first, then severity, then recency")
# NOTE: PHQ-9 q9 > 0 IS a crisis signal, so the severe patient's screening
# deliberately keeps q9 low - otherwise BOTH would be crisis-flagged and
# severity would (correctly) break the tie instead of the crisis flag.
now = datetime.now(timezone.utc)
tri_crisis = make_user("tri-crisis@test.local", name="Crisis Case")
make_screening(tri_crisis,
               answers={f"q{i}": (2 if i == 9 else 1) for i in range(1, 10)},
               score=10, severity="Moderate", at=now)
tri_severe = make_user("tri-severe@test.local", name="Severe Case")
make_screening(tri_severe,
               answers={f"q{i}": (0 if i == 9 else 3) for i in range(1, 10)},
               score=24, severity="Severe", at=now)
# Equal severity, different recency: the more recent must come first.
tri_mild_new = make_user("tri-mild-new@test.local", name="Mild New")
make_screening(tri_mild_new, score=8, severity="Mild",
               at=now - timedelta(hours=1))
tri_mild_old = make_user("tri-mild-old@test.local", name="Mild Old")
make_screening(tri_mild_old, score=2, severity="Minimal",
               at=now - timedelta(days=7))
# Link in scrambled order - the server must impose the triage order itself.
for pid in (tri_mild_old, tri_severe, tri_mild_new, tri_crisis):
    link_patient(ther_b, pid, "BBB222")
code, d = api("GET", "/api/therapist/patients", user_id=ther_b)
names = [x.get("name") for x in d.get("patients", [])]
check("crisis patient sorts first", names[:1] == ["Crisis Case"], names)
check("Severe before Mild",
      "Severe Case" in names and "Mild New" in names
      and names.index("Severe Case") < names.index("Mild New"), names)
check("recency breaks ties (Mild New before Mild Old)",
      "Mild New" in names and "Mild Old" in names
      and names.index("Mild New") < names.index("Mild Old"), names)
check("triage rows keep only allowed fields",
      set((d.get("patients") or [{}])[0].keys())
      <= {"patient_id", "name", "age_range", "gender", "language",
          "screening_count", "latest_date", "latest_score", "latest_type",
          "latest_severity", "crisis", "consented_at"},
      sorted((d.get("patients") or [{}])[0].keys()))

print("=" * 74)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALL CHECKS PASSED")
