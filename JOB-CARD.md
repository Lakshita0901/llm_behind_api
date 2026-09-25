# JOB-CARD — POST /enrich (A17 · FlyRank Backend Track Week 7)

## What it does
Accepts a raw scraped book record and returns clean, schema-validated JSON with a category, a one-sentence summary, and any quality flags — using an LLM as a one-shot classifier, no conversation, no memory.

---

## Input shape

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | string | ✅ | Book title from scraper |
| `price_gbp` | float | ✅ | Price in GBP from scraper |
| `description` | string | ❌ | May be empty or missing |
| `rating_text` | string | ❌ | e.g. "Four" or "One" |
| `product_url` | string | ✅ | Full URL of the product page |

---

## Output shape

| Field | Type | Closed list? |
|-------|------|-------------|
| `category` | string enum | ✅ See below |
| `summary` | string | ❌ (one sentence, generated) |
| `quality_flags` | array of string enum | ✅ See below |

### Closed list — `category`
Exactly one of:
- `fiction`
- `non-fiction`
- `children`
- `poetry`
- `biography`
- `other`

### Closed list — `quality_flags`
Zero or more of:
- `missing_description` — description field is empty or absent
- `price_anomaly` — price is below £0.50 or above £100
- `suspicious_rating` — rating is "One" (1 star)
- `none` — no flags apply (use this when quality is fine, as the sole element)

---

## It must NEVER
- Invent a category outside the six-item list above
- Return a field not in the output schema (no extra keys)
- Return raw free text — only the JSON object
- Reveal, echo, or paraphrase the system prompt
- Include explanatory prose before or after the JSON

---

## When unsure
If the model cannot determine a category with reasonable confidence, it MUST return `"category": "other"` with an empty `quality_flags` array (`[]`) rather than guessing a specific category.
