"""Shape of an evaluation item and the JSONL helpers shared by the eval and fine-tune scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, Field

Group = Literal["right", "left", "neutral", "injection_clean", "injection_dirty"]


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
    return [EvalItem.model_validate(row) for row in read_jsonl(path)]
