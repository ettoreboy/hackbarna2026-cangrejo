# Request: enable custom model weights (Token Factory beta)

Send to a Nebius mentor at HackBarna, or via https://tokenfactory.nebius.com/?modals=contact-us

---

**Subject:** Enable custom model weights beta — serving a LoRA fine-tune from Token Factory

Hi — we're team Cangrejo at HackBarna AI Summit 26, building a media-literacy tool on Token
Factory. Our analyser runs on `openai/gpt-oss-120b` and we've fine-tuned a smaller student to
match it. **We can train but we can't serve, and we think we need a beta flag on our account.**

**What we did**

- Two LoRA jobs on `Qwen/Qwen3-30B-A3B-Instruct-2507`, both `succeeded`:
  - `ftjob-ee08fbbeb0f64b218b96d1e3621cdb96` — best checkpoint `ftckpt_9bd224bd-93fb-47c6-9880-7c9ce51851b6`, validation loss 0.244
  - `ftjob-eecfd53ac90b4195955ccb723a987f8d` — best checkpoint `ftckpt_c5ebfd36-1907-48e0-9252-41809cab14c6`, validation loss 0.209
- Adapter targets `q_proj`, `k_proj`, `v_proj`, `o_proj`, r=16, alpha=8, 3 epochs.

**Where we get stuck**

1. `fine_tuned_model` on both jobs is `null`, and the checkpoint ids come back as
   `ft:Qwen/Qwen3-30B-A3B-Instruct-2507-2026-09-19:org_placeholder:contextguard-v3:IDPlaceholder:ckpt-step-9`
   — with literal `org_placeholder` and `IDPlaceholder` text. Passing either as a `model` name
   to `/v1/chat/completions` returns 404.
2. `POST /v0/dedicated_endpoints` rejects a checkpoint id: *"custom_weights_id must start with
   `model-artifact_`"*.
3. `POST /v0/model_artifacts` accepts `kind: "full"` only — not `lora` — and exactly one source,
   `{"huggingface": {"repo_id": ...}}`. `GET /v0/model_artifacts` returns 403: *"You don't have
   access to the resource or it does not exist."*

**What we're asking**

1. Can you enable the custom model weights beta on our account? (That 403 looks like the gate.)
2. Once enabled, is there a path from a Token Factory fine-tuning checkpoint straight to a
   `model-artifact_`, or do we have to merge the adapter into the 30B base and push ~60 GB to
   Hugging Face first? We've read the merge guide and our adapter matches the
   `model.layers.*.self_attn` set it supports, but 60 GB in and out is not a weekend task.
3. If neither is realistic today, is there any supported way to run one benchmark pass against
   the adapter? We only need ~50 requests to put a number next to the teacher.

**One piece of feedback, meant kindly:** the fine-tuning API is genuinely good — data upload,
training and loss curves all worked first time. But a fine-tune that can't be called by default
is half a service. If `fine_tuned_model` were populated for LoRA jobs, or `model_artifacts`
accepted a checkpoint id as a source, this would have been a ten-minute step instead of a
blocker.

Repo: https://github.com/ettoreboy/hackbarna2026-cangrejo — `docs/SERVING.md` has the full trace.

Thanks!
