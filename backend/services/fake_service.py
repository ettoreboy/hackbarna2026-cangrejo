"""Deterministic analyzer for offline development and tests.

Enable with ANALYZER_PROVIDER=fake. Returns schema-v2 responses keyed on the author handle so
the extension can be developed with no API keys. Unknown handles get the high-manipulation profile.
"""

from __future__ import annotations

from backend.schemas.analysis_schema import AnalysisResult, AnalyzeRequest, Fallacy, Indicators, Signal, Source
from backend.services.analyzer_base import AnalysisOutcome


def canned_result(req: AnalyzeRequest, sources: list[Source]) -> AnalysisResult:
    handle = req.author_handle.lower()
    background = sources[0].snippet[:300] if sources else "Unknown author"

    if handle == "destatis":
        return AnalysisResult(
            post_summary="A statistics office reports preliminary August inflation and energy price figures.",
            author=req.author_name,
            author_background=background if sources else "Unknown author",
            communication_signals=[],
            logical_fallacies=[],
            indicators=Indicators(
                strategic_intent="Routine statistical release.",
                timing_note="Scheduled monthly publication.",
                factual_context="Figures are labelled preliminary by the source itself.",
                is_division_tactic=False,
            ),
            manipulation_score=5,
            cognitive_summary="An informational post gives numbers, a source and a caveat, and asks nothing of the reader. That combination is the baseline to compare persuasive posts against.",
        )

    if handle == "troll_account":
        return AnalysisResult(
            post_summary="An anonymous account claims unnamed elites want the reader poor and scared.",
            author=req.author_name,
            author_background="Unknown author",
            communication_signals=[
                Signal(
                    name="Fear-mongering",
                    evidence="the elites want you poor and scared",
                    confidence=0.8,
                    description="Names a vague threat with no actor or evidence.",
                ),
                Signal(
                    name="Emotional Bait",
                    evidence="wake up sheeple",
                    confidence=0.7,
                    description="Flatters the reader as awake versus a sleeping majority.",
                ),
            ],
            logical_fallacies=[Fallacy(name="Appeal to Fear", evidence="want you poor and scared")],
            indicators=Indicators(
                strategic_intent="Engagement bait; no policy claim to evaluate.",
                timing_note="No timing signal identified.",
                factual_context="No verifiable claim is made.",
                is_division_tactic=True,
            ),
            manipulation_score=70,
            cognitive_summary="A vague 'they', a fear, and flattery of the reader is a reusable engagement pattern. Ask who 'they' are and what evidence is offered; if neither is present, the post is bait.",
        )

    if handle == "example_centrist":
        return AnalysisResult(
            post_summary="A minister frames the election as a choice between stability and extremists on both sides.",
            author=req.author_name,
            author_background="Unknown author",
            communication_signals=[
                Signal(
                    name="Fear-mongering",
                    evidence="or the radicals win",
                    confidence=0.75,
                    description="Presents the opponent's win as a catastrophe without saying what would happen.",
                ),
                Signal(
                    name="Us-vs-Them Framing",
                    evidence="sensible adults like us",
                    confidence=0.7,
                    description="Casts the speaker's side as the only mature actors.",
                ),
            ],
            logical_fallacies=[
                Fallacy(name="False Dilemma", evidence="Vote for stability on Sunday or the radicals win"),
                Fallacy(name="Middle Ground", evidence="Only sensible adults like us can save democracy"),
            ],
            indicators=Indicators(
                strategic_intent="Mobilize turnout before Sunday's vote.",
                timing_note="Published days before an election.",
                factual_context="No specific policy or fact is asserted.",
                is_division_tactic=True,
            ),
            manipulation_score=55,
            cognitive_summary="Casting oneself as the only adult in the room is a positioning move used across the spectrum. The tell is that no policy is named, only the character of the alternatives.",
        )

    # Default high-manipulation profile (Weidel fixture and left control share it).
    return AnalysisResult(
        post_summary="The author links a social problem to one group and demands an immediate binary choice.",
        author=req.author_name,
        author_background=background,
        communication_signals=[
            Signal(
                name="Outrage Farming",
                evidence="pour over our borders" if "border" in req.post_text else "bleeding working families dry",
                confidence=0.85,
                description="Emotionally charged imagery chosen to trigger sharing.",
            ),
            Signal(
                name="Scapegoating",
                evidence="illegal migrants" if "migrant" in req.post_text else "Every landlord",
                confidence=0.9,
                description="Attributes a complex problem to one group as the sole cause.",
            ),
            Signal(
                name="Manufactured Urgency",
                evidence="now" if "now" in req.post_text else "tomorrow",
                confidence=0.7,
                description="Frames an ongoing situation as a last-chance moment.",
            ),
        ],
        logical_fallacies=[
            Fallacy(name="False Dilemma", evidence="Either we" if "Either we" in req.post_text else "There is no middle ground"),
            Fallacy(name="Hasty Generalization", evidence=req.post_text.split(".")[0][:80]),
        ],
        indicators=Indicators(
            strategic_intent="Mobilize the base by naming a culprit and a deadline.",
            timing_note="No timing signal identified.",
            factual_context="The causal link asserted is not supported by any cited data.",
            is_division_tactic=True,
        ),
        manipulation_score=85,
        cognitive_summary="Culprit plus deadline plus binary choice is the standard mobilisation triad. When you see all three, look for the missing second cause and the missing third option.",
    )


class FakeAnalyzer:
    name = "fake"
    model = "fake-v2"

    def __init__(self) -> None:
        self.calls: list[tuple[AnalyzeRequest, list[Source], str]] = []

    async def analyze(
        self, req: AnalyzeRequest, sources: list[Source], prompt_version: str = "v1"
    ) -> AnalysisOutcome:
        self.calls.append((req, sources, prompt_version))
        return AnalysisOutcome(result=canned_result(req, sources), model=self.model, cost_usd=0.0)
