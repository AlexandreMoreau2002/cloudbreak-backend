"""
Endpoints peaks.

Endpoints :
  GET  /api/v1/peaks/search?q=    — recherche autocomplete (min 2 chars)
  GET  /api/v1/peaks/{slug}        — détail par slug

Publics depuis la story 7.1 (onboarding mobile pré-login) : aucune auth requise.
"""

import logging
from typing import Annotated
from sqlalchemy import select
from app.models.peak import Peak
from app.db.session import get_db
from app.core.errors import ErrorCode
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.peak import PeakResponse, PeakSearchResult
from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["peaks"])


def _optional_region(value: object) -> str | None:
    return value if isinstance(value, str) else None


@router.get("/peaks/search", response_model=list[PeakSearchResult])
async def search_peaks(
    q: Annotated[str, Query(min_length=2, description="Texte de recherche (min 2 chars)")],
    db: AsyncSession = Depends(get_db),
) -> list[PeakSearchResult]:
    """Recherche autocomplete sur le nom des sommets — ILIKE, limite 20 résultats."""
    result = await db.execute(
        select(Peak).where(Peak.name.ilike(f"%{q}%")).order_by(Peak.name).limit(20)
    )
    peaks = result.scalars().all()
    logger.debug("peaks_search", extra={"q": q, "count": len(peaks)})
    return [
        PeakSearchResult(
            id=str(p.id),
            name=str(p.name),
            slug=str(p.slug),
            altitude=int(p.altitude),
            region=_optional_region(p.region),
        )
        for p in peaks
    ]


@router.get("/peaks/{slug}", response_model=PeakResponse)
async def get_peak(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> PeakResponse:
    """Récupère le détail d'un sommet par son slug."""
    result = await db.execute(select(Peak).where(Peak.slug == slug))
    peak = result.scalar_one_or_none()
    if not peak:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Sommet introuvable", "code": ErrorCode.PEAK_NOT_FOUND},
        )
    logger.debug("peak_detail", extra={"slug": slug})
    return PeakResponse(
        id=str(peak.id),
        name=str(peak.name),
        slug=str(peak.slug),
        lat=float(peak.lat),
        lng=float(peak.lng),
        altitude=int(peak.altitude),
        region=_optional_region(peak.region),
    )
