# Docs

Start with `GALTEA.md` and `EVAL.md`: everything else is contract or history.

- [GALTEA.md](GALTEA.md) — What Galtea scored, and the speaker-context defect it caught
- [EVAL.md](EVAL.md) — Every measured number: v0 vs v1 guardrails, real senator tweets, what is not reproducible
- [API.md](API.md) — The contract between backend and extension. Schema v3, frozen
- [CLIENT_HANDOFF.md](CLIENT_HANDOFF.md) — Brief for the extension: what to render, what was cancelled
- [PROMPT_DESIGN.md](PROMPT_DESIGN.md) — How a request is assembled and why each rule is in the prompt
- [TECHNIQUES.md](TECHNIQUES.md) — The 25 canonical rhetorical labels, with cues and examples
- [FINETUNE.md](FINETUNE.md) — The distillation set, the two LoRA jobs, and why nothing was shipped
- [SERVING.md](SERVING.md) — Why a Token Factory fine-tune cannot be served, and the route if it could
- [ANALYSIS.md](ANALYSIS.md) — The pre-build critique of the original spec, with what happened to each point

Requests written for a third party live in [requests/](requests/).
