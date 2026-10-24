"""
llm_client.py — the single LLM entry point for the whole app.

One function, `chat_completion()`, is used by every route that needs a model
(conversational screening, score extraction, the Humdum companion). Providers
are OpenAI-compatible chat-completions APIs, selected and ordered purely by
environment variables:

    LLM_PROVIDERS      ordered comma list, e.g. "qwen,groq,gemini"
                       (unset = this default order; providers with no API key
                       are skipped, so a deployment that only has GEMINI_API_KEY
                       keeps working exactly as before)
    <NAME>_API_KEY     per provider, e.g. QWEN_API_KEY
    <NAME>_BASE_URL    per provider (falls back to the documented default)
    <NAME>_MODEL       per provider (falls back to the documented default)

Speed design:
- Reasoning/thinking is disabled or capped everywhere it has a switch (Qwen
  enable_thinking=false, Gemini reasoning_effort="none", Groq
  reasoning_effort=GROQ_REASONING_EFFORT default "low"), because these are
  short conversational turns, not reasoning tasks.
- One request timeout (LLM_TIMEOUT_SECONDS, default 18s) and a bounded reply
  size (LLM_MAX_TOKENS, default 700).
- On 429 the NEXT provider is tried immediately - never a waiting room. Timeouts
  and 5xx get at most one quick same-provider retry. A 4xx that looks like a
  bad request (e.g. a provider rejecting the thinking-disable extra) is retried
  once WITHOUT the extras before giving up on that provider. A server-side
  json_object validation rejection (the model produced one prose generation
  instead of JSON) is retried as-is, because the request itself was fine.

The caller owns the response contract: this layer returns text, never parses it
into clinical structure. Logging records provider, model, latency and token
counts - never message content or any user data.
"""

import logging
import os
import time

import requests

logger = logging.getLogger('zs.llm')

# Documented base URLs for the OpenAI-compatible endpoints (confirmed against
# provider docs, Oct 2026). All overridable per provider via env.
DEFAULTS = {
    'qwen': {
        'base_url': 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen3.8-flash',
    },
    'groq': {
        'base_url': 'https://api.groq.com/openai/v1',
        'model': 'openai/gpt-oss-120b',
    },
    'gemini': {
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai/',
        'model': 'gemini-2.5-flash',
    },
}
DEFAULT_ORDER = ('qwen', 'groq', 'gemini')

DEFAULT_TIMEOUT_SECONDS = 18
DEFAULT_MAX_TOKENS = 700

# Two attempts per provider maximum: the first with thinking disabled, and a
# single quick retry either without the extras (400) or as-is (timeout/5xx).
_MAX_ATTEMPTS_PER_PROVIDER = 2


class LLMError(Exception):
    """
    Every configured provider failed. `attempts` describes what happened per
    provider (name, model, error kind, status) for logs and callers.

    `response` is attached from the LAST HTTP error when there was one, so the
    existing failure classification in chat.py (quota-exhausted vs transient
    vs config) keeps working unchanged.
    """

    def __init__(self, message, attempts=None, last_error=None):
        super().__init__(message)
        self.attempts = attempts or []
        self.last_error = last_error
        response = getattr(last_error, 'response', None)
        if response is not None:
            self.response = response


def _env(name):
    return (os.environ.get(name) or '').strip()


def _api_key_for(name):
    key = _env(f'{name.upper()}_API_KEY')
    if not key and name == 'gemini':
        # Legacy aliases from the single-provider era keep working.
        key = _env('GEMINI_API_KEY') or _env('Gemini_API')
    return key


def configured_providers():
    """Ordered [{name, key, base_url, model}] for providers that have a key."""
    raw = _env('LLM_PROVIDERS')
    if raw:
        names = [p.strip().lower() for p in raw.split(',') if p.strip()]
    else:
        names = list(DEFAULT_ORDER)
    providers = []
    for name in names:
        key = _api_key_for(name)
        if not key:
            continue  # no key -> this provider is simply not part of the chain
        defaults = DEFAULTS.get(name, {})
        base_url = _env(f'{name.upper()}_BASE_URL') or defaults.get('base_url', '')
        model = _env(f'{name.upper()}_MODEL') or defaults.get('model', '')
        if not base_url or not model:
            continue
        providers.append({'name': name, 'key': key,
                          'base_url': base_url.rstrip('/'), 'model': model})
    return providers


def configured():
    """Is at least one provider usable? (Replaces the old single-key check.)"""
    return bool(configured_providers())


def _timeout_seconds(override=None):
    if override:
        return override
    try:
        value = float(_env('LLM_TIMEOUT_SECONDS'))
        return value if value > 0 else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _max_tokens(override=None):
    if override:
        return override
    try:
        value = int(_env('LLM_MAX_TOKENS'))
        return value if value > 0 else DEFAULT_MAX_TOKENS
    except ValueError:
        return DEFAULT_MAX_TOKENS


def _extras(name):
    """Per-provider speed extras: keep thinking minimal. Empty for the rest."""
    if name == 'qwen':
        # DashScope compatible-mode: top-level body field (OpenAI SDK users
        # pass it as extra_body). Ignored/unsupported by some older models -
        # a 400 there triggers the without-extras retry.
        return {'enable_thinking': False}
    if name == 'gemini':
        # Gemini OpenAI-compat: reasoning_effort "none" disables thinking on
        # 2.5+ models (do not also send a thinking budget - they conflict).
        return {'reasoning_effort': 'none'}
    if name == 'groq':
        # Groq honors reasoning_effort (docs: gpt-oss-20b/120b; verified HTTP
        # 200 on qwen/qwen3.8-27b as well, where effort=low keeps the hidden
        # reasoning to a few tokens - which matters because reasoning counts
        # against LLM_MAX_TOKENS and can otherwise starve the JSON budget).
        # GROQ_REASONING_EFFORT: low | medium | high; any other value (e.g.
        # "off") omits the field entirely. Unset -> low = fast replies.
        # If a model ever rejects the field, the existing config-400 retry
        # re-sends the same request once WITHOUT extras (chat_completion).
        effort = _env('GROQ_REASONING_EFFORT')
        effort = (effort or 'low').strip().lower()
        if effort in ('low', 'medium', 'high'):
            return {'reasoning_effort': effort}
        return {}
    return {}


def _json_validate_failed(exc):
    """Groq's server-side json_object check rejected ONE probabilistic
    generation (the model answered with prose instead of JSON). The request
    itself is fine, so a fresh attempt usually comes back valid - retrying is
    worth far more than failing the user's turn over a parse blip."""
    response = getattr(exc, 'response', None)
    text = getattr(response, 'text', '') or ''
    return 'json_validate_failed' in text


def _build_payload(provider, messages, json_mode, with_extras,
                   timeout=None, max_tokens=None):
    payload = {
        'model': provider['model'],
        'messages': messages,
        'max_tokens': _max_tokens(max_tokens),
    }
    if json_mode:
        # Every documented provider here supports json_object mode. Parsing
        # and validation stay on the caller's side regardless.
        payload['response_format'] = {'type': 'json_object'}
    if with_extras:
        payload.update(_extras(provider['name']))
    return payload


def _failure_kind(exc):
    """'config' (4xx, not 429) | 'transient' (429/5xx/timeout/network)."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return 'transient'
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    if status is not None and 400 <= status < 500 and status != 429:
        return 'config'
    return 'transient'


def _post_chat(provider, messages, json_mode, with_extras,
               timeout=None, max_tokens=None):
    """One HTTP call. Returns (content, latency_ms, usage_dict). Raises on errors."""
    payload = _build_payload(provider, messages, json_mode, with_extras,
                             timeout=timeout, max_tokens=max_tokens)
    started = time.monotonic()
    response = requests.post(
        f"{provider['base_url']}/chat/completions",
        json=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {provider['key']}",
        },
        timeout=_timeout_seconds(timeout),
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code >= 400:
        error = requests.HTTPError(
            f"HTTP {response.status_code}", response=response)
        error.latency_ms = latency_ms
        raise error
    data = response.json()
    content = data['choices'][0]['message']['content']
    usage = data.get('usage') or {}
    return content, latency_ms, usage


def _log_call(provider, ok, latency_ms, usage, detail=''):
    """Structured, content-free log line: who answered, how fast, how many tokens."""
    logger.info(
        "llm provider=%s model=%s ok=%s latency_ms=%s prompt_tokens=%s "
        "completion_tokens=%s %s",
        provider['name'], provider['model'], ok, latency_ms,
        usage.get('prompt_tokens'), usage.get('completion_tokens'), detail,
    )


def chat_completion(messages, json_mode=False, timeout=None, max_tokens=None):
    """
    Run one chat completion with automatic failover.

    Tries each configured provider in order; returns
    {'content', 'provider', 'model', 'latency_ms', 'usage'} on the first
    success. Raises LLMError when every provider has failed - the caller
    decides how to degrade (the app degrades honestly to the written form and
    keeps its LLM-independent crisis floor).
    """
    providers = configured_providers()
    if not providers:
        raise LLMError('no LLM provider configured (set LLM_PROVIDERS and an API key)')

    attempts = []
    last_error = None
    for provider in providers:
        with_extras = bool(_extras(provider['name']))
        retry_left = _MAX_ATTEMPTS_PER_PROVIDER - 1
        while True:
            try:
                content, latency_ms, usage = _post_chat(
                    provider, messages, json_mode, with_extras,
                    timeout=timeout, max_tokens=max_tokens)
                _log_call(provider, True, latency_ms, usage)
                return {
                    'content': content,
                    'provider': provider['name'],
                    'model': provider['model'],
                    'latency_ms': latency_ms,
                    'usage': usage,
                }
            except Exception as exc:  # noqa: BLE001 - classified below
                kind = _failure_kind(exc)
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                latency_ms = getattr(exc, 'latency_ms', None)
                _log_call(provider, False, latency_ms, {},
                          detail=f"status={status} kind={kind}")
                attempts.append({
                    'provider': provider['name'], 'model': provider['model'],
                    'kind': kind, 'status': status,
                })
                last_error = exc
                if status == 429:
                    break  # rate limited: the next provider may still serve
                if kind == 'config' and status == 400 and retry_left > 0 \
                        and _json_validate_failed(exc):
                    # Checked BEFORE the extras branch: a JSON-blip is a
                    # generation issue, not a param issue - retry as-is.
                    retry_left -= 1  # same request again - see _json_validate_failed
                    continue
                if kind == 'config' and with_extras and retry_left > 0:
                    # Most likely this model rejected the thinking-disable
                    # extra - retry once without it before giving up.
                    with_extras = False
                    retry_left -= 1
                    continue
                if kind == 'transient' and retry_left > 0:
                    retry_left -= 1  # one quick same-provider retry
                    continue
                break
    raise LLMError(f'all {len(providers)} LLM provider(s) failed',
                   attempts=attempts, last_error=last_error)
