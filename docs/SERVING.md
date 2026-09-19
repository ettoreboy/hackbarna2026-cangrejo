# Serving the fine-tuned model on Nebius

Answering "how do I create an endpoint with my model, and how do I call it?" from the Nebius
docs, checked against the live API on 19 September 2026.

## The short answer

**Custom weights are beta and gated.** The docs say so outright:

> Working with custom model weights is currently in beta and available on request. If you'd
> like to deploy or work with custom fine-tuned model weights, please contact our Support team
> to enable access.

`GET /v0/model_artifacts` returns 403 on this account, which is that gate. **Nothing else can be
done until someone at Nebius enables it.** Everything below is ready to run the moment they do.

## Why the checkpoint is not directly servable

A fine-tuning job does not produce a callable model:

- the job's `fine_tuned_model` is `null`
- checkpoint ids read `ft:Qwen/...:org_placeholder:contextguard-v3:IDPlaceholder:ckpt-step-9`
- using either as a `model` name returns 404

A dedicated endpoint takes `custom_weights_id`, which must start with `model-artifact_`. Model
artifacts are created at `POST /v0/model_artifacts`, which accepts `kind: "full"` only — never
`lora` — and exactly one source, `{"huggingface": {"repo_id": ...}}`. So the adapter has to be
merged into the base weights and published before anything can serve it.

## The five steps

### 1. Get beta access

https://tokenfactory.nebius.com/?modals=contact-us, or ask a Nebius mentor at the event. This
is the only blocking step.

### 2. Merge the adapter into the base weights

Nebius publishes the script: https://docs.tokenfactory.nebius.com/post-training/merge-moe-lora-weights

Our adapter targets `q_proj`, `k_proj`, `v_proj`, `o_proj`, which is exactly the
`model.layers.*.self_attn` set the script supports, so it merges without modification.

```bash
pip install safetensors huggingface_hub transformers peft torch
hf download Qwen/Qwen3-30B-A3B-Instruct-2507 --local-dir qwen3-30b-base
python merge_lora.py -i qwen3-30b-base -l artifacts/contextguard-v3-2-lora -o qwen3-30b-contextguard
```

Needs roughly 130 GB of disk: about 61 GB for the base and the same again for the merged copy.
Not a laptop job.

### 3. Publish the merged checkpoint to Hugging Face

```bash
hf upload <org>/qwen3-30b-contextguard qwen3-30b-contextguard
```

### 4. Register it as a model artifact

```bash
curl -X POST https://api.tokenfactory.nebius.com/v0/model_artifacts \
  -H "Authorization: Bearer $NEBIUS_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "contextguard-v3-2",
       "base_model_slug": "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8",
       "kind": "full",
       "source": {"huggingface": {"repo_id": "<org>/qwen3-30b-contextguard"}}}'
```

Returns an id starting `model-artifact_`.

### 5. Create the endpoint and call it

```bash
.venv/bin/python -m backend.eval.serve_finetune --custom-weights model-artifact_xxx
```

Two things that are easy to get wrong when calling it:

- **The model name is the `routing_key`** the create call returns, not the endpoint id and not
  the model slug.
- **The base URL is regional, not the global one.** An endpoint in `us-central1` is called at
  `https://api.tokenfactory.us-central1.nebius.com/v1`. Requests to
  `https://api.tokenfactory.nebius.com/v1` will not find it.

Once running, point the whole app at it with no code change:

```bash
NEBIUS_MODEL=<routing_key> \
NEBIUS_BASE_URL=https://api.tokenfactory.us-central1.nebius.com/v1/ \
.venv/bin/python scripts/check_nebius.py --post spec_example
```

**A dedicated endpoint bills per GPU-hour from the moment it is created.** Delete it after the
demo: `.venv/bin/python -m backend.eval.serve_finetune --delete <endpoint_id>`.

## The fallback, if beta access does not arrive

Merge the adapter (step 2) and serve it locally with vLLM on any 80 GB GPU. The merged
directory is a standard checkpoint, so `vllm serve qwen3-30b-contextguard` exposes the same
OpenAI-compatible API and the two environment variables above still switch the app onto it.

Failing that, the fine-tune stands as a measured result — dataset, method, loss curve — and
`openai/gpt-oss-120b` stays the served model.
