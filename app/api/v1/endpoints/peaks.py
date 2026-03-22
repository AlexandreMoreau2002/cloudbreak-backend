"""
Endpoints peaks et favoris.

Endpoints :
  GET  /api/v1/peaks/search?q=    — recherche autocomplete (min 2 chars)
  GET  /api/v1/peaks/{slug}        — détail par slug
  POST /api/v1/user/favorites      — ajouter un favori
  DELETE /api/v1/user/favorites/{peak_id} — retirer un favori
  GET  /api/v1/user/favorites      — lister les favoris

Auth required sur tous les endpoints.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.peak import Peak
from app.core.errors import ErrorCode
from app.models.favorite import Favorite
from app.core.dependencies import get_current_user
from app.schemas.peak import PeakResponse, PeakSearchResult
from app.schemas.favorite import FavoriteCreate, FavoriteResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["peaks"])


# ---------------------------------------------------------------------------
# Peaks — search + detail
# ---------------------------------------------------------------------------


@router.get("/peaks/search", response_model=list[PeakSearchResult])
async def search_peaks(
    q: Annotated[str, Query(min_length=2, description="Texte de recherche (min 2 chars)")],
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PeakSearchResult]:
    """Recherche autocomplete sur le nom des sommets — ILIKE, limite 20 résultats."""
    result = await db.execute(
        select(Peak).where(Peak.name.ilike(f"%{q}%")).order_by(Peak.name).limit(20)
    )
    peaks = result.scalars().all()
    logger.debug("peaks_search", extra={"q": q, "count": len(peaks)})
    return [
        PeakSearchResult(id=str(p.id), name=str(p.name), slug=str(p.slug), altitude=int(p.altitude))
        for p in peaks
    ]


@router.get("/peaks/{slug}", response_model=PeakResponse)
async def get_peak(
    slug: str,
    current_user: dict[str, Any] = Depends(get_current_user),
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
    )


# ---------------------------------------------------------------------------
# Favoris
# ---------------------------------------------------------------------------


@router.post(
    "/user/favorites", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED
)
async def add_favorite(
    body: FavoriteCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteResponse:
    """Ajoute un sommet aux favoris de l'utilisateur."""
    user_id = str(current_user["id"])

    # Vérifier que le sommet existe
    peak_result = await db.execute(select(Peak).where(Peak.id == body.peak_id))
    peak = peak_result.scalar_one_or_none()
    if not peak:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Sommet introuvable", "code": ErrorCode.PEAK_NOT_FOUND},
        )

    # Vérifier doublon
    existing = await db.execute(
        select(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.peak_id == body.peak_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "Sommet déjà en favoris", "code": ErrorCode.ALREADY_EXISTS},
        )

    fav = Favorite(user_id=user_id, peak_id=body.peak_id)
    db.add(fav)
    await db.commit()
    await db.refresh(fav)

    logger.info("favorite_added", extra={"user_id": user_id, "peak_id": body.peak_id})
    return FavoriteResponse(
        id=str(fav.id),
        peak_id=str(fav.peak_id),
        peak=PeakSearchResult(
            id=str(peak.id), name=str(peak.name), slug=str(peak.slug), altitude=int(peak.altitude)
        ),
        created_at=fav.created_at,  # type: ignore[arg-type]
    )


@router.delete("/user/favorites/{peak_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    peak_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Retire un sommet des favoris de l'utilisateur."""
    user_id = str(current_user["id"])

    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.peak_id == peak_id,
        )
    )
    fav = result.scalar_one_or_none()
    if not fav:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Favori introuvable", "code": ErrorCode.NOT_FOUND},
        )

    await db.delete(fav)
    await db.commit()
    logger.info("favorite_removed", extra={"user_id": user_id, "peak_id": peak_id})


@router.get("/user/favorites", response_model=list[FavoriteResponse])
async def list_favorites(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FavoriteResponse]:
    """Liste les favoris de l'utilisateur avec le détail du sommet."""
    user_id = str(current_user["id"])

    result = await db.execute(
        select(Favorite, Peak)
        .join(Peak, Favorite.peak_id == Peak.id)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
    )
    rows = result.all()

    logger.debug("favorites_list", extra={"user_id": user_id, "count": len(rows)})
    return [
        FavoriteResponse(
            id=str(fav.id),
            peak_id=str(fav.peak_id),
            peak=PeakSearchResult(
                id=str(peak.id),
                name=str(peak.name),
                slug=str(peak.slug),
                altitude=int(peak.altitude),
            ),
            created_at=fav.created_at,
        )
        for fav, peak in rows
    ]
