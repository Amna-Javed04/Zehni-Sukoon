"""
Auth + dashboards integration test:
- signup (success, duplicate, weak password)
- login (success, wrong password, unknown email)
- role-based redirect hints
- admin stats API (401 anonymous / 403 non-admin / 200 admin with full data)
- page routes render
Run with the Flask dev server up on localhost:5000.
"""
import requests
import sqlite3
import time
import sys

BASE = "http://localhost:5000"
DB = "instance/zehni_test.db"

results = {"pass": 0, "fail": 0}

def report(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    results["pass" if ok else "fail"] += 1
    print(f"  [{tag}] {name}")
    if detail:
        print(f"         {detail}")

ts = int(time.time())
user_email = f"testuser_{ts}@example.com"
admin_email = f"testadmin_{ts}@example.com"
password = "SecurePass123"

print("=" * 70)
print("1. SIGN UP")
print("=" * 70)
r = requests.post(f"{BASE}/api/auth/signup", json={"email": user_email, "password": password}, timeout=10)
d = r.json()
report("New signup returns 201", r.status_code == 201, f"email={user_email}")
report("Signup returns token", bool(d.get("token")))
report("New user is_admin=False (no privilege escalation)", d.get("user", {}).get("is_admin") is False)
report("Signup redirect_to='home'", d.get("user", {}).get("redirect_to") == "home")
user_token = d.get("token")

r = requests.post(f"{BASE}/api/auth/signup", json={"email": user_email, "password": password}, timeout=10)
report("Duplicate email rejected with 409", r.status_code == 409, r.json().get("error", ""))

r = requests.post(f"{BASE}/api/auth/signup", json={"email": f"x_{ts}@example.com", "password": "short"}, timeout=10)
report("Weak password (<8 chars) rejected with 400", r.status_code == 400, r.json().get("error", ""))

r = requests.post(f"{BASE}/api/auth/signup", json={}, timeout=10)
report("Empty body rejected with 400", r.status_code == 400)

print()
print("=" * 70)
print("2. LOG IN")
print("=" * 70)
r = requests.post(f"{BASE}/api/auth/login", json={"email": user_email, "password": password}, timeout=10)
d = r.json()
report("Correct credentials return 200 + token", r.status_code == 200 and bool(d.get("token")))
report("Regular user redirect_to='home'", d.get("user", {}).get("redirect_to") == "home")
user_token = d.get("token") or user_token

r = requests.post(f"{BASE}/api/auth/login", json={"email": user_email, "password": "WrongPass999"}, timeout=10)
report("Wrong password rejected with 401", r.status_code == 401, r.json().get("error", ""))

r = requests.post(f"{BASE}/api/auth/login", json={"email": f"ghost_{ts}@example.com", "password": password}, timeout=10)
report("Unknown email rejected with 401", r.status_code == 401)

print()
print("=" * 70)
print("3. ADMIN ACCESS CONTROL")
print("=" * 70)
r = requests.get(f"{BASE}/api/admin/stats", timeout=10)
report("Anonymous /api/admin/stats rejected with 401", r.status_code == 401)

r = requests.get(f"{BASE}/api/admin/stats", headers={"Authorization": f"Bearer {user_token}"}, timeout=10)
report("Regular user /api/admin/stats rejected with 403", r.status_code == 403, r.json().get("error", ""))

# Create admin the sanctioned way: signup via API, then flip is_admin directly in DB
r = requests.post(f"{BASE}/api/auth/signup", json={"email": admin_email, "password": password}, timeout=10)
assert r.status_code == 201, f"admin signup failed: {r.text}"
con = sqlite3.connect(DB)
con.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (admin_email,))
con.commit()
con.close()
print(f"  (created {admin_email} and promoted via direct DB update, per app's admin policy)")

r = requests.post(f"{BASE}/api/auth/login", json={"email": admin_email, "password": password}, timeout=10)
d = r.json()
report("Admin login returns 200", r.status_code == 200)
report("Admin login redirect_to='admin' (role-based redirect)", d.get("user", {}).get("redirect_to") == "admin")
report("Admin flag in login payload", d.get("user", {}).get("is_admin") is True)
admin_token = d.get("token")

print()
print("=" * 70)
print("4. ADMIN DASHBOARD DATA (/api/admin/stats)")
print("=" * 70)
r = requests.get(f"{BASE}/api/admin/stats", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
d = r.json()
report("Admin stats returns 200", r.status_code == 200)
report("total_screenings > 0", d.get("total_screenings", 0) > 0, f"total={d.get('total_screenings')}")
report("average_score present", isinstance(d.get("average_score"), (int, float)), f"avg={d.get('average_score')}")
report("severity_distribution non-empty", bool(d.get("severity_distribution")), str(d.get("severity_distribution")))
report("gender_distribution non-empty", bool(d.get("gender_distribution")), str(d.get("gender_distribution")))
report("age_distribution non-empty", bool(d.get("age_distribution")), str(d.get("age_distribution")))
report("language_distribution non-empty", bool(d.get("language_distribution")), str(d.get("language_distribution")))
trend = d.get("trend_7day", [])
report("trend_7day has 7 days", len(trend) == 7)
today_count = trend[-1]["count"] if trend else 0
report("Today's screenings appear in trend", today_count > 0, f"today={trend[-1] if trend else None}")

# Filtered variants used by the dashboard dropdown
for at in ("phq9", "gad7"):
    r = requests.get(f"{BASE}/api/admin/stats?assessment_type={at}", headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    report(f"Filter assessment_type={at} returns 200", r.status_code == 200,
           f"total={r.json().get('total_screenings')}")

print()
print("=" * 70)
print("5. PAGE ROUTES RENDER")
print("=" * 70)
for path, marker in [("/login", "auth"), ("/register", "auth"), ("/admin", "admin"), ("/", "hero")]:
    r = requests.get(f"{BASE}{path}", timeout=10)
    report(f"GET {path} -> 200", r.status_code == 200, f"{len(r.text)} bytes")

print()
print("=" * 70)
print(f"TOTALS: {results['pass']} passed, {results['fail']} failed")
print("=" * 70)
sys.exit(0 if results["fail"] == 0 else 1)
