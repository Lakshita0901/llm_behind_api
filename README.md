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
    "title": "The Shadow of the Wind",
    "price_gbp": 12.99,
    "description": "A young boy discovers a mysterious book and embarks on a quest to find its author.",
    "rating_text": "Five",
    "product_url": "https://books.toscrape.com/catalogue/shadow-of-the-wind_1.html"
  }'
```

**Exact response:**
```json
{
  "category": "fiction",
  "summary": "A young boy's discovery of a mysterious book sets him on an unforgettable journey through post-war Barcelona.",
  "quality_flags": ["none"]
}
```

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

| Env var | Default | Notes |
|---------|---------|-------|
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint |
| `LLM_API_KEY` | *(your key)* | OpenRouter key or `ollama` for local |
| `LLM_MODEL` | `openrouter/auto` | Any model name the provider accepts |

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
| 2026-09-25 | enrich-v1 | **7/8 (87%)** — case-05 category ambiguous (non-fiction vs children) |

Run evals yourself (server must be running):
```bash
python evals/run_evals.py
```

---

## Cost log sample

One real call (OpenRouter free tier):

```json
{"ts":"2026-09-25T12:30:01Z","prompt_version":"enrich-v1","model":"openrouter/auto","input_tokens":412,"output_tokens":48,"duration_ms":1840,"repaired":false}
```

**Estimated cost at 10,000 requests/day on a paid model (e.g., GPT-4o-mini at $0.15/1M input, $0.60/1M output):**
- Input: 412 tokens × 10,000 = 4.12M tokens → ~$0.62/day
- Output: 48 tokens × 10,000 = 0.48M tokens → ~$0.29/day
- **Total ≈ $0.91/day (~$27/month)**

On OpenRouter free tier: $0.00 (subject to 50 req/day and rate limits).

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
LLM_ENABLED=false? → return FALLBACK (503 / deterministic)
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
