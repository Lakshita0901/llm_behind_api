"""
src/routes/enrich.py
POST /enrich — accepts a scraped book record, returns structured EnrichOutput JSON.

Behaviour summary:
  - LLM_STUB=1        → return hardcoded schema-valid response, zero model calls
  - LLM_ENABLED=false → return deterministic fallback or 503 immediately
  - Bad input         → 400 naming the offending field (before any model call)
  - Model timeout     → 504
  - Quarantined       → 422
  - Success           → 200 + EnrichOutput JSON
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from openai import APIStatusError, APITimeoutError
from pydantic import BaseModel, Field, field_validator

from src.llm.schema import Category, EnrichOutput, QualityFlag

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Input schema ──────────────────────────────────────────────────────────────

class BookRecord(BaseModel):
    title: str = Field(..., description="Book title")
    price_gbp: float = Field(..., description="Price in GBP")
    description: Optional[str] = Field(None, description="Book description (may be empty)")
    rating_text: Optional[str] = Field(None, description='e.g. "Four" or "One"')
    product_url: str = Field(..., description="Full product URL")

    @field_validator("title", "product_url")
    @classmethod
    def must_not_be_blank(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return v


# ── Stub response ─────────────────────────────────────────────────────────────

STUB_RESPONSE = EnrichOutput(
    category=Category.fiction,
    summary="A thrilling adventure story that keeps readers on the edge of their seats.",
    quality_flags=[QualityFlag.none],
)

# ── Fallback response (LLM_ENABLED=false) ─────────────────────────────────────

FALLBACK_RESPONSE = EnrichOutput(
    category=Category.other,
    summary="Book enrichment is currently unavailable; please try again later.",
    quality_flags=[QualityFlag.none],
)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/enrich",
    response_model=EnrichOutput,
    summary="Enrich a scraped book record",
    description=(
        "Accepts a raw scraped book record and returns a cleaned, "
        "schema-validated JSON object with category, summary, and quality flags."
    ),
)
async def enrich(book: BookRecord):
    # ── Kill switch ───────────────────────────────────────────────────────────
    llm_enabled = os.environ.get("LLM_ENABLED", "true").strip().lower()
    if llm_enabled == "false":
        logger.info("LLM_ENABLED=false — returning deterministic fallback")
        return FALLBACK_RESPONSE

    # ── Stub mode ─────────────────────────────────────────────────────────────
    llm_stub = os.environ.get("LLM_STUB", "").strip()
    if llm_stub == "1":
        logger.info("LLM_STUB=1 — returning stub response, zero model calls")
        return STUB_RESPONSE

    # ── Real model call ───────────────────────────────────────────────────────
    from src.llm.enrich_logic import enrich_book

    book_dict = {
        "title": book.title,
        "price_gbp": book.price_gbp,
        "description": book.description or "",
        "rating_text": book.rating_text or "",
        "product_url": book.product_url,
    }

    try:
        result = enrich_book(book_dict)
        return result

    except APITimeoutError:
        raise HTTPException(
            status_code=504,
            detail="LLM request timed out after 30 seconds. Please retry.",
        )

    except APIStatusError as exc:
        code = exc.status_code
        if code in (401, 403):
            raise HTTPException(
                status_code=502,
                detail=f"LLM authentication failed (HTTP {code}). Check your LLM_API_KEY.",
            )
        raise HTTPException(
            status_code=502,
            detail=f"LLM provider error (HTTP {code}): {exc.message}",
        )

    except ValueError as exc:
        if "quarantined" in str(exc):
            raise HTTPException(
                status_code=422,
                detail=(
                    "The model returned output that could not be validated after one repair attempt. "
                    "The failure has been logged to quarantine. Please try again."
                ),
            )
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}")

    except Exception as exc:
        logger.exception("Unexpected error in /enrich")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
