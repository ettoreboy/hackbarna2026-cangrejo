"""Deterministic analyzer for offline development and tests.

Enable with ANALYZER_PROVIDER=fake. Keyed on the author handle so the extension can be
developed with no API keys. The fake honours its inputs the way a real model should: the
verdict depends on whether evidence was supplied, cited sources are copied from that evidence,
and the speaker background is "Unknown author" when no background source is given.
"""

from __future__ import annotations

from backend.schemas.analysis_schema import (
    AnalysisBody,
    AnalyzeRequest,
    ClaimCandidate,
    ClaimCheck,
    ClaimDraft,
    ClaimSource,
    ClaimVerdict,
    DiscoveryBody,
    MainClaim,
    Signal,
    Source,
    SpeakerContext,
)
from backend.services.analyzer_base import StepOutcome

_CLAIMS: dict[str, MainClaim] = {
    "alice_weidel": MainClaim(
        found=True,
        text="The number of illegal migrants entering Germany is increasing every day.",
        quote="Every day more illegal migrants pour over our borders",
    ),
    "example_migrants": MainClaim(
        found=True,
        text="Germany accepted 1.2 million migrants last year.",
        quote="Germany accepted 1.2M migrants last year.",
    ),
    "example_left_mp": MainClaim(found=False, text="", quote=""),
    "example_centrist": MainClaim(found=False, text="", quote=""),
    "destatis": MainClaim(
        found=True,
        text="Consumer prices in Germany rose 2.2% year on year in August 2026 according to preliminary figures.",
        quote="Consumer prices in Germany rose 2.2% year on year in August 2026",
    ),
    "troll_account": MainClaim(found=False, text="", quote=""),
}

_SIGNALS: dict[str, list[Signal]] = {
    "alice_weidel": [
        Signal(name="Loaded Language", evidence="pour over our borders"),
        Signal(name="Scapegoating", evidence="illegal migrants"),
        Signal(name="Fear-mongering", evidence="The system is collapsing"),
        Signal(name="False Dilemma", evidence="Either we close the borders now or we lose our country"),
    ],
    "example_migrants": [Signal(name="Loaded Language", evidence="clearly doesn't care about German citizens")],
    "example_left_mp": [
        Signal(name="Dehumanization", evidence="parasite"),
        Signal(name="Scapegoating", evidence="Every landlord in this city"),
        Signal(name="False Dilemma", evidence="Either we freeze all rents tomorrow or we watch our neighbourhoods die"),
    ],
    "example_centrist": [
        Signal(name="Fear-mongering", evidence="or the radicals win"),
        Signal(name="Us-vs-Them Framing", evidence="sensible adults like us"),
        Signal(name="Middle Ground", evidence="Only sensible adults like us can save democracy"),
    ],
    "destatis": [],
    "troll_account": [
        Signal(name="Fear-mongering", evidence="the elites want you poor and scared"),
        Signal(name="Emotional Bait", evidence="wake up sheeple"),
    ],
}

_MISSING: dict[str, str] = {
    "alice_weidel": "Irregular border crossings and heating costs are unrelated budget lines; the post gives no figure for either.",
    "example_migrants": "The figure mixes asylum applications with all forms of immigration, and a large share were Ukrainian refugees under temporary protection.",
    "example_left_mp": "",
    "example_centrist": "",
    "destatis": "",
    "troll_account": "",
}


def _default_claim(req: AnalyzeRequest) -> MainClaim:
    first = req.post_text.split(".")[0].strip()
    return MainClaim(found=True, text=first + ".", quote=first)


# --------------------------------------------------------------------------- two-stage fixtures
#
# Multi-claim sets for the claim picker. Keyed on handle so the extension can develop every
# branch offline: several claims, exactly one, and none at all.

_MULTI: dict[str, list[ClaimDraft]] = {
    "alice_weidel": [
        ClaimDraft(
            text="The number of irregular border crossings into Germany is rising.",
            quote="Every day more illegal migrants pour over our borders",
        ),
        ClaimDraft(
            text="German pensioners cannot afford to heat their homes.",
            quote="German families can't afford to heat their homes",
        ),
    ],
    "example_migrants": [
        ClaimDraft(
            text="Germany accepted 1.2 million migrants last year.",
            quote="Germany accepted 1.2M migrants last year.",
        ),
        ClaimDraft(
            text="Germany's asylum budget increased in 2025.",
            quote="the asylum budget keeps climbing",
        ),
    ],
    "destatis": [
        ClaimDraft(
            text="Consumer prices in Germany rose 2.2% year on year in August 2026 according to preliminary figures.",
            quote="Consumer prices in Germany rose 2.2% year on year in August 2026",
        ),
    ],
    # Pure rhetoric: nothing checkable, but plenty of signals.
    "example_left_mp": [],
    "example_centrist": [],
    "troll_account": [],
}

# Verdicts per (handle, claim index), so switching claims visibly changes the answer.
_VERDICTS: dict[str, list[tuple[str, str]]] = {
    "alice_weidel": [
        ("partially_supported", "Crossings rose over the period the sources cover, but not 'every day', and the sources give no daily series."),
        ("unverifiable", "No supplied source reports heating affordability among pensioners."),
    ],
    "example_migrants": [
        ("partially_supported", "The direction is reported by the sources but the scale and timeframe in the post are not."),
        ("unsupported", "The cited budget line fell in 2025 rather than rising."),
    ],
    "destatis": [
        ("supported", "The figure matches the preliminary release cited."),
    ],
}

# Canned web results so fake mode demonstrates every verdict with no BRAVE_API_KEY. The real
# Brave search always wins when it returns anything; this only fills an empty result.
_EVIDENCE: dict[str, list[Source]] = {
    "alice_weidel": [
        Source(
            title="Irregular migration to Germany, monthly series",
            url="https://www.bamf.example/irregular-migration-2026",
            snippet="Detected irregular entries rose 14% year on year, with month-to-month figures varying widely.",
            provider="brave",
        ),
    ],
    "example_migrants": [
        Source(
            title="Migration report 2025 - Federal Office for Migration",
            url="https://www.bamf.example/report-2025",
            snippet="In 2025 Germany registered 351,915 first-time asylum applications, alongside around 1.1 million arrivals under temporary protection.",
            provider="brave",
        ),
        Source(
            title="Fact check: how many people came to Germany last year?",
            url="https://www.news.example/factcheck-migration",
            snippet="The 1.2 million figure conflates asylum seekers with Ukrainian refugees and EU free movement.",
            provider="brave",
        ),
    ],
    "destatis": [
        Source(
            title="Consumer price index, August 2026 - preliminary",
            url="https://www.destatis.example/cpi-august-2026",
            snippet="Consumer prices rose 2.2% year on year in August 2026 according to preliminary results.",
            provider="brave",
        ),
    ],
    # Posts with nothing checkable still get related reading, so the panel is never blank in
    # the demo. troll_account is deliberately absent: it is the empty-state fixture.
    "example_left_mp": [
        Source(
            title="What the evidence says about rent control",
            url="https://www.econ.example/rent-control-evidence",
            snippet="Reviews find rent caps protect sitting tenants in the short run while reducing rental supply over time.",
            provider="brave",
        ),
        Source(
            title="City housing market report 2026",
            url="https://www.cityhousing.example/report-2026",
            snippet="Median rents rose 7% year on year; the report attributes most of the rise to a shortfall in new construction.",
            provider="brave",
        ),
    ],
    "example_centrist": [
        Source(
            title="Affective polarisation across Europe, 2010-2026",
            url="https://www.polisci.example/affective-polarisation",
            snippet="Cross-national surveys find hostility between partisan camps has grown faster than the gap in their stated policy preferences.",
            provider="brave",
        ),
    ],
}


class FakeAnalyzer:
    name = "fake"
    model = "fake-v3"

    def __init__(self) -> None:
        self.extract_calls: list[AnalyzeRequest] = []
        self.analyse_calls: list[tuple[AnalyzeRequest, MainClaim, list[Source], list[Source], str]] = []
        self.discover_calls: list[tuple[AnalyzeRequest, list[Source], int, str]] = []
        self.check_calls: list[tuple[AnalyzeRequest, ClaimCandidate, list[Source], str]] = []

    async def extract_claim(self, req: AnalyzeRequest) -> StepOutcome[MainClaim]:
        self.extract_calls.append(req)
        claim = _CLAIMS.get(req.author_handle.lower(), _default_claim(req))
        return StepOutcome(result=claim, model=self.model, cost_usd=0.0)

    async def analyse(
        self,
        req: AnalyzeRequest,
        claim: MainClaim,
        evidence: list[Source],
        background: list[Source],
        prompt_version: str = "v1",
    ) -> StepOutcome[AnalysisBody]:
        self.analyse_calls.append((req, claim, evidence, background, prompt_version))
        handle = req.author_handle.lower()

        if not claim.found:
            check = ClaimCheck(verdict="no_factual_claim", explanation="The post makes no checkable factual claim.", sources=[])
        elif not evidence:
            check = ClaimCheck(verdict="unverifiable", explanation="No evidence was found for this claim.", sources=[])
        elif handle == "destatis":
            check = ClaimCheck(
                verdict="supported",
                explanation="The figure matches the preliminary release cited.",
                sources=[ClaimSource(title=evidence[0].title, url=evidence[0].url)],
            )
        else:
            check = ClaimCheck(
                verdict="partially_supported",
                explanation="The direction is reported by the sources but the scale and timeframe in the post are not.",
                sources=[ClaimSource(title=s.title, url=s.url) for s in evidence[:2]],
            )

        body = AnalysisBody(
            claim_check=check,
            missing_context=_MISSING.get(handle, ""),
            rhetorical_signals=_SIGNALS.get(handle, [Signal(name="Loaded Language", evidence=req.post_text[:40])]),
            speaker_context=_speaker(req, background),
        )
        return StepOutcome(result=body, model=self.model, cost_usd=0.0)


    # ------------------------------------------------------------------ two-stage

    def offline_evidence(self, claim: ClaimCandidate | MainClaim | None, handle: str) -> list[Source]:
        """Canned results so every verdict is reachable without a BRAVE_API_KEY.

        The pipeline only calls this when both the claim search and the post search came back
        empty. `claim` is unused: the canned set is keyed on the author.
        """
        return _EVIDENCE.get(handle.lower(), [])

    async def discover(
        self,
        req: AnalyzeRequest,
        background: list[Source],
        max_claims: int = 4,
        prompt_version: str = "v1",
    ) -> StepOutcome[DiscoveryBody]:
        self.discover_calls.append((req, background, max_claims, prompt_version))
        handle = req.author_handle.lower()

        if handle in _MULTI:
            drafts = _MULTI[handle][:max_claims]
        else:
            claim = _default_claim(req)
            drafts = [ClaimDraft(text=claim.text, quote=claim.quote)]

        body = DiscoveryBody(
            claims=drafts,
            rhetorical_signals=_SIGNALS.get(handle, [Signal(name="Loaded Language", evidence=req.post_text[:40])]),
            speaker_context=_speaker(req, background),
        )
        return StepOutcome(result=body, model=self.model, cost_usd=0.0)

    async def check_claim(
        self,
        req: AnalyzeRequest,
        claim: ClaimCandidate,
        evidence: list[Source],
        prompt_version: str = "v1",
    ) -> StepOutcome[ClaimVerdict]:
        self.check_calls.append((req, claim, evidence, prompt_version))
        handle = req.author_handle.lower()

        if not evidence:
            check = ClaimCheck(verdict="unverifiable", explanation="No evidence was found for this claim.", sources=[])
        else:
            index = _claim_index(claim.id)
            table = _VERDICTS.get(handle, [])
            if index < len(table):
                verdict, explanation = table[index]
            else:
                verdict, explanation = (
                    "partially_supported",
                    "The direction is reported by the sources but the scale and timeframe in the post are not.",
                )
            check = ClaimCheck(
                verdict=verdict,
                explanation=explanation,
                sources=[ClaimSource(title=s.title, url=s.url) for s in evidence[:2]],
            )

        return StepOutcome(
            result=ClaimVerdict(claim_check=check, missing_context=_MISSING.get(handle, "")),
            model=self.model,
            cost_usd=0.0,
        )


def _claim_index(claim_id: str) -> int:
    """"c2" -> 1. Anything unrecognised falls back to the first entry."""
    try:
        return max(0, int(str(claim_id).lstrip("c")) - 1)
    except ValueError:
        return 0


def _speaker(req: AnalyzeRequest, background: list[Source]) -> SpeakerContext:
    if background:
        return SpeakerContext(name=req.author_name, role=_role(background[0]), background=background[0].snippet[:240])
    return SpeakerContext(name=req.author_name, role="", background="Unknown author")


def _role(src: Source) -> str:
    snippet = src.snippet.lower()
    if "politician" in snippet:
        return "Politician"
    if "statistical" in snippet or "agency" in snippet:
        return "Government agency"
    return "Public figure"
