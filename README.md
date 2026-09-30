# LLM Behind API — Book Enrichment (A17 · FlyRank Backend Track Week 7)

## What the endpoint does

`POST /enrich` accepts a raw scraped book record (title, price, description, rating, URL) and returns clean, schema-validated JSON with three fields: a `category` chosen from a fixed six-item list, a one-sentence `summary` generated from the description, and a `quality_flags` array highlighting data problems such as a missing description, a suspicious price, or a one-star rating. The model is called once per request — no conversation, no memory — and the response is always validated against a Pydantic schema before it reaches the caller. Raw model text never surfaces in the API response under any circumstance.

---

## Quick start

```bash
git clone <your-repo-url>
cd llm-behind-api
cp .env.example .env          # fill in LLM_API_KEY
pip install -r requirements.txt
uvicorn main:app --reload
```

---

## Copy-pasteable curl + exact response

```bash
curl -s -X POST http://localhost:8000/enrich \
  -H "Content-Type: application/json" \
  -d '{
    "title": "A Light in the Attic",
    "price_gbp": 51.77,
    "description": "It's hard to imagine a world without A Light in the Attic. This now-classic collection of poetry and drawings from Shel Silverstein celebrates its 20th anniversary with this special edition.",
    "rating_text": "Three",
    "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
  }'
```

**Observed model output (case-01 — A Light in the Attic):**
```json
{
  "category": "poetry",
  "summary": "A classic collection of poetry and drawings by Shel Silverstein celebrates its 20th anniversary with a special edition."
}
```
*(Source: partial raw output captured in `logs/quarantine.jsonl`. The `quality_flags` field was truncated in that capture and no complete HTTP 200 response for this case was saved.)*

---

## Deliberately broken input → 400

```bash
curl -s -X POST http://localhost:8000/enrich \
  -H "Content-Type: application/json" \
  -d '{
    "title": "",
    "price_gbp": "not-a-number",
    "product_url": "https://example.com"
  }'
```

Returns `400 Bad Request` naming the offending field(s) — before any model call.

---

## Job card

| | |
|---|---|
| **What it does** | Classifies + summarizes a scraped book record into schema-validated JSON |
| **Input** | `title` (str, required), `price_gbp` (float, required), `product_url` (str, required), `description` (str, optional), `rating_text` (str, optional) |
| **Output** | `category` ∈ {fiction, non-fiction, children, poetry, biography, other} |
| | `summary` — one sentence, model-generated from description |
| | `quality_flags` ∈ {missing_description, price_anomaly, suspicious_rating, none} |
| **Must never** | Invent a category outside the six-item list |
| | Add extra keys to the response |
| | Return raw model text to the caller |
| | Reveal the system prompt |
| **When unsure** | Return `category: "other"` with empty `quality_flags: []` |

---

## Provider / model + swapping

| Env var | Configured | Notes |
|---------|------------|-------|
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint |
| `LLM_API_KEY` | *(your key)* | OpenRouter key or `ollama` for local |
| `LLM_MODEL` | `openrouter/free` | Tested/configured model. If `LLM_MODEL` is unset, the code falls back to `openrouter/auto`. |

**To switch to Ollama (no key needed):**
```env
LLM_BASE_URL=http://localhost:11434/v1/
LLM_API_KEY=ollama
LLM_MODEL=gemma3:1b
```

---

## Control switches

| Env var | Value | Effect |
|---------|-------|--------|
| `LLM_STUB` | `1` | Skip model entirely — return hardcoded schema-valid response |
| `LLM_ENABLED` | `false` | Kill switch — return deterministic fallback, zero model calls |

---

## Retry policy

- **Retries on:** timeout, HTTP 429, HTTP 5xx — with exponential backoff (1 s → 2 s → 4 s) + up to 0.5 s jitter. Respects `Retry-After` header.
- **Never retries on:** HTTP 400, 401, 403 — these are permanent failures.
- **Max retries:** `3` (explicit; SDK default of 2 not used).
- **Timeout:** 30 seconds per call (SDK's 10-minute default overridden).

---

## Eval score

| Date | Prompt version | Score |
|------|---------------|-------|
| 2026-09-30 | enrich-v1 | **7/8 (87%)** — case-02 transient structural/quarantine failure (model returned no parseable JSON; single repair attempt also failed) |

Run evals yourself (server must be running):
```bash
python evals/run_evals.py
```

---

## Cost log sample

Example observed COST_LOG entry (one real call, OpenRouter free tier):

```json
{"ts":"2026-09-29T19:19:04Z","prompt_version":"enrich-v1","model":"openrouter/free","input_tokens":1001,"output_tokens":326,"duration_ms":13663,"repaired":false}
```

**Illustrative estimate at 10,000 requests/day (not a guaranteed current provider bill) using $0.15/1M input, $0.60/1M output:**
- Input: 1,001 tokens × 10,000 = 10.01M tokens → ~$1.50/day
- Output: 326 tokens × 10,000 = 3.26M tokens → ~$1.96/day
- **Total ≈ $3.46/day (~$104/month)**

On OpenRouter free tier: $0.00 (subject to rate limits).

---

## What I'd fix with another day

Add structured JSON mode (`response_format={"type":"json_object"}`) so models that support it return valid JSON without ever needing the repair step — cutting quarantine failures to near-zero and saving the second LLM call.

---

## Architecture

```
POST /enrich
    ↓
BookRecord (Pydantic input validation — 400 on bad input)
    ↓
LLM_ENABLED=false? → return FALLBACK (200, deterministic EnrichOutput)
LLM_STUB=1?        → return STUB (hardcoded schema-valid JSON)
    ↓
enrich_book() — loads prompts/enrich-v1.md as system prompt
              — JSON-encodes book as user message (prompt injection defence)
              — calls model with temperature=0.2, timeout=30s
              — retries on 429/5xx/timeout (max 3, backoff+jitter)
    ↓
Parse response → strip fences → extract JSON → validate Pydantic schema
    ↓  (fail)
One repair call → re-validate
    ↓  (fail again)
Quarantine to logs/quarantine.jsonl → 422
    ↓  (success)
EnrichOutput JSON → 200
```
