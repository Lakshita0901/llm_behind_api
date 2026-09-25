"""
main.py
FastAPI application entry point.
Run with:  uvicorn main:app --reload
"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── App factory ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting LLM-behind-API service")
    logger.info("Model: %s", os.environ.get("LLM_MODEL", "not set"))
    logger.info("Base URL: %s", os.environ.get("LLM_BASE_URL", "not set"))
    stub = os.environ.get("LLM_STUB", "")
    enabled = os.environ.get("LLM_ENABLED", "true")
    logger.info("LLM_STUB=%r  LLM_ENABLED=%r", stub, enabled)
    yield
    logger.info("Shutting down LLM-behind-API service")


app = FastAPI(
    title="LLM Behind API — Book Enrichment",
    description=(
        "FlyRank Backend Track Week 7 (A17). "
        "POST /enrich turns a messy scraped book record into clean structured JSON."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
from src.routes.enrich import router as enrich_router
app.include_router(enrich_router, prefix="/api/v1", tags=["enrichment"])

# Also expose at root for convenience
from src.routes.enrich import router as enrich_router_root
app.include_router(enrich_router_root, tags=["enrichment"])


@app.get("/health", tags=["ops"])
async def health():
    return {
        "status": "ok",
        "llm_enabled": os.environ.get("LLM_ENABLED", "true"),
        "llm_stub": os.environ.get("LLM_STUB", ""),
        "model": os.environ.get("LLM_MODEL", "not set"),
    }
