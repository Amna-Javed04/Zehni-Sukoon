"""Benchmark the configured LLM providers on the app's own score-extraction cases.

Usage:
    python scripts/llm_benchmark.py                 # every configured provider, all 40 cases
    python scripts/llm_benchmark.py --provider qwen  # a single provider
    python scripts/llm_benchmark.py --limit 10       # first N cases per instrument

For each provider in LLM_PROVIDERS that has an API key, every case from
test_score_extraction.py is sent through backend/llm_client.py using the SAME
extraction prompt and JSON contract the app uses
(chat.EXTRACT_SCORE_SYSTEM_PROMPT), one provider at a time (no failover), so
accuracy and latency are compared like for like.

- "Correct" mirrors the app's expectations: vague replies must ask for
  clarification; clear replies must land on the exact expected 0-3 score
  (with the PHQ-9 q9 risk rule: self-harm hints are scored >= 1, never
  deferred).
- Provider errors and unparseable replies count as incorrect and are tallied.

Needs real API keys in .env - this deliberately spends a little quota.
Startup takes ~20s because the shared prompt constant lives in the chat route
module, which imports the screening engine on load.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(override=True)

import backend.llm_client as llm  # noqa: E402
from backend.routes.chat import EXTRACT_SCORE_SYSTEM_PROMPT, _extract_json_object  # noqa: E402
from test_score_extraction import phq9_samples, gad7_samples  # noqa: E402


def run_case(case):
    """-> (correct: bool, latency_ms: int, detail: str)."""
    started = time.monotonic()
    try:
        result = llm.chat_completion([
            {'role': 'system', 'content': EXTRACT_SCORE_SYSTEM_PROMPT},
            {'role': 'user',
             'content': f"Question: {case['question']}\nUser Reply: {case['reply']}"},
        ], json_mode=True)
    except Exception as exc:  # noqa: BLE001 - a failed call is just a wrong answer here
        latency = int((time.monotonic() - started) * 1000)
        return False, latency, f"provider error: {exc}"

    latency = int((time.monotonic() - started) * 1000)
    try:
        parsed = _extract_json_object(result['content'])
    except Exception:  # noqa: BLE001
        # Content-free on purpose: replies may quote the user's own words,
        # and neither prompts nor user text belong in output or logs.
        return False, latency, (f"unparseable reply: no JSON object in "
                                f"{len(result['content'])} chars of model output")

    got_score = parsed.get('score')
    got_clarify = bool(parsed.get('needs_clarification'))
    if case['clarify']:
        correct = got_clarify is True
        detail = f"score={got_score} clarify={got_clarify} (want clarify)"
    else:
        correct = (not got_clarify) and got_score == case['expected_score']
        detail = f"score={got_score} clarify={got_clarify} (want {case['expected_score']})"
    return correct, latency, detail


def benchmark_provider(name, cases, verbose=False):
    saved = dict(os.environ)
    for key in [k for k in os.environ if k.startswith('LLM_PROVIDERS')]:
        os.environ.pop(key, None)
    os.environ['LLM_PROVIDERS'] = name
    correct = 0
    latencies = []
    errors = 0
    try:
        if not llm.configured_providers():
            print(f"  [{name}] skipped - no API key configured")
            return None
        for idx, case in enumerate(cases):
            ok, latency, detail = run_case(case)
            latencies.append(latency)
            correct += int(ok)
            if not ok:
                errors += 1
            marker = 'ok ' if ok else 'MISS'
            if verbose or not ok:
                print(f"    {marker} #{idx + 1:>2} {latency:>5}ms  {detail}  | {case['reply'][:40]}")
    finally:
        os.environ.clear()
        os.environ.update(saved)
    total = len(cases)
    avg = round(sum(latencies) / len(latencies)) if latencies else 0
    return {
        'provider': name,
        'accuracy': correct,
        'total': total,
        'pct': round(correct / total * 100, 1) if total else 0.0,
        'avg_latency_ms': avg,
        'errors': errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--provider', help='benchmark a single provider by name')
    parser.add_argument('--limit', type=int, default=0,
                        help='use only the first N cases per instrument (default: all)')
    parser.add_argument('--verbose', action='store_true',
                        help='print every case, not only misses')
    args = parser.parse_args()

    cases = phq9_samples + gad7_samples
    if args.limit > 0:
        cases = phq9_samples[:args.limit] + gad7_samples[:args.limit]

    providers = llm.configured_providers()
    if not providers:
        print("No provider configured. Set LLM_PROVIDERS and at least one "
              "<NAME>_API_KEY in .env (see .env.example).")
        return 1
    names = [args.provider] if args.provider else [p['name'] for p in providers]

    print(f"Benchmarking {len(cases)} score-extraction cases per provider "
          f"(JSON contract: EXTRACT_SCORE_SYSTEM_PROMPT)\n")
    rows = []
    for name in names:
        print(f"[{name}] running {len(cases)} cases...")
        row = benchmark_provider(name, cases, verbose=args.verbose)
        if row:
            rows.append(row)

    if not rows:
        print("Nothing to report.")
        return 1

    print("\n" + "=" * 66)
    print(f"{'provider':<10} {'accuracy':>10} {'avg latency':>12} {'errors':>7}")
    print("-" * 66)
    for row in sorted(rows, key=lambda r: (-r['pct'], r['avg_latency_ms'])):
        print(f"{row['provider']:<10} "
              f"{str(row['accuracy']) + '/' + str(row['total']):>7} ({row['pct']:>4.1f}%) "
              f"{str(row['avg_latency_ms']) + 'ms':>12} {row['errors']:>7}")
    print("=" * 66)
    print("Best accuracy first; ties broken by average latency.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
