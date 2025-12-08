from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.deps import get_db, get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=schemas.AdminOverview)
def get_admin_overview(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    clubs = db.query(models.Club).order_by(models.Club.created_at.desc()).all()
    return schemas.AdminOverview(users=users, clubs=clubs)
