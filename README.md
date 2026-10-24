# Zehni Sukoon (ذہنی سکون)

**Mental peace, in your language.** Zehni Sukoon is a bilingual (Urdu / English) mental-health web platform built for users in Pakistan. It combines clinically grounded screening instruments (PHQ-9, GAD-7) with a natural, empathetic AI conversation, an always-available companion chat, self-care guidance, and a directory of real-world help — helplines, therapist platforms, and hospitals.

> **Disclaimer:** Zehni Sukoon is a screening and support tool, not a diagnostic service. It does not replace professional mental-health care.

---

## Table of Contents

- [Features](#features)
- [How the Screening Works](#how-the-screening-works)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started (Local Development)](#getting-started-local-development)
- [Environment Variables](#environment-variables)
- [Docker Deployment](#docker-deployment)
- [API Overview](#api-overview)
- [Testing](#testing)
- [Security & Privacy](#security--privacy)
- [Admin Accounts](#admin-accounts)

---

## Features

**Two ways to take a screening**
- **Standard form** — the classic PHQ-9 / GAD-7 questionnaire, fully localized in Urdu and English.
- **Conversational screening** — instead of a translated checklist, an AI talks with the user the way a therapist would: it listens, reflects, and asks naturally. Scores for every instrument item are extracted from the user's own words in the background, and the result is computed by the same clinical/ML pipeline as the standard form.

**Humdum — AI companion**
- A floating chat widget available on every page for open-ended, supportive conversation (no scoring, no account needed).

**Safety first**
- Crisis phrases typed by a user are detected **server-side, independent of the LLM**, so a rate limit or outage can never swallow a cry for help.
- PHQ-9 item 9 (self-harm) scoring above zero triggers immediate crisis escalation with helpline information, in the user's own language and script (Urdu script or Roman Urdu).

**Dashboards**
- **User dashboard** — personal screening history, trends, and results.
- **Admin dashboard** — aggregate statistics, severity/age/gender distributions, date filtering, and user management (list, add, delete users).

**Accounts & access**
- Email + password accounts (JWT), one-click **guest sessions** (no personal data stored), and a stateless forgot-password/reset flow with optional SMTP delivery.

**Fully bilingual**
- Every page works in Urdu (RTL) and English (LTR), switchable at runtime; the AI mirrors the user's language and even their script (Urdu script vs Roman Urdu).

**Real-world help**
- A resources hub with crisis helplines, city-aware therapist platforms (Marham, Healthwire), and a hospital directory.

## How the Screening Works

**Scoring engine.** Severity comes ONLY from the standard validated clinical score bands. PHQ-9: 0–4 minimal, 5–9 mild, 10–14 moderate, 15–19 moderately severe, 20–27 severe. GAD-7: 0–4 minimal, 5–9 mild, 10–14 moderate, 15–21 severe. Crisis detection = PHQ-9 item 9 > 0. (A machine-learning ensemble was tried here earlier and has been fully removed; see [ml_research/](ml_research/).)

**Conversational mode** uses an LLM behind a **multi-provider failover layer** ([backend/llm_client.py](backend/llm_client.py)): Qwen, Groq and Gemini (any OpenAI-compatible endpoint) are tried in the configured order, with reasoning disabled and a ~18s timeout per call — a 429 fails over to the next provider immediately. The conversation itself follows a strict, stateless contract: the browser owns the transcript and echoes coverage state every turn, so a refresh never loses progress. The server never trusts the model blindly — deterministic guards enforce:

- **User-grounded evidence** — a score is only accepted if it is traceable to the *user's own words* (never to the bot's own question).
- **Monotonic coverage** — items once scored cannot be silently unscored; values are validated to integers 0–3.
- **Derived completion** — the conversation ends only when every item is genuinely answered; the model cannot "declare" completion.
- **LLM-independent crisis floor** — keyword safety net that works even when the LLM is down.
- **Honest degradation** — if the LLM is unavailable or out of quota, the app says so plainly and offers the standard form instead of faking empathy with scripted replies.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, Flask 3.1, Flask-SQLAlchemy, Flask-CORS |
| Auth | PyJWT (login + password-reset tokens), Werkzeug password hashing |
| Database | SQLite (local dev) / PostgreSQL 15 (production, via psycopg2) |
| ML | *(removed)* — severity uses the validated PHQ-9/GAD-7 score bands; retired model artifacts live in `ml_research/` |
| LLM | Multi-provider failover layer (Qwen / Groq / Gemini) over their OpenAI-compatible HTTP endpoints using `requests` — no vendor SDK. Env-configured; providers without a key are skipped. Per-user/per-guest daily chat-turn caps. |
| Frontend | Jinja2 templates, vanilla JS, custom CSS, full RTL/LTR i18n |
| Server | Gunicorn 23 (production), Flask dev server (local) |

## Project Structure

```
ZehniSukoon/
├── run.py                    # Entry point: python run.py  →  http://localhost:5000
├── requirements.txt          # Pinned Python dependencies
├── .env.example              # Config template — copy to .env (never commit .env)
├── Dockerfile / docker-compose.yml
│                             # Production image + web/db stack
├── schema.sql                # Reference schema
│
├── backend/
│   ├── app.py                # Application factory: config, blueprints, page routes
│   ├── config.py             # Env-driven config classes (dev/prod)
│   ├── models.py             # SQLAlchemy models: users, guest_sessions, screenings, resources
│   ├── middleware.py         # JWT decorators: require_user / require_admin
│   │
│   ├── routes/
│   │   ├── auth.py           # Signup, login, guest sessions, password reset
│   │   ├── screening.py      # Standard form: start + result (validated score bands)
│   │   ├── chat.py           # Conversational screening turn engine + Humdum companion
│   │   ├── user.py           # User dashboard data (overview, history)
│   │   └── admin.py          # Admin stats + user management
│   │
│   ├── templates/            # Jinja2 pages (bilingual, RTL-aware)
│   └── static/               # CSS + JS (api client, auth, i18n, theme, chat widget)
│
├── ml_research/              # Retired ML artifacts (NOT used by the app)
│                             # RF/xgb/svm pickles + label encoder (research only)
│
└── test_*.py                 # Test suites (see Testing)
```

## Getting Started (Local Development)

**Prerequisites:** Python 3.11+

```bash
# 1. Clone and enter the project
git clone https://github.com/Amna-Javed04/Zehni-Sukoon.git
cd Zehni-Sukoon

# 2. Create a virtual environment and install dependencies
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env           # then edit .env — see table below
# Minimum for local dev: set SECRET_KEY, JWT_SECRET_KEY, and at least one
# LLM provider keys — GROQ_API_KEY (primary) and/or GEMINI_API_KEY (legacy)
# (DATABASE_URL already defaults to local SQLite)

# 4. Run
python run.py                  # → http://localhost:5000
```

The database tables are created automatically on first run. No migrations step is required for development.

## Environment Variables

All configuration comes from environment variables (loaded from `.env`). **Never commit `.env`** — it is gitignored; only `.env.example` is tracked.

| Variable | Required | Purpose |
|---|---|---|
| `FLASK_ENV` | No | `development` (default) or `production` |
| `SECRET_KEY` | **Yes** (prod) | Flask session signing |
| `JWT_SECRET_KEY` | **Yes** (prod) | Signs login + password-reset tokens |
| `DATABASE_URL` | **Yes** (prod) | `sqlite:///zehni_test.db` locally; `postgresql://…` in production |
| `LLM_PROVIDERS` | No | Failover order, e.g. `qwen,groq,gemini` (default order; keyless providers are skipped) |
| `QWEN_API_KEY` / `QWEN_BASE_URL` / `QWEN_MODEL` | No | Qwen (DashScope compatible-mode); defaults `qwen3.8-flash` |
| `GROQ_API_KEY` / `GROQ_BASE_URL` / `GROQ_MODEL` | No | Groq; `.env.example` uses `qwen/qwen3.8-27b` (the `openai/gpt-oss-120b` fallback needs its thinking capped — see `GROQ_REASONING_EFFORT`) |
| `GROQ_REASONING_EFFORT` | No | Groq thinking budget: `low` (default), `medium`, `high`; any other value omits the field |
| `GEMINI_API_KEY` | Yes (AI features) | Google Gemini API key — works alone as the legacy single provider |
| `GEMINI_MODEL` | No | Set to a model currently listed as available in Google AI Studio (IDs rotate) |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_TOKENS` | No | Defaults 18s / 700 tokens per call |
| `LLM_RECENT_TURNS` | No | Recent transcript messages sent verbatim (default 6); earlier turns travel as the server's compact scored-items record |
| `CHAT_TURNS_PER_USER_DAY` / `CHAT_TURNS_PER_GUEST_DAY` | No | Daily chat-turn caps (defaults 80 / 40). A crisis message always bypasses the cap |
| `CORS_ORIGINS` | No | Comma-separated allowed origins |
| `GUEST_SESSION_EXPIRY_HOURS` | No | Default 24 |
| `JWT_ACCESS_EXPIRES_HOURS` | No | Default 24 |
| `PASSWORD_RESET_EXPIRY_MINUTES` | No | Default 30 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `MAIL_FROM` | No | Email delivery for password resets. Leave blank to log reset links to the server console instead. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Docker only | Consumed by `docker-compose.yml` via `${VAR:?}` — the stack refuses to start without them |

**Production guard:** with `FLASK_ENV=production`, the app refuses to boot if `SECRET_KEY`, `JWT_SECRET_KEY`, or `DATABASE_URL` still contain placeholder values.

## Docker Deployment

```bash
cp .env.example .env   # fill in real production values first
docker compose up --build
```

This starts two services: `web` (Gunicorn, 4 workers, port 5000) and `db` (PostgreSQL 15). The Dockerfile sets `FLASK_ENV=production`, and `.dockerignore` ensures `.env`, the venv, and local databases are never baked into the image.

## API Overview

All API routes are JSON. Authenticated routes expect `Authorization: Bearer <token>`.

| Endpoint | Auth | Description |
|---|---|---|
| `POST /api/auth/signup` | — | Create account (always non-admin) |
| `POST /api/auth/login` | — | Login → `{ token, user{…, is_admin, redirect_to} }` |
| `POST /api/auth/guest` | — | Anonymous guest session |
| `POST /api/auth/forgot-password` | — | Request reset link (anti-enumeration: identical response either way) |
| `POST /api/auth/reset-password` | — | Reset password with token |
| `POST /api/screening/start` | User/Guest | Start a standard-form screening |
| `POST /api/screening/result` | User/Guest | Submit answers → band-based score, severity, crisis flag |
| `POST /api/chat/screening-turn` | User/Guest | One conversational screening turn (transcript in → reply + coverage out) |
| `POST /api/chat/extract-score` | User/Guest | Extract instrument scores from a conversation |
| `POST /api/chat/companion` | — | Humdum companion chat (no account needed) |
| `GET /api/user/overview` | User | Personal dashboard summary |
| `GET /api/user/history` | User | Personal screening history |
| `GET /api/admin/stats` | Admin | Aggregate platform statistics |
| `GET /api/admin/users` | Admin | List users |
| `POST /api/admin/users` | Admin | Add a user |
| `DELETE /api/admin/users/<id>` | Admin | Delete a user |
| `GET /api/health` | — | Health check |

## Testing

```bash
# Offline suites (no server, no LLM quota needed)
python test_screening_guards.py    # conversational-screening safety guards
python test_llm_providers.py       # multi-provider failover, caps, crisis floor (mocked HTTP)
python test_score_extraction.py    # 40 cases: score extraction incl. clarification flow
python test_severity_bands.py      # PHQ-9/GAD-7 band mapping, crisis rule, no-ML response

# Live suites (dev server must be running: python run.py)
python test_auth_admin.py          # auth, role-based redirects, admin access control
python test_ai_integration.py      # end-to-end scoring, crisis redirect, band severity

# Provider benchmark (needs real API keys in .env; spends a little quota)
python scripts/llm_benchmark.py    # accuracy + avg latency per configured provider
```

## Security & Privacy

- **No secrets in the repo.** All credentials come from environment variables; `.env` is gitignored and `.dockerignore`d; historical leaks were audited and rotated.
- **Passwords** are hashed with Werkzeug (never stored in plaintext); password reset uses short-lived, stateless JWT tokens with anti-enumeration responses.
- **Role-based access control** is enforced server-side on every admin endpoint — there is no client-side-only protection.
- **Guest privacy:** guest sessions store no identifying information (enforced at schema level).
- **Mental-health data** is scoped per user; every user-owned query filters by the authenticated caller.

## Admin Accounts

There is intentionally **no API endpoint that creates an admin** — signup always produces a non-admin user. To grant admin access:

1. Sign up normally (or pick an existing account).
2. Flip the flag directly in the database:

```sql
UPDATE users SET is_admin = 1 WHERE email = 'you@example.com';
```

3. Log in again — admins land on `/admin`, regular users on `/dashboard`.

---

*Built with care for mental-health awareness in Pakistan.*
