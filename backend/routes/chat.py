from flask import Blueprint, request, jsonify, current_app
import requests
import json
import re
import time

chat_bp = Blueprint('chat', __name__, url_prefix='/api/chat')

# ════════════════════════════════════════════════════════════════
# Conversational screening contract
# ════════════════════════════════════════════════════════════════
# Conversational mode is NOT the questionnaire read aloud. The LLM holds a
# natural counselling conversation while, underneath, every clinical topic
# still has to be resolved so the q1..qN answers sent to
# /api/screening/result stay complete (the PHQ-9 ensemble needs all nine
# features, and a missing item used to be silently scored as "not at all").
#
# `key` values match the answers_dict keys in backend/routes/screening.py.
# `nudge_*` are seeding angles for the model to paraphrase - never to quote.
PHQ9_ITEMS = [
    {'key': 'q1', 'topic_ur': 'کاموں میں دلچسپی یا لطف کا ختم ہو جانا',
     'topic_en': 'loss of interest or pleasure in things',
     'nudge_ur': 'جن کاموں میں پہلے مزا آتا تھا، وہ اب کیسے لگتے ہیں؟',
     'nudge_en': 'the things you used to enjoy - how do they feel these days?'},
    {'key': 'q2', 'topic_ur': 'اداسی، مایوسی یا ہمت ٹوٹ جانا',
     'topic_en': 'feeling down, low or hopeless',
     'nudge_ur': 'ان دنوں اپنے اندر کا مزاج کیسا رہتا ہے - اداسی سی چھاتی ہے یا حوصلہ ٹھیک ہے؟',
     'nudge_en': 'how your mood has been sitting inside you lately'},
    {'key': 'q3', 'topic_ur': 'نیند نہ آنا، رات جلدی کھل جانا یا بہت زیادہ سونا',
     'topic_en': 'trouble sleeping, waking early, or sleeping too much',
     'nudge_ur': 'راتوں کا کیسا حال ہے - نیند آ جاتی ہے یا رات کٹ جاتی ہے؟',
     'nudge_en': 'how the nights are going, whether sleep comes easily'},
    {'key': 'q4', 'topic_ur': 'تھکن یا توانائی کا ختم ہو جانا',
     'topic_en': 'feeling tired or having little energy',
     'nudge_ur': 'دن بھر کی تھکاوٹ کے بارے میں بتائیے - توانائی دیر تک ٹھکتی ہے؟',
     'nudge_en': 'energy through the day, whether small tasks feel heavy'},
    {'key': 'q5', 'topic_ur': 'بھوک کم ہو جانا یا بہت زیادہ کھا لینا',
     'topic_en': 'appetite dropping or eating a lot more',
     'nudge_ur': 'کھانے کا شوق اور بھوک کیسی ہے؟',
     'nudge_en': 'appetite and how meals have been going'},
    {'key': 'q6', 'topic_ur': 'خود کو ناکام سمجھنا یا مایوسی محسوس کرنا',
     'topic_en': 'feeling bad about yourself, a failure, or having let family down',
     'nudge_ur': 'خود کے بارے میں کیا خیال آتا ہے - کہیں آپ خود کو ناکام تو نہیں سمجھنے لگے؟',
     'nudge_en': 'how they feel about themselves, any sense of letting people down'},
    {'key': 'q7', 'topic_ur': 'کسی بات پر توجہ ٹِکنے میں دشواری',
     'topic_en': 'trouble concentrating',
     'nudge_ur': 'کسی کام یا پڑھائی میں ذہن ٹِکتا ہے یا بار بار بٹھرا جاتا ہے؟',
     'nudge_en': 'whether the mind stays put on one thing or keeps drifting'},
    {'key': 'q8', 'topic_ur': 'انتہائی سستی یا الٹا بے چینی سے حرکت کرنا',
     'topic_en': 'moving or speaking very slowly, or being restless and fidgety',
     'nudge_ur': 'کیا ایسا محسوس ہوتا ہے کہ آپ بہت سست ہو گئے ہیں، یا الٹا بے چینی سے قرار نہیں پڑتا؟',
     'nudge_en': 'whether everything feels slowed down, or the opposite - keyed up and unable to settle'},
    {'key': 'q9', 'topic_ur': 'مر جانا بہتر سمجھنا یا خود کو نقصان پہنچانے کے خیالات',
     'topic_en': 'thoughts of being better off dead or of self-harm',
     'nudge_ur': 'کیبھی دل سے یہ خیال آیا ہے کہ بس، یہ سب ختم ہو جائے تو بہتر؟',
     'nudge_en': 'whether part of them ever wishes it would all just stop'},
]

GAD7_ITEMS = [
    {'key': 'q1', 'topic_ur': 'گھبراہٹ، بے چینی یا ذہنی دباؤ',
     'topic_en': 'feeling nervous, anxious or on edge',
     'nudge_ur': 'اندر ہی اندر گھبراہٹ یا بے چینی سی رہتی ہے - آپ کا کیسا چل رہا ہے؟',
     'nudge_en': 'whether they feel keyed up, nervous or on edge'},
    {'key': 'q2', 'topic_ur': 'فکر کو روکنے یا قابو میں رکھنے سے بے بسی',
     'topic_en': 'not being able to stop or control worrying',
     'nudge_ur': 'فکر ایک بار آ جائے تو اسے روک پاتے ہیں یا سوچیں خود بہ خود چلتی رہتی ہیں؟',
     'nudge_en': 'whether a worry, once started, can be put down again'},
    {'key': 'q3', 'topic_ur': 'بہت سی مختلف چیزوں کی فکر',
     'topic_en': 'worrying too much about a number of different things',
     'nudge_ur': 'ذہن پر کس کس چیز کا بوجھ ہے - ایک دو باتیں یا بہت کچھ اکٹھا؟',
     'nudge_en': 'how many things are competing for their worry at once'},
    {'key': 'q4', 'topic_ur': 'پُرسکون نہ ہو پانا',
     'topic_en': 'trouble relaxing',
     'nudge_ur': 'جب فارغ بیٹھتے ہیں تو ذہن اور جسم سکون محسوس کرتے ہیں یا بے قراری رہتی ہے؟',
     'nudge_en': 'whether they can actually relax when they have the time'},
    {'key': 'q5', 'topic_ur': 'بے چینی کے مارے جگہ پر نہ ٹک پانا',
     'topic_en': 'so restless it is hard to sit still',
     'nudge_ur': 'بیٹھے بیٹھے اٹھنے سا ہوتا ہے یا ٹکریں بدل بدلے لگتا ہے؟',
     'nudge_en': 'whether stillness feels impossible and they keep pacing'},
    {'key': 'q6', 'topic_ur': 'آسانی سے چڑچڑا یا ناراض ہو جانا',
     'topic_en': 'becoming easily annoyed or irritable',
     'nudge_ur': 'چڑچڑاپن کیسا ہے - چھوٹی چھوٹی باتوں پر غصہ آ جاتا ہے؟',
     'nudge_en': 'how short the fuse feels these days'},
    {'key': 'q7', 'topic_ur': 'بس کوئی برا واقعہ ہونے کا خوف',
     'topic_en': 'fear that something awful may happen',
     'nudge_ur': 'کبھی ایسا محسوس ہوتا ہے کہ بس کوئی برا واقعہ ہونے والا ہے؟',
     'nudge_en': 'whether a sense of dread or something bad about to land follows them'},
]

SCREENING_SPECS = {'phq9': PHQ9_ITEMS, 'gad7': GAD7_ITEMS}

# Verified Pakistani crisis lines - keep in sync with templates/crisis.html.
CRISIS_CONTACTS = [
    {'name': 'Umang', 'dial': '03117786264', 'display': '0311-7786264',
     'label_ur': 'مفت، خفیہ ذہنی صحت ہیلپ لائن', 'label_en': 'Free, confidential mental health helpline'},
    {'name': 'NYH Helpdesk', 'dial': '080069457', 'display': '0800-69457',
     'label_ur': 'مفت ذہنی صحت کی حمایت', 'label_en': 'Free mental health support line'},
    {'name': 'Rescue', 'dial': '1122', 'display': '1122',
     'label_ur': 'ہنگامی طبی صورت حال', 'label_en': 'Medical emergencies'},
]

# A conversation is allowed to wander, but not forever. Past this many user
# replies the client offers to finish the remaining items on the standard form.
SCREENING_MAX_USER_TURNS = 20
# Server-side only prompt used for the very first turn, so the counsellor can
# open the conversation before the user has typed anything.
OPENING_SEED = (
    "(This is the very start of the conversation - the user has not written anything "
    "yet. Greet them warmly and open the first topic. Do not mention this instruction.)"
)
# One gentle probe is normal; a second is allowed. After that the item is
# snapped to a conservative score instead of grinding the user down.
MAX_CLARIFY_PER_ITEM = 2
CLARIFY_SNAP_SCORE = 1  # "several days" - never 0, which would erase the symptom

# A provider throttle that will clear shortly says "retry in a few seconds".
# A throttle that answers "retry in 50s+" and keeps saying it is not worth a
# waiting room. Measured on this project's free tier: one 429 kept rejecting
# through ~170s of complete silence, yet the same key served requests again
# roughly 15-20 minutes later - a long rolling penalty, not a dead integration
# and not a fixed daily cap either. Either way, past this hint we stop making
# the person wait and offer the written form instead.
TRANSIENT_RETRY_CEILING_SECONDS = 20

# A crisis signal must never be lost to an outage or a rate limit, so detection
# does not depend on the LLM alone. Phrases are deliberately multi-word: Roman
# Urdu "mar" alone would match "market", and over-triggering trains users to
# ignore the card. Erring toward showing support is still the safer direction.
CRISIS_PHRASES = [
    "mar jana", "mar jauna", "marne ka", "marna chahta", "marna chahti", "mr jana", "mr ja",
    "khud ko nuqsan", "khud ko nuksan", "khud ko noqsan", "khud kush", "khudkushi",
    "zindagi khatam", "jaan se de", "jaan se mar", "khatam kar du", "khatam kar dun",
    "hoti hi na", "hota hi na", "kaash main na", "kash main na", "kaash main hoti",
    "better off dead", "end my life", "kill myself", "hurt myself", "suicide",
    "خودکشی", "مر جانا", "نقصان پہنچا", "کاش میں نہ",
]
CRISIS_FALLBACK = {
    'ur': ('آپ نے جو کہا اس میں بڑی تکلیف ہے، اور یہ بات میرے لیے بہت اہم ہے۔ آپ اکیلے نہیں — '
           'نیچے دیے گئے نمبروں پر ابھی کوئی اصل انسان آپ سے بات کر سکتا ہے۔ جب آپ تیار ہوں تو '
           'مجھے سناتی رہیے، میں یہاں ہوں۔'),
    # Many people in Pakistan can speak Urdu far better than they can read it, and
    # type in Roman for that reason. A safety message written in a script the
    # reader cannot follow is not a safety message.
    'ur-Roman': ('Aap ne jo kaha us mein bohat takleef hai, aur yeh baat mere liye bohat ahem hai. '
                 'Aap akele nahi hain — neeche diye gaye number par abhi koi asli insaan aap se baat '
                 'kar sakta hai. Jab aap taiyar hon to mujhe sunati rahiye, main yahan hoon.'),
    'en': ('What you just said carries a lot of pain, and I want you to know I heard it. '
           'You are not alone - someone real can talk with you right now on the numbers below. '
           'Whenever you are ready, keep telling me; I am still here.'),
}

_URDU_SCRIPT_RE = re.compile(r"[\u0600-\u06FF]")


def _crisis_fallback(language, written_by_user):
    """Pick the crisis reply in the script the person is actually using."""
    if language != 'ur':
        return CRISIS_FALLBACK['en']
    if not _URDU_SCRIPT_RE.search(written_by_user or ''):
        return CRISIS_FALLBACK['ur-Roman']
    return CRISIS_FALLBACK['ur']



def _local_crisis_signal(text):
    low = (text or '').lower()
    return any(phrase in low for phrase in CRISIS_PHRASES)


def _item_lookup(assessment_type):
    spec = SCREENING_SPECS.get(assessment_type) or []
    return {item['key']: item for item in spec}


def _call_llm(api_key, base_url, model, messages, json_mode=False, timeout=25):
    """POST to the active OpenAI-compatible chat endpoint, return message content."""
    payload = {'model': model, 'messages': messages}
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json=payload,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


def _classify_llm_failure(exc):
    """
    Split provider failures into three kinds:

      'config'     bad key / bad model / malformed request - this chat will
                   never come up, so hand over to the form immediately
      'transient'  a short throttle - one quiet backoff retry is worth it
      'exhausted'  the quota is spent for a long window - stop, never stall

    A conversational screening costs 10-16 LLM calls, so 429 is expected under
    any concurrency and must never be mistaken for a dead integration. But it
    must not be mistaken for a *brief* blip either: the provider's own retry
    hint is the only honest signal separating the two, and a large hint means
    waiting will not help. Someone in distress should be offered the form now,
    not asked to resend four times against a wall.
    """
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None)
    if status is not None and 400 <= status < 500 and status != 429:
        return 'config', None
    body = getattr(response, 'text', '') or ''
    match = re.search(r'retry in\s+(\d+(?:\.\d+)?)s', body)
    if match:
        delay = float(match.group(1))
        if delay > TRANSIENT_RETRY_CEILING_SECONDS:
            return 'exhausted', delay
        return 'transient', delay
    if status == 429:
        # Rate limited with no usable hint: assume the long window rather than
        # loop blindly while a person waits on a reply that is never coming.
        return 'exhausted', None
    return 'transient', 3.0  # network timeout / 5xx / connection reset


def _extract_json_object(text):
    """Parse a JSON object out of a model reply, tolerating stray prose/fences."""
    text = (text or '').strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError('no JSON object found in model reply')


def _tidy_reply(text):
    """Keep the counsellor's message in plain conversational prose."""
    cleaned = (text or '').replace('\r', '').strip()
    lines = []
    for line in cleaned.split('\n'):
        stripped = line.strip().lstrip('-*•\u2022 ').strip()
        if stripped:
            lines.append(stripped)
    return ' '.join(lines)[:900]


def _sanitize_transcript(raw):
    """Keep only well-formed chat turns, trimmed and bounded in length."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for msg in raw:
        if not isinstance(msg, dict):
            continue
        role = msg.get('role')
        content = msg.get('content')
        if role not in ('user', 'assistant') or not isinstance(content, str):
            continue
        content = content.strip()
        if content:
            cleaned.append({'role': role, 'content': content[:1200]})
    return cleaned[-40:]


def _user_text(transcript):
    """All the user's own words in this conversation, lowercased, as one string."""
    return ' '.join(m['content'] for m in transcript if m['role'] == 'user').lower()


_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _grounded_in_user(evidence, user_text):
    """
    Does this evidence actually come from something the USER said?

    The model sees its own messages too, so without this check it can "score" an
    item by quoting the question it just asked, and can flag a crisis it raised
    itself. That would end a screening on the model's initiative instead of the
    patient's words - which is precisely the thing a hidden assessment cannot
    afford. Quotes are accepted verbatim; a light token-overlap allowance covers
    harmless re-quoting of the user's own phrasing.
    """
    ev = (evidence or '').strip().lower()
    if not ev or not user_text:
        return False
    if ev in user_text:
        return True
    tokens = [t for t in _WORD_RE.findall(ev) if len(t) > 2]
    if not tokens:
        return False
    user_tokens = set(_WORD_RE.findall(user_text))
    hits = sum(1 for t in tokens if t in user_tokens)
    return hits / len(tokens) >= 0.6


def _validated_coverage(raw_coverage, spec_map, prior_coverage, user_text='',
                        require_evidence=True):
    """
    Merge the model's coverage map over the prior (already validated) one.

    Coverage is monotonic: an item that was once scored never disappears
    because the model dropped it from this turn's JSON. Scores must be whole
    numbers 0-3, and a score with no quoted evidence is discarded so the item
    gets asked again rather than hallucinated. Evidence that cannot be traced
    back to the user's own words is discarded for the same reason.
    """
    coverage = {k: dict(v) for k, v in (prior_coverage or {}).items() if k in spec_map}
    if not isinstance(raw_coverage, dict):
        return coverage
    for key, value in raw_coverage.items():
        if key not in spec_map:
            continue
        score, confidence, evidence = value, 'medium', ''
        if isinstance(value, dict):
            score = value.get('score')
            confidence = str(value.get('confidence', 'medium')).strip().lower()
            evidence = str(value.get('evidence', '')).strip()[:300]
        try:
            score = int(score)
        except (TypeError, ValueError):
            continue
        if score < 0 or score > 3:
            continue
        if require_evidence and len(evidence) < 2:
            continue
        if require_evidence and not _grounded_in_user(evidence, user_text):
            continue
        coverage[key] = {
            'score': score,
            'confidence': confidence if confidence in ('low', 'medium', 'high') else 'medium',
            'evidence': evidence,
        }
    return coverage


def _build_screening_system_prompt(assessment_name, spec, remaining, pending_item,
                                   turns_used, max_turns, preferred_lang):
    """Assemble the counsellor persona + the clinical bookkeeping it hides behind."""
    topic_lines = '\n'.join(
        f"  - {i['key']}: {i['topic_en']} / {i['topic_ur']}"
        for i in spec
    )
    remaining_lines = '\n'.join(
        f"  - {i['key']}: {i['topic_en']} / {i['topic_ur']}\n"
        f"      (angle you may paraphrase: {i['nudge_en']} / {i['nudge_ur']})"
        for i in remaining
    ) or '  (none - every topic is covered)'

    pending_block = ''
    if pending_item:
        pending_block = (
            f"The user's most recent reply was in answer to you exploring: "
            f"{pending_item['key']} - {pending_item['topic_en']} / {pending_item['topic_ur']}. "
            f"Judge that item first, but still credit anything they volunteered about others.\n"
        )

    lang_hint = (
        "The interface language is Urdu, and this user very likely writes Urdu or Roman Urdu - "
        "match their script exactly." if preferred_lang == 'ur'
        else "The interface language is English - default to English unless the user switches."
    )

    turns_left = max_turns - turns_used

    return (
        f"You are Humdum (ہمدم), a warm, experienced counsellor on Zehni Sukoon, a mental "
        f"wellbeing platform in Pakistan. You are holding a conversation that doubles as a "
        f"{assessment_name} wellbeing check. The user must never feel they are filling in a form.\n\n"

        "HOW YOU TALK\n"
        f"- {lang_hint}\n"
        "- MIRROR THE SCRIPT EXACTLY, EVERY TURN. Look at the script of the user's most recent "
        "message and write your whole reply in that one script. If they wrote Roman Urdu "
        "(\"main theek nahi hoon\"), your reply must be pure Roman Urdu - not a single Urdu-script "
        "word in it. If they wrote Urdu script, reply in pure Urdu script. Never blend the two in "
        "one message, and never drift back to Urdu script just because the interface is Urdu.\n"
        "- Warm, plain, human. Never clinical, never robotic, never preachy.\n"
        "- Reflect what they just said in one short phrase, then move on with genuine curiosity.\n"
        "- Ask about ONE thing at a time. Never two questions in one message.\n"
        "- Keep it to 1-3 short sentences. No bullet points, no headings, no emoji, no markdown.\n"
        "- Use the details they gave you - their name for nothing, but their world for everything. "
        "If they mentioned their mother, their shop, their exams, come back to it.\n"
        "- Do not moralise, reassure reflexively, or tell them how they should feel.\n\n"

        "NEVER DO THESE THINGS\n"
        "- Never number anything. Never say \"question 3 of 9\" or count out loud.\n"
        "- Never read a topic aloud word for word, and never reuse the wording in the topic list "
        "below verbatim. Invite, do not recite.\n"
        "- Never mention PHQ-9, GAD-7, a questionnaire, scoring, points, severity, or a diagnosis.\n"
        "- Never say you are an AI, a model, or a bot. Never say \"as a language model\".\n"
        "- Never promise treatment, medication, or a diagnosis.\n\n"

        f"WHAT THIS CHECK MUST COVER (internally - {assessment_name})\n"
        f"{topic_lines}\n"
        "For each item, judge how often it has been true over the LAST TWO WEEKS:\n"
        "  0 = not at all, 1 = several days, 2 = more than half the days, 3 = nearly every day\n\n"

        "YOUR TWO JOBS EVERY TURN\n"
        "1. LISTEN AND SCORE. Read the WHOLE conversation, not just the last message. People answer "
        "obliquely (\"main so nahi paati\", \"ghar walon par chilla deti hoon\", \"sab bojh lagta hai\") "
        "- translate that into a frequency honestly. If a topic already came up naturally before you "
        "asked about it, score it then. Only give a score when you can quote the words that earned it "
        "in \"evidence\"; otherwise leave that item out and ask about it later.\n"
        "   EVIDENCE MUST BE THE USER'S OWN WORDS, never your own question or paraphrase. If the "
        "user has not answered a topic yet, that topic is simply not scoreable this turn - leave it "
        "out, even if you just raised it. An unasked item costs you one more turn; a score invented "
        "from your own sentence is a clinical error.\n"
        "2. LEAD GENTLY. Choose exactly one uncovered topic and steer toward it in your own words. "
        "If nothing is left to cover, close warmly - say their results are ready - and set complete "
        "to true. Never state a number or a verdict.\n\n"

        f"TOPICS STILL UNRESOLVED ({len(remaining)} of {len(spec)} left)\n"
        f"{remaining_lines}\n\n"
        f"{pending_block}"
        f"Turns used: {turns_used}. Turns before we hand over to the written form: {max(turns_left, 0)}.\n"
        f"If that leaves barely enough turns to cover what remains, ask about the remaining topics "
        f"more directly - still kindly, still in your own words, but stop circling.\n\n"

        "SAFETY - READ CAREFULLY\n"
        "If the user hints at wanting to die, hurting themselves, or not wanting to wake up:\n"
        "- Set crisis to true, and put the user's own phrase that triggered it in \"crisis_evidence\".\n"
        "- crisis is about THEIR words only. Asking about this topic yourself is not a signal - do "
        "not set crisis just because your own last message raised item q9.\n"
        "- Do NOT interrogate them about method, plans, or means. Do NOT panic or lecture.\n"
        "- Stay with them. Name the pain, take it seriously, and tell them plainly that a real "
        "person is available to talk right now.\n"
        "- Then keep the conversation going; the screening continues.\n"
        "- When you have any doubt about item q9, score it 1 or higher. Never leave a hinted "
        "self-harm topic unanswered, and never ask a clarifying question about it.\n\n"

        "OUTPUT FORMAT\n"
        "Return ONLY a valid JSON object, nothing else:\n"
        "{\n"
        '  "reply": "your conversational message to the user, in their language and script",\n'
        '  "coverage": { "q1": {"score": 0, "confidence": "high", "evidence": "their exact words"}, ... },\n'
        '  "target_item": "q3" or null,\n'
        '  "phase": "asking" | "clarifying" | "closing",\n'
        '  "crisis": true | false,\n'
        '  "crisis_evidence": "the user\'s own words, or empty string",\n'
        '  "complete": true | false\n'
        "}\n"
        "coverage must contain every item you are confident about from the entire conversation so far, "
        "each with a short verbatim quote in evidence. target_item must be one of the unresolved topics "
        "above."
    )


def local_heuristic_extract_score(assessment_type, question, reply):
    """
    Fallback score extraction using keyword matching in Urdu/Roman Urdu/English.
    """
    reply_clean = reply.lower().strip()
    
    # 1. Self-harm / Crisis Detection (PHQ-9 Q9)
    is_self_harm_item = "better off dead" in question.lower() or "نقصان" in question or "مر جانا" in question
    self_harm_keywords = ["mar", "marna", "die", "suicide", "hurt", "nuksan", "nooksan", "zakhmi", "خودکشی", "نقصان", "موت", "مرنا"]
    if is_self_harm_item or any(kw in reply_clean for kw in self_harm_keywords):
        denial_keywords = ["bilkul nahi", "bilkul nahin", "kabhi nahi", "kabhi nahin", "no", "never", "نہیں", "بالکل نہیں", "کبھی نہیں"]
        if any(dk in reply_clean for dk in denial_keywords) or reply_clean == "nahi" or reply_clean == "nahin":
            return 0, "User explicitly denied self-harm thoughts.", False
        return 1, "Self-harm/suicide risk keyword detected or ambiguous response.", False

    # 2. Vague responses check (requires clarification)
    vague_phrases = [
        "pata nahi", "pata nahin", "samajh nahi", "samajh nahin", "don't know", "dont know",
        "unclear", "unsure", "kuch keh nahi", "kuch keh nahin", "kuch pata nahi", "kuch pata nahin",
        "ajeeb sa", "bas theek", "bas normal", "mood ajeeb", "samjh nahi", "samjh nahin",
        "kuch keh nahi sakte", "kuch keh nahin sakte"
    ]
    if any(vp in reply_clean for vp in vague_phrases) or reply_clean in ["pata nahi", "pata nahin", "no idea", "not sure"]:
        # Only clarify if there are no explicit frequency keywords
        if not any(kw in reply_clean for kw in ["kabhi kabhi", "daily", "har roz", "always"]):
            return None, "Response is vague and requires clarification.", True

    # 3. Explicit low frequency matches first to avoid shadowing by high frequency (e.g. "mostly normal bas thoda sad" should be 1)
    low_freq_distress = [
        "kabhi kabhi bhook nahi", "kabhi kabhi bhook nahin",
        "bas thoda sad", "bas thoda", "sometimes control",
        "sometimes worried", "sometimes energy"
    ]
    low_freq_keywords = [
        "kabhi kabhi", "kabhikabhi", "sometimes", "kai din", "kaee din", "few days", "some days",
        "occasionally", "thoda", "thoda sa", "thoda boht", "thoda bohat", "halka", "halka sa",
        "کئی دن", "کبھی کبھی", "چند دن", "تھوڑا"
    ]
    if any(kw in reply_clean for kw in low_freq_distress) or any(kw in reply_clean for kw in low_freq_keywords):
        return 1, "Low frequency response matched score 1", False

    # 4. Explicit moderate frequency matches (e.g. "aadhe se zyada") matched before raw "zyada"
    mod_freq_keywords = [
        "aadhe", "aadhey", "half", "more than half", "mostly", "ziada tar", "zyada tar",
        "half the time", "half time", "آدھے", "آدھے سے زیادہ", "زیادہ تر"
    ]
    if any(kw in reply_clean for kw in mod_freq_keywords):
        # But make sure it's not "mostly normal" which is score 0/1
        if "mostly normal" in reply_clean or "mostly fine" in reply_clean:
            return 1, "Mostly normal mapped to mild score 1", False
        return 2, "Moderate-high frequency response matched score 2", False

    # 5. Severe Symptom Distress without explicit frequency (e.g. "neend nahi aati", "control nahi hota")
    # This must be run before wellness to prevent false score-0 classifications
    if "control" in reply_clean and ("nahi" in reply_clean or "nahin" in reply_clean or "control" in reply_clean):
        # Wait, if they say "no control", it's severe worry
        return 3, "High distress response (unable to control worry)", False
    if "neend" in reply_clean and ("nahi" in reply_clean or "nahin" in reply_clean or "sleep" in reply_clean):
        return 3, "High distress response (insomnia/sleep issues)", False
    if "dil" in reply_clean and ("nahi" in reply_clean or "nahin" in reply_clean):
        return 3, "High distress response (loss of interest)", False

    # 6. High Frequency (Score 3)
    high_freq_distress = [
        "neend nahi aati bilkul bhi", "neend nahin aati bilkul bhi",
        "zero interest", "relax nahi kar pata", "relax nahin kar pata"
    ]
    high_freq_keywords = [
        "har waqt", "harwaqt", "daily", "always", "every day", "everyday", "har roz", "harroz",
        "bohat zyaada", "bohat zyada", "boht zyada", "boht zyaada", "buhat ziada", "buhat zyaada",
        "ziada", "zyada", "rozana", "constant", "constantly", "hamesha", "nearly every day",
        "تقریباً ہر روز", "ہر روز", "روزانہ", "ہمیشہ", "بہت زیادہ", "زیادہ"
    ]
    if any(kw in reply_clean for kw in high_freq_distress) or any(kw in reply_clean for kw in high_freq_keywords):
        return 3, "High frequency response matched score 3", False

    # 7. Explicit wellness / negation of symptom (Score 0)
    wellness_keywords = [
        "bilkul nahi", "bilkul nahin", "kabhi nahi", "kabhi nahin", "no", "never", "not at all",
        "zero", "no issue", "no problem", "fine", "absolutely fine", "all good", "perfect",
        "bilkul theek", "bilkul thik", "sab theek", "sab thik", "normal", "fit", "healthy",
        "no fear", "absolutely fine", "بالکل نہیں", "نہیں", "کبھی نہیں"
    ]
    if any(wk in reply_clean for wk in wellness_keywords) or reply_clean == "nahi" or reply_clean == "nahin":
        distress_keywords = ["neend", "sleep", "bhook", "appetite", "dil", "interest", "focus", "concentrate", "tension", "pareshan", "ghabrahat"]
        if not any(dk in reply_clean for dk in distress_keywords):
            return 0, "Negative response matched score 0", False

    # 8. Fallback distress indicator
    distress_keywords = ["neend", "sleep", "bhook", "appetite", "dil", "interest", "focus", "concentrate", "tension", "pareshan", "ghabrahat", "anxious", "nervous", "sad", "udasi", "udas"]
    if any(dk in reply_clean for dk in distress_keywords):
        return 1, "Symptom mentioned, defaulted to score 1", False

    return None, "Unable to map response to 0-3 scale via local heuristics.", True


def get_llm_config():
    """Retrieve the Gemini LLM configuration, or (None, None, None) if unset."""
    gemini_key = current_app.config.get('GEMINI_API_KEY')
    if gemini_key:
        return (
            gemini_key,
            current_app.config.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/'),
            current_app.config.get('GEMINI_MODEL', 'gemini-2.5-flash')
        )

    return None, None, None


@chat_bp.route('/extract-score', methods=['POST'])
def extract_score():
    """
    POST /api/chat/extract-score
    Body: { assessment_type, question, reply }
    Returns: { score, reasoning, needs_clarification }
    """
    data = request.get_json(silent=True) or {}
    assessment_type = data.get('assessment_type')
    question = data.get('question')
    reply = data.get('reply')

    if not assessment_type or not question or not reply:
        return jsonify({'error': 'assessment_type, question, and reply are required.'}), 400

    api_key, base_url, model = get_llm_config()

    # If API key is missing, fall back directly to local heuristics
    if not api_key:
        score, reasoning, needs_clarify = local_heuristic_extract_score(assessment_type, question, reply)
        return jsonify({
            'score': score,
            'reasoning': reasoning + " (local fallback)",
            'needs_clarification': needs_clarify
        }), 200

    # System instruction for score extraction
    system_prompt = (
        "You are an empathetic, clinical AI score extractor for Zehni Sukoon, a mental health platform in Pakistan.\n"
        "Your task is to analyze the user's free-text reply to a single screening question (from PHQ-9 or GAD-7) "
        "and determine a score from 0 to 3 based on the frequency they describe:\n"
        "- 0: Not at all / بالکل نہیں\n"
        "- 1: Several days / kabhi kabhi / some days / کئی دن\n"
        "- 2: More than half the days / half the time / aadhe se zyada din / آدھے سے زیادہ دن\n"
        "- 3: Nearly every day / daily / har roz / تقریباً ہر روز\n\n"
        "Rules:\n"
        "1. If the reply is vague, unrelated, or lacks enough information to pick 0, 1, 2, or 3, set 'score' to null and 'needs_clarification' to true.\n"
        "2. If they answer clearly, set 'score' to the correct integer and 'needs_clarification' to false.\n"
        "3. CRITICAL Rule for PHQ-9 Question 9 (thoughts of self-harm/suicide):\n"
        "   If there is ANY hint of self-harm, passive suicidal ideation, or ambiguity, DO NOT ask for clarification. "
        "   Map it immediately to a score of 1, 2, or 3 (flagging risk). Ambiguity on Question 9 must default to flagging risk (score >= 1, needs_clarification = false).\n\n"
        "Return ONLY a valid JSON object with the following format:\n"
        "{\n"
        "  \"score\": 0|1|2|3|null,\n"
        "  \"reasoning\": \"brief explanation of why this score was chosen\",\n"
        "  \"needs_clarification\": true|false\n"
        "}"
    )

    user_content = f"Question: {question}\nUser Reply: {reply}"

    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_content}
            ],
            'response_format': {'type': 'json_object'}
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        res_data = response.json()
        content = res_data['choices'][0]['message']['content']
        
        # Parse JSON from response
        parsed = json.loads(content)
        return jsonify({
            'score': parsed.get('score'),
            'reasoning': parsed.get('reasoning', ''),
            'needs_clarification': parsed.get('needs_clarification', False)
        }), 200

    except Exception as e:
        # Fallback to local heuristic on any failure
        score, reasoning, needs_clarify = local_heuristic_extract_score(assessment_type, question, reply)
        return jsonify({
            'score': score,
            'reasoning': f"Local fallback due to API error: {str(e)}",
            'needs_clarification': needs_clarify
        }), 200


@chat_bp.route('/screening-turn', methods=['POST'])
def screening_turn():
    """
    POST /api/chat/screening-turn
    Body: {
      assessment_type: 'phq9' | 'gad7',
      language: 'ur' | 'en',
      transcript: [{role: 'user'|'assistant', content: str}, ...],
      prior_coverage: {qN: {score, confidence, evidence}},   # echoed from last turn
      prior_clarifications: {qN: count},                     # echoed from last turn
      pending_item: 'qN' | null                              # what the last question explored
    }
    Returns: {
      ok, reply, coverage, unanswered, target_item, phase, crisis, complete,
      over_limit, turns_used, max_turns, clarifications, crisis_contacts
    }

    Stateless by design: the browser owns the conversation and replays it each
    turn, so no session table is needed and a refresh costs nothing. The guards
    below are deterministic - the model proposes coverage, the server disposes.
    A screening is never declared complete on the model's say-so.
    """
    data = request.get_json(silent=True) or {}
    assessment_type = data.get('assessment_type')
    language = data.get('language') if data.get('language') in ('ur', 'en') else 'ur'
    is_ur = language == 'ur'

    if assessment_type not in SCREENING_SPECS:
        return jsonify({'ok': False, 'error': 'assessment_type must be phq9 or gad7.'}), 400

    spec = SCREENING_SPECS[assessment_type]
    spec_map = _item_lookup(assessment_type)
    transcript = _sanitize_transcript(data.get('transcript'))
    turns_used = sum(1 for m in transcript if m['role'] == 'user')
    last_user_message = next((m['content'] for m in reversed(transcript)
                              if m['role'] == 'user'), '')
    # Independent of the provider: a cry for help must surface even if the LLM
    # is rate-limited, blocked, or entirely down.
    local_crisis = _local_crisis_signal(last_user_message)

    prior_coverage = data.get('prior_coverage')
    coverage = _validated_coverage(
        prior_coverage if isinstance(prior_coverage, dict) else {},
        spec_map, {}, require_evidence=False
    )

    clarifications = {}
    raw_clar = data.get('prior_clarifications')
    if isinstance(raw_clar, dict):
        for key, value in raw_clar.items():
            if key in spec_map:
                try:
                    clarifications[key] = max(0, int(value))
                except (TypeError, ValueError):
                    pass

    pending_key = data.get('pending_item')
    pending_item = spec_map.get(pending_key) if pending_key in spec_map else None

    unavailable = {
        'crisis_contacts': CRISIS_CONTACTS,
        'turns_used': turns_used,
        'max_turns': SCREENING_MAX_USER_TURNS,
    }
    api_key, base_url, model = get_llm_config()
    if not api_key:
        # Decision: never fake a conversation with scripted keyword replies.
        # Say what happened and hand over to the standard form.
        return jsonify(dict(unavailable, **{
            'ok': False,
            'reason': 'llm_unavailable',
            'transient': False,
            'crisis': local_crisis,
            'reply': (
                _crisis_fallback(language, last_user_message) if local_crisis else
                ('معاف کیجیے، آج بات چیت والے طریقے کے لیے ضروری سروس دستیاب نہیں۔ '
                 'آپ یہ جانچ مختصر فارم کے ذریعے آسانی سے مکمل کر سکتے ہیں۔'
                 if is_ur else
                 'I am sorry - the conversational service is unavailable right now. '
                 'You can finish this check comfortably using the short written form instead.')
            ),
        })), 200

    unanswered_now = [i for i in spec if i['key'] not in coverage]
    system_prompt = _build_screening_system_prompt(
        'PHQ-9' if assessment_type == 'phq9' else 'GAD-7', spec, unanswered_now,
        pending_item, turns_used, SCREENING_MAX_USER_TURNS, language
    )
    messages = [{'role': 'system', 'content': system_prompt}]
    messages.extend({'role': m['role'], 'content': m['content']} for m in transcript)
    if not transcript:
        # The opening turn has no user message yet, and the OpenAI-compatible
        # providers reject a contentless request (Gemini answers 400 "contents is
        # not specified"). This seed never reaches the browser - it only prompts
        # the model to write the first line of the conversation.
        messages.append({'role': 'user', 'content': OPENING_SEED})

    parsed = None
    failure_reason = 'llm_error'
    # One quiet retry: this prompt is long and the provider rate-limits hard, so
    # failing the whole conversation on the first blip would be unkind. If both
    # attempts fail we still degrade honestly to the written form.
    for attempt in (1, 2):
        try:
            content = _call_llm(api_key, base_url, model, messages,
                                json_mode=True, timeout=30 if attempt == 1 else 45)
            candidate = _extract_json_object(content)
            if not isinstance(candidate, dict):
                raise ValueError('model returned a non-object')
            parsed = candidate
            break
        except Exception as exc:
            kind, delay = _classify_llm_failure(exc)
            body = getattr(getattr(exc, 'response', None), 'text', '') or ''
            print(f"[Chat BP] screening-turn attempt {attempt} failed ({kind}): {exc} {body[:200]}")
            failure_reason = {'config': 'llm_unavailable',
                              'exhausted': 'llm_quota_exhausted'}.get(kind, 'llm_error')
            if kind == 'transient' and attempt == 1:
                # Honour the provider's own hint, but never stall a worker for long.
                time.sleep(min(max(delay or 3.0, 1.0), 10.0))
            else:
                break

    if parsed is None:
        if local_crisis:
            # The provider is failing but someone just asked for help: answer in
            # our own words and reveal the helplines. Coverage is left as it was,
            # so the screening can resume cleanly once the provider recovers.
            rescue = dict(coverage)
            if 'q9' in spec_map and rescue.get('q9', {}).get('score', 0) < 1:
                rescue['q9'] = {
                    'score': 1,
                    'confidence': 'high',
                    'evidence': 'crisis phrase detected without the model',
                }
            rescue_unanswered = [i['key'] for i in spec if i['key'] not in rescue]
            return jsonify({
                'ok': True,
                'degraded': True,
                'reply': _crisis_fallback(language, last_user_message),
                'coverage': rescue,
                'unanswered': rescue_unanswered,
                'target_item': rescue_unanswered[0] if rescue_unanswered else None,
                'phase': 'asking',
                'crisis': True,
                'complete': False,
                'over_limit': False,
                'turns_used': turns_used,
                'max_turns': SCREENING_MAX_USER_TURNS,
                'clarifications': clarifications,
                'crisis_contacts': CRISIS_CONTACTS,
            }), 200

        stalled = failure_reason == 'llm_error'
        return jsonify(dict(unavailable, **{
            'ok': False,
            'reason': failure_reason,
            'transient': stalled,
            'crisis': local_crisis,
            'reply': (
                ('ایک لمحاتی رکاوٹ آئی، میں دوبارہ کوشش کر رہی ہوں۔' if is_ur else
                 'That took a moment too long - let me try again.')
                if stalled else
                ('معاف کیجیے، بات چیت والے طریقے کے لیے ضروری سروس دستیاب نہیں۔ '
                 'آپ یہ جانچ مختصر فارم کے ذریعے آسانی سے مکمل کر سکتے ہیں۔' if is_ur else
                 'I am sorry - the conversational service is unavailable right now. '
                 'You can finish this check comfortably using the short written form instead.')
            ),
        })), 200

    # ── Deterministic guards ────────────────────────────────────
    spoken_by_user = _user_text(transcript)
    merged = _validated_coverage(parsed.get('coverage'), spec_map, coverage, spoken_by_user)

    # Crisis is only ever about what the USER said. Left to itself the model can
    # flag crisis from its own question, which would surface a helpline card
    # nobody asked for and then, via the q9 floor below, end the conversation the
    # very moment it raised the subject. So: either the local phrase floor caught
    # it, or the model has to point at the person's own words.
    model_crisis = bool(parsed.get('crisis')) and _grounded_in_user(
        str(parsed.get('crisis_evidence', '')), spoken_by_user)
    crisis = local_crisis or model_crisis

    # Safety floor: a crisis can never leave q9 reading "not at all". It only
    # raises a score the user already gave. It deliberately never manufactures
    # coverage, so an q9 that has not been answered stays unanswered and still
    # gets asked - rather than being quietly filled in and closing the chat.
    if crisis and 'q9' in merged and merged['q9'].get('score', 0) < 1:
        merged['q9'] = {
            'score': 1,
            'confidence': merged['q9'].get('confidence', 'high'),
            'evidence': merged['q9'].get('evidence') or 'crisis signal in the user\'s own words',
        }

    unanswered = [i['key'] for i in spec if i['key'] not in merged]

    # Someone who has already been gently probed twice gets a conservative score
    # rather than a third question - except a crisis item, which is always >= 1.
    for key in list(unanswered):
        if clarifications.get(key, 0) >= MAX_CLARIFY_PER_ITEM:
            merged[key] = {
                'score': max(CLARIFY_SNAP_SCORE, 1) if (key == 'q9' and crisis) else CLARIFY_SNAP_SCORE,
                'confidence': 'low',
                'evidence': 'unresolved after clarification - scored conservatively as several days',
            }
    unanswered = [i['key'] for i in spec if i['key'] not in merged]

    # The model's own "complete" flag is ignored: completion is derived purely
    # from whether every clinical item resolved.
    target_key = parsed.get('target_item')
    if unanswered:
        if target_key not in unanswered:
            target_key = unanswered[0]
        phase = str(parsed.get('phase') or 'asking').strip().lower()
        if phase not in ('asking', 'clarifying'):
            phase = 'asking'
        if phase == 'clarifying':
            clarifications[target_key] = clarifications.get(target_key, 0) + 1
        complete = False
    else:
        target_key = None
        phase = 'closing'
        complete = True

    reply = _tidy_reply(parsed.get('reply'))
    if not reply:
        reply = ('میں یہاں ہوں۔ آہستہ آہستہ بتائیے۔' if is_ur
                 else "I'm here. Take your time and tell me.")

    return jsonify({
        'ok': True,
        'reply': reply,
        'coverage': merged,
        'unanswered': unanswered,
        'target_item': target_key,
        'phase': phase,
        'crisis': crisis,
        'complete': complete,
        'over_limit': bool(unanswered) and turns_used >= SCREENING_MAX_USER_TURNS,
        'turns_used': turns_used,
        'max_turns': SCREENING_MAX_USER_TURNS,
        'clarifications': clarifications,
        'crisis_contacts': CRISIS_CONTACTS,
    }), 200


@chat_bp.route('/companion', methods=['POST'])
def companion():
    """
    POST /api/chat/companion
    Body: { message, history }
    """
    data = request.get_json(silent=True) or {}
    message = data.get('message')
    history = data.get('history', [])

    if not message:
        return jsonify({'error': 'message is required.'}), 400

    api_key, base_url, model = get_llm_config()

    if not api_key:
        return jsonify({
            'response': "I am here with you. Please feel free to tell me more about how you are feeling."
        }), 200

    # Companion system prompt
    system_prompt = (
        "You are Humdum (ہمدم), an empathetic, caring, non-clinical AI companion for Zehni Sukoon in Pakistan.\n"
        "Your tone must stay calm, supportive, non-clinical, and extremely safe.\n"
        "Use simple language. Respond in the same language the user writes in (Urdu or English/Roman Urdu).\n"
        "Always remind them gently if they are in crisis that they can call the helpline. Never make diagnostic claims."
    )

    # Format messages for the chat model
    messages = [{'role': 'system', 'content': system_prompt}]
    for msg in history[-10:]: # Keep last 10 messages for context
        role = 'user' if msg.get('role') == 'user' else 'assistant'
        messages.append({'role': role, 'content': msg.get('content', '')})
    
    # Append current message if not already in history
    if not messages or messages[-1]['content'] != message:
        messages.append({'role': 'user', 'content': message})

    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        payload = {
            'model': model,
            'messages': messages
        }
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        res_data = response.json()
        bot_response = res_data['choices'][0]['message']['content']
        return jsonify({'response': bot_response}), 200

    except Exception as e:
        return jsonify({
            'response': "I hear you. I'm here to listen. Tell me more about what has been on your mind."
        }), 200
