"""Dependency-free metric implementations used by the evaluation harness."""
import re
from collections import Counter


def toks(s: str):
    return re.findall(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", (s or "").lower())


def _ngrams(t, n):
    return Counter(tuple(t[i:i + n]) for i in range(len(t) - n + 1))


def _f(p, r):
    return 2 * p * r / (p + r) if p + r else 0.0


def rouge_n(pred: str, ref: str, n=1) -> float:
    p, r = _ngrams(toks(pred), n), _ngrams(toks(ref), n)
    ov = sum((p & r).values())
    return _f(ov / max(sum(p.values()), 1), ov / max(sum(r.values()), 1))


def rouge_l(pred: str, ref: str) -> float:
    a, b = toks(pred), toks(ref)
    if not a or not b:
        return 0.0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        for j in range(len(b)):
            dp[i + 1][j + 1] = dp[i][j] + 1 if a[i] == b[j] else max(dp[i][j + 1], dp[i + 1][j])
    lcs = dp[-1][-1]
    return _f(lcs / len(a), lcs / len(b))


def fact_coverage(pred: str, facts: list[str]) -> float:
    """Share of gold key-facts (strings) present in the predicted value (case/space-insensitive)."""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").lower())
    p = norm(pred)
    return sum(1 for f in facts if norm(f) in p) / len(facts) if facts else 1.0


def keyword_match(pred_terms, gold_terms):
    """Lenient containment match. Returns (precision, recall, f1)."""
    pl = [p.lower() for p in pred_terms]
    gl = [g.lower() for g in gold_terms]
    hit_gold = sum(1 for g in gl if any(g in p or p in g for p in pl))
    hit_pred = sum(1 for p in pl if any(g in p or p in g for g in gl))
    prec, rec = hit_pred / max(len(pl), 1), hit_gold / max(len(gl), 1)
    return prec, rec, _f(prec, rec)


def percentile(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0
