"""Terminal rendering shared by scripts/check_nebius.py and scripts/compare.py.

The five blocks below are exactly what the extension drawer shows, so what the script prints
is what a judge would see in the browser.
"""

from __future__ import annotations

from backend.schemas.analysis_schema import AnalyzeResponse, PostAnalysis

OK, BAD, INFO = "  ok  ", " FAIL ", " .... "


def line(mark: str, text: str) -> None:
    print(f"[{mark}] {text}", flush=True)


def block(title: str, body: str) -> None:
    print(f"\n{title}\n{body}")


def render_analysis(a: PostAnalysis, title: str) -> None:
    """The five client-facing blocks: claim, check, missing context, signals, speaker."""
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)
    if a.main_claim.found:
        block("MAIN CLAIM", f'  "{a.main_claim.text}"\n  quoted: "{a.main_claim.quote}"')
    else:
        block("MAIN CLAIM", "  none found (no checkable factual claim)")
    src = "\n".join(f"  - {s.title} — {s.url}" for s in a.claim_check.sources) or "  (none cited)"
    block("CLAIM CHECK", f"  {a.claim_check.verdict.upper()}\n  {a.claim_check.explanation}\n  Sources:\n{src}")
    block("MISSING CONTEXT", f"  {a.missing_context or '(none)'}")
    sig = "\n".join(f'  [{s.name}]  "{s.evidence}"' for s in a.rhetorical_signals) or "  (none)"
    block("RHETORICAL SIGNALS", sig)
    sp = a.speaker_context
    block("SPEAKER CONTEXT", f"  {sp.name}" + (f" · {sp.role}" if sp.role else "") + f"\n  {sp.background}")


def render_timings(resp: AnalyzeResponse, elapsed_ms: float | None = None) -> None:
    total = elapsed_ms if elapsed_ms is not None else resp.latency_ms
    cost = f"${resp.cost_usd:.5f}" if resp.cost_usd is not None else "unpriced"
    print(f"\n    total {total:.0f} ms  =  claim {resp.steps.extract_ms} + evidence {resp.steps.evidence_ms} + analysis {resp.steps.analyse_ms}")
    print(f"    cost {cost} · evidence {len(resp.evidence)} results · background {len(resp.sources)} sources")
