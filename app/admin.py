from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.deps import get_db, get_current_user
from app.tables_api import TABLES, TABLE_CONNECTIONS

router = APIRouter(prefix="/admin", tags=["admin"])

SITE_ADMIN_EMAILS = {"paddywarren99@gmail.com", "padpadpoker@gmail.com"}


def require_site_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.email.lower() not in {email.lower() for email in SITE_ADMIN_EMAILS}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def _delete_club_with_relations(club: models.Club, db: Session) -> None:
    tables = db.query(models.PokerTable).filter(models.PokerTable.club_id == club.id).all()
    for table in tables:
        TABLES.pop(table.id, None)
        TABLE_CONNECTIONS.pop(table.id, None)
        db.delete(table)

    db.query(models.ClubMember).filter(models.ClubMember.club_id == club.id).delete(
        synchronize_session=False
    )

    db.query(models.User).filter(models.User.current_club_id == club.id).update(
        {"current_club_id": None}, synchronize_session=False
    )

    db.delete(club)


@router.get("/overview", response_model=schemas.AdminOverview)
def get_admin_overview(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_site_admin),
):
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    clubs = db.query(models.Club).order_by(models.Club.created_at.desc()).all()
    return schemas.AdminOverview(users=users, clubs=clubs)


@router.delete("/clubs/{club_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_club(
    club_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_site_admin),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Club not found")

    _delete_club_with_relations(club, db)
    db.commit()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_site_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.email.lower() in {email.lower() for email in SITE_ADMIN_EMAILS}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete admin user")

    owned_clubs = db.query(models.Club).filter(models.Club.owner_id == user.id).all()
    for club in owned_clubs:
        _delete_club_with_relations(club, db)

    tables_created = (
        db.query(models.PokerTable)
        .filter(models.PokerTable.created_by_user_id == user.id)
        .all()
    )
    for table in tables_created:
        TABLES.pop(table.id, None)
        TABLE_CONNECTIONS.pop(table.id, None)
        db.delete(table)

    db.query(models.ClubMember).filter(models.ClubMember.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(models.HandHistory).filter(models.HandHistory.user_id == user.id).delete(
        synchronize_session=False
    )

    db.delete(user)
    db.commit()


@router.post("/users/{user_id}/approve", response_model=schemas.AdminUser)
def approve_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_site_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.is_active:
        return user

    user.is_active = True
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
