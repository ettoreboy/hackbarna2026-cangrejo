"""Shape of an evaluation item and the JSONL helpers shared by the eval and fine-tune scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, Field

Group = Literal["right", "left", "neutral", "injection_clean", "injection_dirty", "real"]


class EvalItem(BaseModel):
    id: str
    group: Group
    pair_id: str | None = Field(default=None, description="Mirrored pairs and injection twins share this")
    topic: str
    signal_target: str = Field(default="", description="The signal the post was written to exhibit")
    author_handle: str
    author_name: str
    post_text: str
    claim_expected: bool = Field(description="Whether the post contains a checkable factual claim")
    signals_expected: bool = Field(description="Whether any rhetorical signal should be found")
    party: str = Field(default="", description="Real-tweet sets only: the author's party at collection")
    post_url: str = ""

    def to_request(self) -> dict:
        return {
            "author_handle": self.author_handle,
            "author_name": self.author_name,
            "post_text": self.post_text,
            "platform": "x",
        }


def write_jsonl(path: str | Path, items: list[BaseModel]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as fh:
        for item in items:
            fh.write(item.model_dump_json() + "\n")


def read_jsonl(path: str | Path) -> Iterator[dict]:
    with Path(path).open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_eval_set(path: str | Path) -> list[EvalItem]:
    """Load a generated .jsonl set or a real-tweet .csv (tweets.csv schema)."""
    p = Path(path)
    if p.suffix == ".csv":
        return load_tweet_csv(p)
    return [EvalItem.model_validate(row) for row in read_jsonl(p)]


def load_tweet_csv(path: str | Path) -> list[EvalItem]:
    """Real tweets from the research archive: one row per tweet, party label as ground truth.

    Nothing here is annotated for claims or signals, so claim_expected/signals_expected are
    left true and the metrics that need a label are skipped. What this set measures is whether
    the analyzer treats the two parties the same, on real language.
    """
    import csv

    items: list[EvalItem] = []
    with Path(path).open() as fh:
        for row in csv.DictReader(fh):
            text = (row.get("text") or "").strip()
            handle = (row.get("author_handle") or "").strip().lstrip("@")
            if not text or not handle:
                continue
            items.append(EvalItem(
                id=row.get("tweet_id") or handle,
                group="real",
                pair_id=None,
                topic=row.get("split", ""),
                signal_target="",
                author_handle=handle,
                author_name=(row.get("author_name") or handle).strip(),
                post_text=text,
                claim_expected=True,
                signals_expected=True,
                party=(row.get("party_at_collection") or "").strip(),
                post_url=(row.get("post_url") or "").strip(),
            ))
    return items
