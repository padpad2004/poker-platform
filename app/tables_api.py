from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import models, schemas
from .deps import get_db, get_current_user

router = APIRouter(prefix="/tables", tags=["tables"])


def _ensure_user_in_table_club(
    table_id: int,
    db: Session,
    current_user: models.User,
) -> models.PokerTable:
    table_meta = db.query(models.PokerTable).filter(models.PokerTable.id == table_id).first()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    club = table_meta.club
    is_owner = club.owner_id == current_user.id
    is_member = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club.id,
            models.ClubMember.user_id == current_user.id,
        )
        .first()
        is not None
    )
    if not (is_owner or is_member):
        raise HTTPException(status_code=403, detail="Not a member of this club")

    return table_meta


@router.get("/", response_model=list[schemas.PokerTableMeta])
def list_my_tables(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """List tables within clubs the user belongs to."""

    return (
        db.query(models.PokerTable)
        .join(models.Club, models.PokerTable.club_id == models.Club.id)
        .join(models.ClubMember, models.ClubMember.club_id == models.Club.id)
        .filter(models.ClubMember.user_id == current_user.id)
        .all()
    )


@router.get("/{table_id}", response_model=schemas.PokerTableMeta)
def get_table(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Return metadata for a table within a club the user can access."""

    return _ensure_user_in_table_club(table_id, db, current_user)
