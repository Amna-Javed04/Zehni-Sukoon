"""Offline tests for the multi-provider LLM layer (backend/llm_client.py).

Run with:  python test_llm_providers.py

Every HTTP call is mocked - no network, no quota, no keys needed. They cover:
  1. providers without an API key are skipped
  2. failover follows the configured order
  3. 429 fails over IMMEDIATELY (exactly one request to the throttled provider)
  4. timeouts get at most one quick same-provider retry, then fail over
  5. a 400 that looks extras-related retries once WITHOUT the extras;
     a server-side json_validate_failed 400 (prose instead of JSON) is
     salvaged when the rejected generation still held JSON, else retried
     with a JSON-only reminder appended, while a plain config 400 fails
     over at once
  6. all providers failing raises LLMError with a per-provider trail
  7. request payload shape (thinking off, JSON mode, max_tokens)
  8. logging carries provider/model/latency/tokens, never message content
  9. route level: the crisis floor survives ALL providers failing
 10. route level: honest degradation (form offered) when all providers fail11. route level: daily turn cap + crisis bypass of the cap
12. no provider configured at all -> llm_unavailable / local heuristic
13. every route caps max_tokens (Groq OTPM reservation: a JSON blip must
    not consume the output-token budget its own retry needs) and Groq's
    "try again in ~21s" OTPM hint classifies as transient, not exhausted
"""
import contextlib
import json
import os
import sys
import unittest.mock

sys.path.insert(0, ".")

import requests  # noqa: E402

import backend.llm_client as llm  # noqa: E402
import backend.routes.chat as chat  # noqa: E402
from backend.app import create_app  # noqa: E402

app = create_app()
FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(name)
    print(f"  [{status}] {name}{('  -> ' + str(detail)) if detail and not cond else ''}")


# ── Environment isolation ─────────────────────────────────────────────
@contextlib.contextmanager
def llm_env(**env):
    """Run with LLM-related env vars replaced entirely by `env`."""
    saved = dict(os.environ)
    for key in [k for k in os.environ if k.startswith(('LLM_', 'QWEN_', 'GROQ_', 'GEMINI_'))]:
        os.environ.pop(key, None)
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


# ── Fake transport ────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        return self._payload


def ok_response(content='{"reply": "ok"}'):
    return FakeResponse(200, {
        'choices': [{'message': {'content': content}}],
        'usage': {'prompt_tokens': 12, 'completion_tokens': 7},
    })


def error_response(status, message="err"):
    return FakeResponse(status, {'error': {'message': message}},
                        text=json.dumps({'error': {'message': message}}))


def route_table(routes):
    """routes: [(url_prefix, handler(payload) -> FakeResponse | Exception)]."""
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({'url': url, 'payload': json, 'headers': headers,
                      'timeout': timeout})
        for prefix, handler in routes:
            if url.startswith(prefix):
                result = handler(json)
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected url {url}")

    return fake_post, calls


# ── 1. Providers with no key are skipped ──────────────────────────────
print("=" * 74)
print("1. Providers without an API key are skipped entirely")
with llm_env(LLM_PROVIDERS="qwen,groq,gemini", GROQ_API_KEY="g-key"):
    providers = llm.configured_providers()
    check("only groq survives", [p['name'] for p in providers] == ['groq'], providers)
    check("groq default base url",
          providers[0]['base_url'] == 'https://api.groq.com/openai/v1')
    check("groq default model", providers[0]['model'] == 'openai/gpt-oss-120b')
with llm_env():
    check("no keys at all -> nothing configured", llm.configured() is False)
    try:
        llm.chat_completion([{'role': 'user', 'content': 'hi'}])
        check("no providers raises LLMError", False)
    except llm.LLMError as exc:
        check("no providers raises LLMError", 'no LLM provider configured' in str(exc))

# ── 2+3. Failover order; 429 fails over immediately ───────────────────
print("=" * 74)
print("2. 429 fails over to the next provider immediately, in order")
fake_post, calls = route_table([
    ('https://qwen.example', lambda p: error_response(429, 'rate limited')),
    ('https://groq.example', lambda p: ok_response('{"reply": "from groq"}')),
])
with llm_env(LLM_PROVIDERS="qwen,groq",
             QWEN_API_KEY='q-key', QWEN_BASE_URL='https://qwen.example/v1',
             QWEN_MODEL='qwen-test',
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='groq-test'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    result = llm.chat_completion([{'role': 'user', 'content': 'hello'}], json_mode=True)
    check("second provider answered", result['provider'] == 'groq', result['provider'])
    check("exactly one call to the throttled provider",
          sum(1 for c in calls if 'qwen.example' in c['url']) == 1, calls)
    check("exactly one call to groq",
          sum(1 for c in calls if 'groq.example' in c['url']) == 1)
    check("throttled provider was tried first", 'qwen' in calls[0]['url'])
    check("json mode requested",
          calls[-1]['payload'].get('response_format') == {'type': 'json_object'})

# ── 4. Timeouts: one quick retry, then fail over ──────────────────────
print("=" * 74)
print("3. Timeouts get one same-provider retry, then fail over")
fake_post, calls = route_table([
    ('https://qwen.example', lambda p: requests.Timeout('read timed out')),
    ('https://groq.example', lambda p: ok_response('{"reply": "groq again"}')),
])
with llm_env(LLM_PROVIDERS="qwen,groq",
             QWEN_API_KEY='q-key', QWEN_BASE_URL='https://qwen.example/v1', QWEN_MODEL='m',
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1', GROQ_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    result = llm.chat_completion([{'role': 'user', 'content': 'hello'}])
    check("recovered on groq", result['provider'] == 'groq')
    check("qwen retried exactly once (2 calls)",
          sum(1 for c in calls if 'qwen.example' in c['url']) == 2,
          [c['url'] for c in calls])
    check("groq called once", sum(1 for c in calls if 'groq.example' in c['url']) == 1)

print("=" * 74)
print("4. Every provider timing out raises LLMError with a trail")
fake_post, calls = route_table([
    ('https://qwen.example', lambda p: requests.Timeout('read timed out')),
])
with llm_env(LLM_PROVIDERS="qwen",
             QWEN_API_KEY='q-key', QWEN_BASE_URL='https://qwen.example/v1', QWEN_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    try:
        llm.chat_completion([{'role': 'user', 'content': 'hello'}])
        check("LLMError raised", False)
    except llm.LLMError as exc:
        check("LLMError raised", True)
        check("two attempts recorded (the one quick retry)",
              len(exc.attempts) == 2, exc.attempts)
        check("both attempts marked transient",
              all(a['kind'] == 'transient' for a in exc.attempts))

# ── 5. 400 on extras -> one retry without the extras ──────────────────
print("=" * 74)
print("5. A provider rejecting the thinking-disable extra is retried without it")


def qwen_400_on_extras(payload):
    if 'enable_thinking' in payload:
        return error_response(400, 'enable_thinking not supported')
    return ok_response('{"reply": "qwen without extras"}')


fake_post, calls = route_table([('https://qwen.example', qwen_400_on_extras)])
with llm_env(LLM_PROVIDERS="qwen",
             QWEN_API_KEY='q-key', QWEN_BASE_URL='https://qwen.example/v1', QWEN_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    result = llm.chat_completion([{'role': 'user', 'content': 'hello'}])
    check("recovered on the same provider", result['provider'] == 'qwen')
    check("first call sent the extra", 'enable_thinking' in calls[0]['payload'])
    check("second call dropped the extra", 'enable_thinking' not in calls[1]['payload'])
    check("exactly two calls", len(calls) == 2)

# ── 5b. Server-side JSON validation blip -> one as-is retry ───────────
print("=" * 74)
print("5b. A json_validate_failed 400 is salvaged or retried with a nudge")

_GROQ_JSON_BLIP = {'n': 0}


def groq_json_blip(payload):
    _GROQ_JSON_BLIP['n'] += 1
    if _GROQ_JSON_BLIP['n'] == 1:
        return FakeResponse(400, {}, text=json.dumps({
            'error': {
                'message': 'Failed to generate JSON. Please adjust your prompt.',
                'type': 'invalid_request_error',
                'code': 'json_validate_failed',
                'failed_generation': 'It sounds like things have felt flat.',
            },
        }))
    return ok_response('{"reply": "groq recovered"}')


fake_post, calls = route_table([('https://groq.example', groq_json_blip)])
with llm_env(LLM_PROVIDERS="groq",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1', GROQ_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    result = llm.chat_completion([{'role': 'user', 'content': 'hello'}])
    check("recovered after the JSON blip", result['provider'] == 'groq')
    check("retried the same provider (exactly two calls)",
          len(calls) == 2, len(calls))
    first, retry = calls[0]['payload'], calls[1]['payload']
    check("retry differs only by an appended JSON-only nudge",
          retry['messages'][:-1] == first['messages']
          and retry['messages'][-1]['role'] == 'system'
          and 'ONLY' in retry['messages'][-1]['content']
          and {k: v for k, v in retry.items() if k != 'messages'} ==
              {k: v for k, v in first.items() if k != 'messages'},
          retry)

# Two consecutive blips must still recover - blips have their own budget.
_DOUBLE = {'n': 0}


def groq_double_blip(payload):
    _DOUBLE['n'] += 1
    if _DOUBLE['n'] <= 2:
        return FakeResponse(400, {}, text=json.dumps({
            'error': {'message': 'Failed to generate JSON.',
                      'code': 'json_validate_failed',
                      'failed_generation': 'plain prose again'},
        }))
    return ok_response('{"reply": "third attempt lands"}')


fake_post, calls = route_table([('https://groq.example', groq_double_blip)])
with llm_env(LLM_PROVIDERS="groq",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    result = llm.chat_completion([{'role': 'user', 'content': 'hello'}])
    check("two consecutive JSON blips recover on the 3rd attempt",
          result['provider'] == 'groq' and len(calls) == 3, len(calls))

# A blip whose rejected generation chatted a lead-in BEFORE its JSON is
# salvaged: that object is exactly what the caller's tolerant parser would
# have accepted, so the turn is good without spending a retry.
_SALVAGE_BODY = json.dumps({
    'error': {
        'message': 'Failed to generate JSON. Please adjust your prompt.',
        'type': 'invalid_request_error',
        'code': 'json_validate_failed',
        'failed_generation': ('That sounds really tough.\n'
                              '{"reply": "I am here with you.", '
                              '"target_item": null}'),
    },
})
fake_post, calls = route_table([
    ('https://groq.example', lambda p: FakeResponse(400, {}, text=_SALVAGE_BODY))])
with llm_env(LLM_PROVIDERS="groq",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    result = llm.chat_completion([{'role': 'user', 'content': 'hello'}],
                                 json_mode=True)
    check("prose+JSON blip salvaged without any retry",
          len(calls) == 1 and result['provider'] == 'groq'
          and 'I am here with you' in result['content'], result)

fake_post, calls = route_table([
    ('https://groq.example', lambda p: error_response(400, 'malformed request')),
    ('https://gemini.example', lambda p: ok_response('{"reply": "gemini"}')),
])
with llm_env(LLM_PROVIDERS="groq,gemini",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='openai/gpt-oss-120b',
             GEMINI_API_KEY='g2-key', GEMINI_BASE_URL='https://gemini.example/v1',
             GEMINI_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    result = llm.chat_completion([{'role': 'user', 'content': 'hello'}])
    groq_calls = sum(1 for c in calls if 'groq.example' in c['url'])
    check("plain config 400 never retries as-is (one without-extras try)",
          groq_calls == 2, groq_calls)
    check("effort field sent first, dropped on the retry",
          'reasoning_effort' in calls[0]['payload']
          and 'reasoning_effort' not in calls[1]['payload'])
    check("failed over to gemini", result['provider'] == 'gemini')

# ── 6. All providers failing -> LLMError carrying the last response ───
print("=" * 74)
print("6. All providers failing raises LLMError and preserves the last response")
fake_post, calls = route_table([
    ('https://qwen.example', lambda p: error_response(429, 'rate limited')),
    ('https://groq.example', lambda p: error_response(500, 'upstream boom')),
])
with llm_env(LLM_PROVIDERS="qwen,groq",
             QWEN_API_KEY='q-key', QWEN_BASE_URL='https://qwen.example/v1', QWEN_MODEL='m',
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1', GROQ_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    try:
        llm.chat_completion([{'role': 'user', 'content': 'hello'}])
        check("LLMError raised", False)
    except llm.LLMError as exc:
        check("LLMError raised", True)
        names = [a['provider'] for a in exc.attempts]
        check("trail names both providers", names[0] == 'qwen' and 'groq' in names, names)
        check("last response preserved for classification",
              getattr(exc, 'response', None) is not None)
        # The existing chat.py classification must still work on this error.
        check("chat.py classifies it as transient",
              chat._classify_llm_failure(exc)[0] == 'transient')

# ── 7. Payload shape ──────────────────────────────────────────────────
print("=" * 74)
print("7. Request payloads: thinking off, JSON mode, bounded reply size")
fake_post, calls = route_table([('https://gemini.example',
                                 lambda p: ok_response('{}'))])
with llm_env(LLM_PROVIDERS="gemini",
             GEMINI_API_KEY='g-key', GEMINI_BASE_URL='https://gemini.example/v1',
             GEMINI_MODEL='gemini-test', LLM_MAX_TOKENS='321'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    llm.chat_completion([{'role': 'user', 'content': 'hi'}], json_mode=True)
    payload = calls[0]['payload']
    check("gemini thinking disabled via reasoning_effort",
          payload.get('reasoning_effort') == 'none', payload)
    check("max_tokens bounded", payload.get('max_tokens') == 321)
    check("json mode asks for low temperature (compliance, not creativity)",
          payload.get('temperature') == 0.3, payload)
    check("model from env", payload.get('model') == 'gemini-test')
    check("no qwen-style extra on gemini", 'enable_thinking' not in payload)

# Non-JSON calls (the companion chat) keep the provider's default warmth.
fake_post, calls = route_table([('https://gemini.example',
                                 lambda p: ok_response('I am here.'))])
with llm_env(LLM_PROVIDERS="gemini",
             GEMINI_API_KEY='g-key', GEMINI_BASE_URL='https://gemini.example/v1',
             GEMINI_MODEL='gemini-test'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    llm.chat_completion([{'role': 'user', 'content': 'hi'}])
    check("no temperature override on non-JSON calls",
          'temperature' not in calls[0]['payload'], calls[0]['payload'])

# Groq: reasoning effort is env-configurable, defaults to low, and is only
# sent where Groq documents support for it (GPT-OSS models).
fake_post, calls = route_table([('https://groq.example',
                                 lambda p: ok_response('{}'))])
with llm_env(LLM_PROVIDERS="groq",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='openai/gpt-oss-120b'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    llm.chat_completion([{'role': 'user', 'content': 'hi'}])
    check("groq reasoning effort defaults to low",
          calls[0]['payload'].get('reasoning_effort') == 'low', calls[0]['payload'])

# Non-gpt-oss Groq models must NOT receive the field (docs + our A/B: sending
# it to qwen measurably hurt json_object compliance).
with llm_env(LLM_PROVIDERS="groq",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='qwen/qwen3.8-27b'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    llm.chat_completion([{'role': 'user', 'content': 'hi'}])
    check("qwen on groq gets NO reasoning_effort (json reliability)",
          'reasoning_effort' not in calls[-1]['payload'], calls[-1]['payload'])

with llm_env(LLM_PROVIDERS="groq",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='openai/gpt-oss-120b', GROQ_REASONING_EFFORT='high'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    llm.chat_completion([{'role': 'user', 'content': 'hi'}])
    check("groq reasoning effort honours env override",
          calls[-1]['payload'].get('reasoning_effort') == 'high')

with llm_env(LLM_PROVIDERS="groq",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='openai/gpt-oss-120b', GROQ_REASONING_EFFORT='off'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    llm.chat_completion([{'role': 'user', 'content': 'hi'}])
    check("groq reasoning effort omitted when set to off",
          'reasoning_effort' not in calls[-1]['payload'], calls[-1]['payload'])

# A Groq model that rejects the field must still recover without extras.
def groq_400_on_effort(payload):
    if 'reasoning_effort' in payload:
        return error_response(400, 'reasoning_effort not supported')
    return ok_response('{"reply": "recovered"}')

fake_post, calls = route_table([('https://groq.example', groq_400_on_effort)])
with llm_env(LLM_PROVIDERS="groq",
             GROQ_API_KEY='g-key', GROQ_BASE_URL='https://groq.example/v1',
             GROQ_MODEL='openai/gpt-oss-120b'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    result = llm.chat_completion([{'role': 'user', 'content': 'hi'}])
    check("groq rejecting the effort field recovers without extras",
          result['provider'] == 'groq' and len(calls) == 2
          and 'reasoning_effort' in calls[0]['payload']
          and 'reasoning_effort' not in calls[1]['payload'])

# ── 8. Logging: metadata in, content out of the picture ───────────────
print("=" * 74)
print("8. Logs carry provider/latency/tokens and never message content")
fake_post, calls = route_table([('https://qwen.example', lambda p: ok_response('{}'))])
with llm_env(LLM_PROVIDERS="qwen",
             QWEN_API_KEY='q-key', QWEN_BASE_URL='https://qwen.example/v1', QWEN_MODEL='m'), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    import logging as _logging
    records = []
    handler = _logging.Handler()
    handler.emit = records.append
    logger = _logging.getLogger('zs.llm')
    logger.addHandler(handler)
    logger.setLevel(_logging.INFO)
    try:
        llm.chat_completion([{'role': 'user', 'content': 'SECRET-USER-TEXT-9137'}])
    finally:
        logger.removeHandler(handler)
    text = ' '.join(r.getMessage() for r in records)
    check("log names the provider", 'provider=qwen' in text, text)
    check("log records latency", 'latency_ms=' in text)
    check("log records token counts", 'prompt_tokens=' in text)
    check("log never contains message content", 'SECRET-USER-TEXT-9137' not in text)


# ── Route-level tests: crisis floor, degradation, daily cap ───────────
GOOD_TURN = json.dumps({
    "reply": "Theek hai, aur bataiye.",
    "coverage": {"q1": {"score": 1, "confidence": "high", "evidence": "theek nahi hoon"}},
    "target_item": "q2", "phase": "asking", "crisis": False, "complete": False,
})


def post_turn(body, env=None, side_effect=None, config=None):
    """POST one screening-turn with a controlled LLM and fresh ledger."""
    chat._DAILY_TURN_LEDGER.clear()
    env = env or {'LLM_PROVIDERS': 'qwen', 'QWEN_API_KEY': 'k',
                  'QWEN_BASE_URL': 'https://qwen.example/v1', 'QWEN_MODEL': 'm'}
    effect = side_effect if side_effect is not None else (lambda *a, **k: {'content': GOOD_TURN})
    for key, value in (config or {}).items():
        app.config[key] = value
    with llm_env(**env), \
            unittest.mock.patch.object(llm, 'chat_completion', side_effect=effect):
        with app.test_client() as c:
            return c.post('/api/chat/screening-turn', json=body)


print("=" * 74)
print("9. The crisis floor survives every provider failing")
quota_error = llm.LLMError(
    'all failed',
    last_error=requests.HTTPError('HTTP 429', response=error_response(
        429, 'Please retry in 55.0s')))
r = post_turn({'assessment_type': 'phq9', 'language': 'ur',
               'transcript': [{'role': 'user', 'content': 'kaash main hoti hi na'}]},
              side_effect=lambda *a, **k: (_ for _ in ()).throw(quota_error))
d = r.get_json()
check("http 200", r.status_code == 200, r.status_code)
check("ok true (rescued, not failed)", d.get('ok') is True, d)
check("crisis true", d.get('crisis') is True)
check("q9 rescued to >= 1", d.get('coverage', {}).get('q9', {}).get('score', 0) >= 1)
check("helplines attached", len(d.get('crisis_contacts', [])) == 1)
check("rescue copy in the user's script", 'Aap ne jo kaha' in (d.get('reply') or ''))

print("=" * 74)
print("10. All providers failing degrades honestly to the written form")
r = post_turn({'assessment_type': 'phq9', 'language': 'ur',
               'transcript': [{'role': 'user', 'content': 'main thaki hoon'}]},
              side_effect=lambda *a, **k: (_ for _ in ()).throw(quota_error))
d = r.get_json()
check("ok false", d.get('ok') is False)
check("reason names the quota", d.get('reason') == 'llm_quota_exhausted', d.get('reason'))
check("form offered", 'فارم' in (d.get('reply') or ''))
check("no scripted empathy invented", not d.get('degraded'))

print("=" * 74)
print("11. Daily turn cap blocks ordinary turns but never a crisis")


def _ok(*args, **kwargs):
    return {'content': GOOD_TURN}


# Drive the cap within ONE configured budget (no ledger clearing in between).
chat._DAILY_TURN_LEDGER.clear()
app.config['CHAT_TURNS_PER_GUEST_DAY'] = 2
with llm_env(LLM_PROVIDERS='qwen', QWEN_API_KEY='k',
             QWEN_BASE_URL='https://qwen.example/v1', QWEN_MODEL='m'), \
        unittest.mock.patch.object(llm, 'chat_completion', side_effect=_ok):
    with app.test_client() as c:
        t1 = c.post('/api/chat/screening-turn', json={
            'assessment_type': 'phq9', 'language': 'ur',
            'transcript': [{'role': 'user', 'content': 'pehla jawab'}]}).get_json()
        t2 = c.post('/api/chat/screening-turn', json={
            'assessment_type': 'phq9', 'language': 'ur',
            'transcript': [{'role': 'user', 'content': 'doosra jawab'}]}).get_json()
        capped = c.post('/api/chat/screening-turn', json={
            'assessment_type': 'phq9', 'language': 'ur',
            'transcript': [{'role': 'user', 'content': 'teesra jawab'}]}).get_json()
        crisis_over_cap = c.post('/api/chat/screening-turn', json={
            'assessment_type': 'phq9', 'language': 'ur',
            'transcript': [{'role': 'user', 'content': 'kaash main hoti hi na'}]}).get_json()
check("first turn allowed", t1.get('ok') is True, t1)
check("second turn allowed", t2.get('ok') is True, t2)
check("third turn capped", capped.get('ok') is False and
      capped.get('reason') == 'daily_limit', capped)
check("cap reply points to the form", 'فارم' in (capped.get('reply') or ''))
check("crisis bypasses the cap", crisis_over_cap.get('ok') is True, crisis_over_cap)
check("crisis over cap still flags crisis", crisis_over_cap.get('crisis') is True)

print("=" * 74)
print("12. No provider configured: screening-turn degrades, extract-score heuristics")
chat._DAILY_TURN_LEDGER.clear()
with llm_env():
    with app.test_client() as c:
        t = c.post('/api/chat/screening-turn', json={
            'assessment_type': 'phq9', 'language': 'ur',
            'transcript': [{'role': 'user', 'content': 'main theek nahi'}]}).get_json()
        e = c.post('/api/chat/extract-score', json={
            'assessment_type': 'phq9', 'question': 'q', 'reply': 'kabhi kabhi'}).get_json()
check("screening-turn: llm_unavailable", t.get('reason') == 'llm_unavailable', t)
check("extract-score: local fallback used", 'local fallback' in (e.get('reasoning') or ''),
      e)

# ── 13. OTPM output-token caps + retry-hint classification ────────────
# Groq's free tier reserves max_tokens from a 1,000 output-tokens/min budget
# per request. A JSON blip rambles prose to the FULL cap, so an uncapped
# (700) blip leaves no OTPM room for its own as-is retry - the retry 429s
# and a recoverable blip becomes a dead turn. These checks pin the caps that
# keep blip+retry inside the window.
print("=" * 74)
print("13. Route OTPM caps: screening 400, extraction 200, companion 400")

GOOD_SCORE = json.dumps({"score": 1, "reasoning": "occasionally", "needs_clarification": False})
env_qwen = {'LLM_PROVIDERS': 'qwen', 'QWEN_API_KEY': 'k',
            'QWEN_BASE_URL': 'https://qwen.example/v1', 'QWEN_MODEL': 'm'}

chat._DAILY_TURN_LEDGER.clear()
fake_post, calls = route_table([('https://qwen.example',
                                 lambda p: ok_response(GOOD_TURN))])
with llm_env(**env_qwen), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    with app.test_client() as c:
        r = c.post('/api/chat/screening-turn', json={
            'assessment_type': 'phq9', 'language': 'en',
            'transcript': [{'role': 'user', 'content': 'I sleep badly'}]})
check("screening turn ok", r.get_json().get('ok') is True, r.get_json())
check("screening turn reserves <= 400 output tokens",
      calls[0]['payload'].get('max_tokens') == 400, calls[0]['payload'])
check("screening turn keeps json mode",
      calls[0]['payload'].get('response_format') == {'type': 'json_object'})

fake_post, calls = route_table([('https://qwen.example',
                                 lambda p: ok_response(GOOD_SCORE))])
with llm_env(**env_qwen), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    with app.test_client() as c:
        e = c.post('/api/chat/extract-score', json={
            'assessment_type': 'phq9', 'question': 'Little interest?',
            'reply': 'kabhi kabhi'}).get_json()
check("extract-score scored by the LLM", e.get('score') == 1, e)
check("extract-score reserves <= 200 output tokens",
      calls[0]['payload'].get('max_tokens') == 200, calls[0]['payload'])

fake_post, calls = route_table([('https://qwen.example',
                                 lambda p: ok_response('I am here with you.'))])
with llm_env(**env_qwen), \
        unittest.mock.patch.object(llm.requests, 'post', side_effect=fake_post):
    with app.test_client() as c:
        comp = c.post('/api/chat/companion', json={
            'message': 'hello', 'history': []}).get_json()
check("companion answers", 'here' in (comp.get('response') or ''), comp)
check("companion reserves <= 400 output tokens",
      calls[0]['payload'].get('max_tokens') == 400, calls[0]['payload'])

# Groq OTPM 429s say "try again in ~21s" and clear within that minute: one
# quiet retry is worth it, so they must classify as transient (<= 25s
# ceiling), while a long-window hint stays exhausted.
otpm_error = llm.LLMError(
    'all failed',
    last_error=requests.HTTPError('HTTP 429', response=error_response(
        429, 'Rate limit reached ... output tokens per minute (OTPM): Limit '
             '1000, Used 658, Requested 700. Please try again in 21.48s.')))
check("Groq OTPM hint (~21s) classifies as transient",
      chat._classify_llm_failure(otpm_error)[0] == 'transient',
      chat._classify_llm_failure(otpm_error))
long_hint = llm.LLMError(
    'all failed',
    last_error=requests.HTTPError('HTTP 429', response=error_response(
        429, 'Please try again in 55.0s')))
check("long-window hint still classifies as exhausted",
      chat._classify_llm_failure(long_hint)[0] == 'exhausted')

print("=" * 74)
if FAILURES:
    print(f"{len(FAILURES)} PROVIDER TEST(S) FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PROVIDER TESTS PASSED")
