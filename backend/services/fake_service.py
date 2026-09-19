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
    ClaimCheck,
    ClaimSource,
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


class FakeAnalyzer:
    name = "fake"
    model = "fake-v3"

    def __init__(self) -> None:
        self.extract_calls: list[AnalyzeRequest] = []
        self.analyse_calls: list[tuple[AnalyzeRequest, MainClaim, list[Source], list[Source], str]] = []

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

        if background:
            speaker = SpeakerContext(name=req.author_name, role=_role(background[0]), background=background[0].snippet[:240])
        else:
            speaker = SpeakerContext(name=req.author_name, role="", background="Unknown author")

        body = AnalysisBody(
            claim_check=check,
            missing_context=_MISSING.get(handle, ""),
            rhetorical_signals=_SIGNALS.get(handle, [Signal(name="Loaded Language", evidence=req.post_text[:40])]),
            speaker_context=speaker,
        )
        return StepOutcome(result=body, model=self.model, cost_usd=0.0)


def _role(src: Source) -> str:
    snippet = src.snippet.lower()
    if "politician" in snippet:
        return "Politician"
    if "statistical" in snippet or "agency" in snippet:
        return "Government agency"
    return "Public figure"
