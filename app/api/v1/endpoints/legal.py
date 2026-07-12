"""Endpoints légaux — Privacy Policy et CGU (story 4.4 AC1).

Sert les pages HTML statiques stockées dans app/legal/ sur des routes
sans extension, exigées par Apple pour les liens légaux (paywall, App
Store Connect).
"""

import os
import logging
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/legal", tags=["legal"])

_LEGAL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "legal")


def _read_legal_page(filename: str) -> str:
    path = os.path.join(_LEGAL_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> HTMLResponse:
    logger.debug("legal_page_served", extra={"page": "privacy"})
    return HTMLResponse(content=_read_legal_page("privacy.html"))


@router.get("/cgu", response_class=HTMLResponse)
async def cgu() -> HTMLResponse:
    logger.debug("legal_page_served", extra={"page": "cgu"})
    return HTMLResponse(content=_read_legal_page("cgu.html"))
