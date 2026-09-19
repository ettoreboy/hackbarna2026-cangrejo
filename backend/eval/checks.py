"""Per-response sanity checks: the single-post version of the metrics in metrics.py.

``metrics.py`` scores a whole run and returns rates. This module answers the same three
questions about one response, and returns the human-readable problems. ``scripts/check_nebius.py``
and ``scripts/compare.py`` both print the result, so the rules live in one place.
"""

from __future__ import annotations

from backend.schemas.analysis_schema import AnalyzeResponse


def response_problems(resp: AnalyzeResponse, post_text: str) -> list[str]:
    """Quote fidelity, taxonomy adherence and citation grounding, as warning lines.

    An empty list means the response is internally consistent. None of these are fatal: the
    pipeline already drops non-verbatim signal quotes (``pipeline._snap_quotes``) and
    non-evidence citations (``pipeline._cited_only``), so a problem here means the model
    needed that correction, which is worth seeing when comparing two providers.
    """
    problems: list[str] = []
    a = resp.analysis

    if a.main_claim.found and a.main_claim.quote and a.main_claim.quote not in post_text:
        problems.append("claim quote is not verbatim from the post")

    for s in a.rhetorical_signals:
        if s.evidence and s.evidence not in post_text:
            problems.append(f"signal {s.name} quote is not verbatim")
        if s.name.startswith("Other: "):
            problems.append(f"label outside the taxonomy: {s.name}")

    evidence_urls = {e.url.rstrip("/") for e in resp.evidence}
    for c in a.claim_check.sources:
        if c.url.rstrip("/") not in evidence_urls:
            problems.append(f"cited URL was not in the evidence: {c.url}")

    return problems
