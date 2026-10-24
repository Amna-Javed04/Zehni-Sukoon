# Zehni Sukoon (ذہنی سکون) — Hackathon Presentation Content

**Bano Qabil × Alibaba Cloud AI Hackathon — National Level**
Everything below is grounded in the repository. Anything the code does not prove is marked **[NEEDS INPUT: …]**. No invented statistics, accuracy numbers, user counts, or clinical claims.

---

## A. VERIFIED FACT SHEET

*(Each item: what is true, with the file that proves it.)*

1. **Screening instruments:** PHQ-9 (9 items) and GAD-7 (7 items), scored 0–3 per item over the last two weeks. — `backend/routes/chat.py` (PHQ9_ITEMS, GAD7_ITEMS), `backend/routes/screening.py`
2. **Two screening modes:** standard written form and conversational ("Humdum") screening; both feed the same `/api/screening/result` scoring path. — `backend/templates/screening.html` (Stage 4A / 4B), `README.md`
3. **Severity uses only the validated clinical score bands.** PHQ-9: 0–4 Minimal, 5–9 Mild, 10–14 Moderate, 15–19 Moderately Severe, 20–27 Severe. GAD-7: 0–4 Minimal, 5–9 Mild, 10–14 Moderate, 15–21 Severe. There is no machine learning in the live decision. — `backend/routes/screening.py`, `test_severity_bands.py`
4. **ML ensemble: evaluated and removed.** An earlier Random Forest / XGBoost / SVM majority-vote ensemble was trained and evaluated, then removed from the live path because a black-box vote could contradict the validated band for the same score and could not be explained to a clinician; severity now comes only from the bands. Artifacts are kept in `ml_research/` and excluded from the Docker build. — `ml_research/README.md`, `.dockerignore`, `requirements.txt` *(Dataset note: your brief says the ensemble was trained on NHANES 2017-2018; no repository file mentions NHANES — **[NEEDS INPUT: NHANES 2017-2018 citation/provenance]**.)*
5. **Crisis rule:** PHQ-9 item 9 > 0 sets `crisis_redirect`; the score and severity are still computed (no short-circuit). — `backend/routes/screening.py`, `backend/routes/user.py` (`_is_crisis`)
6. **Outage-proof crisis floor:** multi-word crisis phrases in Roman Urdu, Urdu script and English are checked server-side, independent of the LLM; a crisis message bypasses the daily chat cap; the helpline reply matches the person's script (Urdu / Roman Urdu / English). — `backend/routes/chat.py` (CRISIS_PHRASES, `_local_crisis_signal`, `_crisis_fallback`, `_consume_chat_turn`)
7. **One verified helpline:** Umang — 0311-7786264, deliberately the only number shipped (unverified numbers were removed as a safety hazard). — `backend/routes/chat.py`, `backend/templates/crisis.html`
8. **"The LLM proposes, deterministic guards dispose":** evidence must quote the user's own words; coverage is monotonic; scores must be integers 0–3; every item must be scored exactly once; completion is derived server-side, never taken from the model; max 2 clarifications per item then a conservative score of 1 (never 0). — `backend/routes/chat.py` (`_validated_coverage`, `_grounded_in_user`, completion derivation), `backend/routes/screening.py` (full-coverage validation)
9. **Honest failure:** if no provider is configured or all fail, the chat says so plainly and offers the written form — no scripted fake empathy. Daily caps: 80 turns/user/day, 40 guest/day (configurable), crisis always bypasses. — `backend/routes/chat.py`, `backend/config.py`
10. **LLM layer:** single client, OpenAI-compatible HTTP (no vendor SDK), default failover order **qwen → groq → gemini**, providers without keys are skipped; 18s timeout, 700-token reply cap, reasoning disabled; 429 fails over immediately; one retry for timeouts/5xx and for a server-side JSON-generation blip. — `backend/llm_client.py`, `.env.example`
11. **Keys currently configured for the demo:** Groq primary (model `qwen/qwen3.8-27b`) and Google Gemini backup (`gemini-2.5-flash`); Qwen/DashScope is first in the order but has no key in this `.env`. — `.env`, `backend/llm_client.py` *(repo-file proof of the order: `.env.example`; live behavior verified in this workspace today.)*
12. **Score extraction path:** conversational scoring goes through the same result endpoint; `POST /api/chat/extract-score` uses the LLM (10s timeout) with a deterministic local keyword heuristic fallback for Urdu / Roman Urdu / English, including a "never ask a clarifying question about self-harm — default to risk ≥ 1" rule. — `backend/routes/chat.py` (EXTRACT_SCORE_SYSTEM_PROMPT, `local_heuristic_extract_score`)
13. **Languages and scripts:** interface is bilingual Urdu (RTL, default) and English (LTR), toggled at runtime with no page reload; the AI mirrors Urdu script, Roman Urdu, or English, and once the user writes Urdu script the conversation stays Urdu. — `backend/static/js/i18n.js`, `backend/routes/chat.py` (URDU_SCRIPT_RE, script rules in the prompt)
14. **Roles:** patient (default), therapist, admin. Therapist signup requires a license number; therapists become usable only after admin verification; there is no API that creates an admin; role checks are server-side. — `backend/models.py`, `backend/routes/auth.py`, `backend/routes/admin.py` (`verify_therapist`), `backend/middleware.py`
15. **Privacy — guests:** guest sessions store a UUID and timestamps only; no name/email fields exist at the schema level; screening rows are owned by exactly one user *or* one guest. — `schema.sql`, `backend/models.py`
16. **Privacy — chat content:** no chat transcript is stored anywhere in the schema; the browser owns the conversation and replays it each turn (stateless); therapist responses and PDFs contain no conversational content. — `schema.sql`, `backend/routes/chat.py` (stateless docstring), `backend/routes/therapist.py`, `backend/routes/pdf_export.py`
17. **Therapist portal — consent:** a patient connects only with an invite code plus an explicit `consent: true` the server requires; the consent modal lists exactly what the therapist will see (display name, age range, gender, scores/severity, item-level answers, crisis flag) and what they will never see (any chat). — `backend/routes/therapist.py`, `backend/templates/dashboard.html` (consent modal)
18. **Therapist portal — revoke and scope:** revoke sets the link to `revoked` and access ends immediately (checked per request); identical 403s never reveal patient existence; guests cannot link; only one active link per pair. — `backend/routes/therapist.py`, `test_therapist_portal.py`
19. **Triage ordering:** patient list sorted crisis first, then severity (Severe → Minimal), then most recent screening. — `backend/routes/therapist.py` (`_triage_sort_key`)
20. **PDF export:** patient self-export of their own history and therapist export behind the same active-link gate; includes trend summary, per-screening scores, disclaimer "This is a screening result, not a diagnosis"; personalized responses are `Cache-Control: no-store`. Limitation stated in code: reportlab's Helvetica cannot render Urdu glyphs, so Urdu-script text in the PDF is a known gap. — `backend/routes/pdf_export.py`
21. **Privacy — admin:** `/api/admin/stats` is fully anonymized aggregates (counts, distributions, 7-day trend); `/api/admin/users` exposes only account metadata, never responses; deleting a user erases their screenings. — `backend/routes/admin.py`
22. **Accounts:** email+password (Werkzeug hashing), JWT (24h), stateless password reset with short-lived tokens and anti-enumeration responses, optional SMTP (reset links logged if unset), one-click guest sessions. — `backend/routes/auth.py`, `backend/config.py`, `.env.example`
23. **Dashboards:** user overview/history with per-instrument trend (improving/worsening/stable, ±1.5-point noise threshold), analysis, tips; admin gets severity/age/gender/language distributions, 7-day trend, date filters, user management, pending-therapist verification. — `backend/routes/user.py`, `backend/routes/admin.py`, templates
24. **Self-care and resources:** self-care page with Box Breathing, "A Gentler Angle" (rethinking), Grounding 5-4-3-2-1, Sleep Sounds, "A Thought for Today"; landing page has Box Breathing; resources hub with the Umang helpline, city-aware Marham.pk and Healthwire.pk therapist links, and a hospital directory; crisis page; Humdum companion widget on every page with an "AI companion, not a medical substitute" disclaimer. — `backend/templates/self_care.html`, `index.html`, `resources.html`, `crisis.html`, `base.html`
25. **Tests — all passing today (run in this workspace):** 7 suites, **311 checks/cases, 0 failures**:
    - `test_screening_guards.py` — 65 checks (conversational safety guards, mocked LLM)
    - `test_llm_providers.py` — 55 checks (failover, caps, crisis floor, JSON-blip retry; mocked HTTP)
    - `test_score_extraction.py` — 40 cases, 0 failed (31 first-pass, 9 correct clarifications)
    - `test_severity_bands.py` — 28 checks (every PHQ-9 total 0–27, GAD-7 bands, crisis rule, no-ML response)
    - `test_therapist_portal.py` — 74 checks (privacy/security contract, consent gate)
    - `test_auth_admin.py` — 31 checks (live, against the running dev server)
    - `test_ai_integration.py` — 18 checks (live: real LLM used, band severity, crisis redirect)
26. **Deployment:** `Dockerfile` (python:3.11-slim, Gunicorn, 2 workers, `${PORT:-5000}`), `docker-compose.yml` (web + PostgreSQL 15, secrets interpolated from git-ignored `.env`, refuses to start without them), `.dockerignore` keeps `.env`, venvs, databases and `ml_research/` out of the image; production boot refuses placeholder secrets; `/api/health` health check. — `Dockerfile`, `docker-compose.yml`, `backend/app.py`
27. **No secrets in the repo:** `.env` gitignored, only `.env.example` tracked; environment-driven config throughout. — `.gitignore`, `.env.example`, `README.md`

**Plain statement for the deck:** *Severity is computed only from the validated PHQ-9 and GAD-7 clinical score bands. An earlier ML ensemble (trained on NHANES 2017-2018 — **[NEEDS INPUT: citation]**) was evaluated and removed from the live decision because a black-box vote could contradict the band for the same score and could never be explained to a clinician.*

---

## B. SLIDE-BY-SLIDE CONTENT (13 slides, 5–7 minutes ≈ 25–30 s/slide)

### Slide 1 — Title
**Title:** Zehni Sukoon — ذہنی سکون · *Mental peace, in your language.*

**Bullets:**
- Bano Qabil × Alibaba Cloud AI Hackathon — National Level
- Team: **[NEEDS INPUT: team name and members]**
- Free, bilingual mental-health check-in for Pakistan
- Screening tool — not a diagnosis

**Speaker notes:** Welcome — one line: "Zehni Sukoon means 'mental peace' — a free, bilingual mental-health check-in built for how people in Pakistan actually speak." Introduce the team **[NEEDS INPUT]**. Say the disclaimer once, early: screening and support, not diagnosis.

**Visual:** App logo/name in Urdu Nastaliq + English; soft teal background; team names; one calm app screenshot (landing page).

---

### Slide 2 — The problem
**Title:** Help exists — rarely in our language, rarely without stigma

**Bullets:**
- Most mental-health tools assume fluent English
- Stigma stops people before they ever ask
- Clinician shortage: **[NEEDS INPUT: verified figure + source]**
- Cost and travel put therapy out of reach: **[NEEDS INPUT: figure + source]**
- (Optional prevalence stat: **[NEEDS INPUT: statistic + source]**)

**Speaker notes:** Keep it personal and short. The language gap is the part nobody else in this room is solving: a person who can *speak* Urdu but *types* Roman Urdu has almost no clinically structured tool in their language. **Use only the statistics you supply — nothing here is in the code.**

**Visual:** Simple two-column contrast: "English-only tools" vs "How people actually type" (show a Roman Urdu chat bubble). No fake numbers on this slide.

---

### Slide 3 — Who is affected / target users
**Title:** One platform, three doors

**Bullets:**
- Individuals checking in — anonymous, device-only
- Psychologists tracking linked patients with consent
- NGOs and clinics needing anonymized overviews
- Anyone communicating in Urdu or Roman Urdu

**Speaker notes:** The person who needs support and wants zero traces gets a guest session — the database stores no name, no email, enforced by the schema. The therapist gets a consent-gated view of linked patients only. The organization gets aggregate dashboards with no individual responses.

**Visual:** Three-icon diagram: person / therapist / organization, arrows into the app logo.

---

### Slide 4 — Our solution
**Title:** One conversation. Clinical screening underneath.

**One sentence:** *Zehni Sukoon turns an honest conversation into a clinically scored mental-health check — in your own language.*

**Bullets:**
- Talk naturally — no form-feeling, no question numbers
- Same validated PHQ-9 / GAD-7 beneath every chat
- Safety enforced by deterministic code, not model mood

**Speaker notes:** The insight: people avoid forms, not check-ins. So the questionnaire disappears into a conversation, but nothing clinical is left to chance — every one of the nine topics still has to be resolved, scored 0–3, and traced back to the user's own words.

**Visual:** Left: chat bubble screenshot. Right: small code-like badge showing `q1…q9 → total score → severity band` connected by an arrow.

---

### Slide 5 — How it works
**Title:** From a few words to a trusted result

**Bullets:**
- Consent screen, then guest or account choice
- Choose written form or Humdum conversation
- Score, severity and crisis banner instantly
- Optional: link a therapist, export PDF history

**Speaker notes:** Walk the flow: consent checkbox → fully anonymous guest or an account → age/gender (for reports only) → pick PHQ-9 or GAD-7 → pick form or chat → results appear with score circle, severity band, and — if item 9 is above zero — the helpline banner immediately. From the dashboard: history and trends, connect to a therapist with consent, download a PDF.

**Visual:** Horizontal flow diagram (5 boxes with icons) plus a results-screen screenshot.

---

### Slide 6 — Key features
**Title:** Everything a safe check-in needs

**Bullets:**
- Bilingual UI; chat mirrors Urdu, Roman Urdu, English
- Conversational screening with live coverage progress
- Outage-proof crisis detection, Umang helpline
- Therapist portal: consent, triage, PDF export

**Speaker notes:** Mention what fits in no bullet: self-care tools (box breathing, 5-4-3-2-1 grounding, sleep sounds), the resources hub with Marham and Healthwire city links and hospitals, the Humdum companion on every page, and the admin dashboard with aggregate-only statistics.

**Visual:** 2×2 screenshot grid: Urdu RTL chat, coverage progress bar, crisis card, self-care page.

---

### Slide 7 — Safety and responsible AI
**Title:** The AI proposes. Deterministic guards decide.

**Bullets:**
- Every score must quote the user's own words
- Crisis keyword floor works even if the AI is down
- Honest failure: form offered, never fake empathy
- Screening, never diagnosis — helpline always shown

**Speaker notes:** This is the heart of the project. The model cannot invent a score (evidence must be the user's own sentence), cannot un-score an item, cannot declare the screening complete — completion is derived by the server. If every LLM provider is rate-limited or down, the multi-script keyword floor still catches a cry for help and shows the helpline; the chat then honestly offers the written form instead of mimicking care.

**Visual:** Shield diagram: "LLM" in the center wrapped by guard labels (evidence, monotonic, crisis floor, derived completion); include the crisis-card screenshot.

---

### Slide 8 — Privacy and ethics
**Title:** Private by design — consent, control, no transcripts

**Bullets:**
- Guest sessions: schema stores nothing identifying
- Chat transcripts are never stored, never shared
- Consent modal lists exactly what a therapist sees
- Revoke anytime — access ends immediately

**Speaker notes:** Conversations live only in the browser and are replayed per turn; no table in the schema holds chat content. The therapist sees scores, demographics and item answers — never conversation — and only while a consent link is active; the same 403 hides whether a patient even exists. Admins see aggregates and account metadata only; deleting a user erases their screenings.

**Visual:** Screenshot of the consent modal (its green "will see" / red "will NOT see" lists) — it already reads like a privacy slide.

---

### Slide 9 — Technology and architecture
**Title:** Simple stack. Serious safeguards.

**Bullets:**
- Flask + Jinja2 + vanilla JS, full RTL/LTR
- SQLite (dev) / PostgreSQL 15 (prod), Docker
- LLM failover: Qwen → Groq → Gemini, env-driven
- Demo keys: Groq primary, Gemini backup

**Architecture (describe as diagram):** Browser (Jinja2 pages, vanilla JS, JWT or guest-session header) → Flask blueprints (auth, screening, chat, user, admin, therapist, PDF) → SQLite/PostgreSQL; the chat routes call one `llm_client` with automatic failover to OpenAI-compatible endpoints (Groq, Google Gemini; Qwen/DashScope configured first, skipped while keyless); crisis checks and all scoring guards run in Flask, independent of the LLM.

**Speaker notes:** One client, three providers, no vendor SDK — a provider outage is a config-level event, not an outage. The demo runs on local Flask at localhost:5000 (or `docker compose up`). **[NEEDS INPUT: which LLM and host you will present for the demo — local only, or a hosted URL / an Alibaba Cloud DashScope key.]** Do not claim Alibaba Cloud hosting unless you confirm it.

**Visual:** 4-box architecture diagram (Browser → Flask → Database; Flask ⇄ LLM failover chain); simple, one line per hop.

---

### Slide 10 — Evidence and validation
**Title:** We tested the ML — and chose the safer rule

**Bullets:**
- RF, XGBoost, SVM ensemble evaluated honestly
- Black-box votes could contradict clinical bands
- Chose transparent, validated score bands
- 311 checks across 7 suites pass today

**Speaker notes:** The honest story: we built the ensemble, tested it against the clinical rule, and removed it — a majority vote over 11 features (nine scores plus age and gender) can silently disagree with the band clinicians trust, and no one can explain why. The band always wins; the models sit in `ml_research/` as evidence of the evaluation. Test numbers are real and reproducible: 311 checks across 7 suites, all green today (guards, failover, extraction, bands, therapist privacy, auth, integration). **Pilot data: [NEEDS INPUT: number of testers, form-vs-chat agreement, psychologist feedback quotes].**

**Visual:** Two paths converge: "ML vote" (grey ✕) and "Clinical bands" (green ✓); below, the test-suite badges with counts.

---

### Slide 11 — Impact, scalability and sustainability
**Title:** Built to scale beyond one app

**Bullets:**
- Free and anonymous for individuals, always
- Clinics subscribe for therapist dashboards
- NGOs get anonymized, aggregate insight
- Limits today: quotas, no validation study yet

**Speaker notes:** Adoption path: individuals for free (guest mode keeps the barrier at zero), then per-therapist subscriptions for clinics, NGO/institution licenses for aggregate programs, and later API partnerships — this is a plan, not current revenue; no numbers are claimed. Technical scalability is proven by design: stateless turns, per-identity daily caps, swappable LLM providers, Docker + Postgres for production. Honest limits: free-tier LLM quotas, English/Urdu web-only, no clinical validation study yet.

**Visual:** Three-step pyramid: free individuals → clinic SaaS → NGO/institution licenses; a small "limits" footnote strip.

---

### Slide 12 — Limitations and roadmap
**Title:** Honest about what's next

**Bullets:**
- Clinician-led validation study first
- Offline mode and Urdu voice input
- Reminders and therapist crisis alerts
- Deeper longitudinal analysis over time

**Speaker notes:** Say limitations plainly: it screens, it does not diagnose; PDF export cannot render Urdu glyphs yet; there are no push notifications — a therapist sees a crisis flag only when they open the portal; conversational turns consume LLM quota. The roadmap order is deliberate: clinical validation before growth, then low-bandwidth/offline, voice in Urdu, reminders, and real-time crisis alerts to linked therapists.

**Visual:** Timeline arrow: Now → Next → Later, three boxes, minimal text.

---

### Slide 13 — Demo plan and closing
**Title:** See it live.

**Bullets:**
- 60-second check-in: conversation to result
- Consent modal and therapist triage
- Crisis floor with helpline, always present
- Closing: pilot with one clinic or NGO

**Demo script (~90 seconds):**
1. *(0:00)* Landing in Urdu — "This is what a Pakistani user sees first, in their language." Toggle to English.
2. *(0:10)* Start screening → consent checkbox → "Continue as guest — no email, no name, stored as a UUID." → age/gender → pick PHQ-9 → **"A Warm Conversation."**
3. *(0:25)* Answer 2–3 items live in Roman Urdu or English ("har waqt thaka rehta hoon") — point at the coverage bar: "Each topic settles only when the app can quote their own words."
4. *(0:50)* Finish remaining items (or switch to the form for speed) → results: score circle, severity band, feedback — "Same bands a clinician uses."
5. *(1:05)* Show the crisis card path: "Item 9 above zero — or a phrase in Roman Urdu — triggers the helpline even if the AI provider is down."
6. *(1:15)* Dashboard: trends + consent modal ("therapist sees scores, never chat") + therapist portal triage (crisis first) + PDF export.
7. *(1:25)* One line on tests: "311 checks pass across 7 suites."

**Backup plan:** if a live LLM turn fails on quota, say it as designed: "That's our honest-degradation path — the app just offers the written form instead of faking a reply," then complete the form.

**Closing line:** "Mental peace shouldn't depend on the language you dream in. Zehni Sukoon makes a clinical check-in as easy as sending a message."
**Call to action:** "We're looking for one clinic or NGO to pilot with in the next 90 days — and judges' feedback on our validation plan."

**Visual:** Live app on screen; final slide = logo + tagline + contact **[NEEDS INPUT: contact/handle]**.

---

## C. CANVA PROMPT

### Short version (≈1,900 characters)

```
Create a 13-slide presentation for "Zehni Sukoon (ذہنی سکون) — Mental peace, in your language", a bilingual Urdu/English mental-health screening web app for Pakistan, for a national AI hackathon. Tone: professional, calm, trustworthy, no hype. Style: soft teal and sage green palette with warm cream backgrounds, clean sans-serif headings (e.g. Inter/Poppins), lots of white space, simple line icons, one idea per slide, max 4 short bullets per slide. All Urdu text must be right-to-left in Noto Nastaliq Urdu font; English left-to-right. Slides: 1) Title: Zehni Sukoon, tagline, team [PLACEHOLDER], hackathon. 2) The problem: language barrier, stigma, few clinicians, cost [I WILL INSERT STATISTICS]. 3) Target users: individuals, therapists, NGOs/clinics. 4) Solution: conversation with clinical PHQ-9/GAD-7 underneath. 5) How it works: consent → guest/account → form or chat → results → therapist link → PDF. 6) Features: bilingual, conversational screening, crisis detection, therapist portal. 7) Safety: "The AI proposes, deterministic guards decide", outage-proof crisis floor. 8) Privacy: anonymous guests, consent, no stored chat transcripts. 9) Architecture: browser → Flask → database, LLM failover Qwen/Groq/Gemini. 10) Evidence: tested ML, chose clinical bands, 311 passing checks. 11) Impact and sustainability. 12) Limitations and roadmap. 13) Live demo and closing. Insert my app screenshots at [PLACEHOLDERS] on slides 1, 5, 6, 7, 8, 13.
```

### Full version (bullets included; paste as-is)

```
13-slide deck, "Zehni Sukoon (ذہنی سکون) — Mental peace, in your language." Bilingual mental-health screening app for Pakistan; Bano Qabil × Alibaba Cloud AI Hackathon, national level. Tone: professional, calm, trustworthy, plain language, no buzzwords. Design: soft teal/sage green + warm cream, clean sans-serif (Inter/Poppins), generous white space, simple line icons, one idea per slide, ≤4 short bullets, large readable type. Urdu text always right-to-left in Noto Nastaliq Urdu; English LTR; keep scripts separate per line.
SLIDES: 1 Title — Zehni Sukoon, tagline, team [PLACEHOLDER], hackathon, "screening tool, not a diagnosis". 2 Problem — English-only tools; stigma; clinician shortage [I INSERT STATS]; cost [I INSERT STATS]. 3 Users — anonymous individuals; psychologists with consent; NGOs/clinics with anonymized views. 4 Solution — "one conversation, clinical screening underneath": natural chat; validated PHQ-9/GAD-7; deterministic safety. 5 How it works — consent → guest or account → details → form or chat → results → optional therapist link → PDF. 6 Features — Urdu/Roman Urdu/English; conversational screening; crisis detection + Umang helpline; therapist portal with consent, triage, PDF. 7 Safety — "The AI proposes, deterministic guards decide"; evidence must be the user's own words; outage-proof crisis floor; honest failure, no fake empathy. 8 Privacy — guests store nothing identifying; no chat transcripts anywhere; consent modal shows what therapists see; revoke anytime. 9 Architecture — browser (Jinja2 + vanilla JS) → Flask blueprints → SQLite/PostgreSQL; one LLM client failing over Qwen → Groq → Gemini; keys from environment. 10 Evidence — ML ensemble (RF/XGBoost/SVM) tested and retired; validated clinical bands chosen; 311 checks across 7 suites pass. 11 Impact — free for individuals; clinic subscriptions; NGO aggregate insights; prototype limits stated. 12 Roadmap — clinician validation; offline mode; Urdu voice; reminders; therapist crisis alerts. 13 Demo + closing — live screenshot, tagline, call to action "pilot with one clinic".
PLACEHOLDERS: insert real app screenshots on slides 1 (landing, Urdu RTL), 5 (results screen), 6 (chat bubbles), 7 (crisis card), 8 (consent modal), 13 (dashboard); do not invent photos of people or fabricated charts.
```

---

## D. JUDGE Q&A PREP

**1. Why not just use an LLM?**
An LLM alone guarantees nothing: it can skip items, invent scores, or go down mid-screening. Our product is the layer around it — complete instrument coverage, band-correct scoring, evidence grounding, and privacy. The model is a component we can swap; the guarantees are ours.

**2. What if the LLM is wrong?**
Scores are accepted only with a quote traced to the user's own words; coverage never goes backward; values must be 0–3 integers; completion is derived by the server; after two gentle probes an item snaps to a conservative score. Errors bias toward asking again — never toward inventing an answer.

**3. Who sees patient data?**
The user (their own history), or nobody — guest mode stores only a UUID. A therapist sees scores, demographics and item answers only while a consent link is active, never chat. Admins see aggregates and account metadata; deleting a user erases their screenings.

**4. Is this clinically validated?**
The instruments are the standard, widely used PHQ-9 and GAD-7; our *platform* is not yet clinically validated — that study is the first roadmap item, and every screen says "screening, not diagnosis." **[NEEDS INPUT: any psychologist/pilot feedback you can quote.]**

**5. What did the ML models add?**
Honestly: a majority-vote severity label that could contradict the validated band for the same score, with no way to explain it. We evaluated it, removed it, and kept the artifacts in `ml_research/` — the bands are transparent, standard, and always right for the total score.

**6. Why should clinics trust this?**
Because it's testable and bounded: 311 passing checks, verified-therapist invite codes, consent and instant revocation, no chat storage, disclaimers on every report, and triage ordering that *assists* judgment rather than replacing it. It slots beside their existing process, not over it.

**7. How will it be funded?**
Plan, not revenue: free for individuals, per-therapist subscriptions for clinics, institutional/NGO licenses for aggregate programs, later partner APIs — plus social-impact grants for deployment in underserved areas. **[NEEDS INPUT: any pricing or partnership discussions you can mention.]**

**8. What happens in a crisis if the AI is down?**
A server-side multi-script keyword floor still fires (it never calls the LLM), bypasses rate caps, raises item 9 above zero if answered, and shows the Umang helpline in the person's own script — Urdu, Roman Urdu, or English. The written form always remains available.

**9. What does the Alibaba Cloud ecosystem add to this project?**
The failover chain is already built for Qwen via DashScope's OpenAI-compatible endpoint — it's first in our provider order, and any OpenAI-compatible Alibaba Cloud service slots in with an environment variable, no code change. What we can claim on stage depends on setup: **[NEEDS INPUT: will you demo with an Alibaba Cloud/DashScope key or mention hosting plans? Current demo keys are Groq + Gemini — do not claim more.]**

**10. Why Urdu *and* Roman Urdu?**
Many Pakistanis speak Urdu far better than they read it, and type in Roman. A safety message in a script the reader can't follow isn't a safety message — so crisis replies are returned in the exact script the person typed in. That same rule drives the whole conversation.

**11. How accurate is scoring free-text replies?**
We test it: 40 realistic replies in Urdu, Roman Urdu and English — all 40 correct (31 direct, 9 correctly routed to clarification), with a "never clarify self-harm, default to risk" rule and a local keyword fallback when providers fail. Beyond our suite we make no accuracy claim — a clinician study is the next step.

**12. How do you handle privacy law / isn't this sensitive data?**
We minimize on purpose: no transcripts stored, consent-based access, revocation, account erasure, anonymized aggregates, secrets out of the repo. A formal compliance review (e.g. Pakistan's data-protection developments) is on the roadmap: **[NEEDS INPUT: if you've had any legal review.]**

---

## E. GAPS CHECKLIST *(fill tonight — every [NEEDS INPUT] in this document)*

1. **Slide 1:** Team name and member names.
2. **Slide 1/13:** Contact info or handle for the closing slide.
3. **Slide 2:** Clinician/psychiatrist shortage figure for Pakistan + source.
4. **Slide 2:** Cost-of-therapy figure + source.
5. **Slide 2:** Any prevalence statistic you want (e.g. depression/anxiety) + source — only if verified.
6. **Fact sheet #4 / Slide 10:** NHANES 2017-2018 dataset citation (nothing in the repo mentions it; confirm it's accurate before saying it on stage).
7. **Slide 10:** Pilot results — number of testers, form-vs-chat agreement figures, psychologist feedback quotes.
8. **Slide 9 / Q&A 9:** Which LLM and host you will present for the demo (local Flask only? hosted URL? an Alibaba Cloud DashScope key?) — and whether you'll claim any Alibaba ecosystem tie beyond Qwen/DashScope support in code.
9. **Slide 11 / Q&A 7:** Any real pricing, partnership or grant details you can state (otherwise keep it plan-only).
10. **Q&A 4/12:** Any legal or clinical review you've actually had (otherwise leave the honest "roadmap" answer).
11. **Screenshots to capture before the talk:** landing (Urdu RTL), mode chooser, live chat bubbles, coverage bar, results screen, crisis card, consent modal, therapist patient list (triage), admin aggregate dashboard, PDF preview, self-care page.
12. **Demo logistics:** confirm the dev server + `.env` keys work on demo day (Groq free tier throttles under fast repeated calls — pace the live chat; keep the written form as the backup path).
