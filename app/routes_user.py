from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import SessionLocal
from app import models, schemas

# Local get_db using SessionLocal from app.database
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter(tags=["users"])

# ---------- /me ----------
# We identify the user by their email query param.

@router.get("/me", response_model=schemas.UserMe)
def read_me(
    email: str = Query(..., description="User email"),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


class UpdateProfilePictureRequest(BaseModel):
    profile_picture_url: str


@router.post("/me/profile-picture", response_model=schemas.UserMe)
def update_profile_picture(
    body: UpdateProfilePictureRequest,
    email: str = Query(..., description="User email"),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.profile_picture_url = body.profile_picture_url.strip() or None
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

# ---------- /wallet/topup ----------

class TopUpRequest(BaseModel):
    amount: int

@router.post("/wallet/topup", response_model=schemas.UserMe)
def wallet_topup(
    body: TopUpRequest,
    email: str = Query(..., description="User email"),
    db: Session = Depends(get_db),
):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.balance += body.amount
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

# ---------- /me/club (remember active club) ----------

class SetClubRequest(BaseModel):
    club_id: int

@router.post("/me/club", response_model=schemas.UserMe)
def set_current_club(
    body: SetClubRequest,
    email: str = Query(..., description="User email"),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    club = db.query(models.Club).filter(models.Club.id == body.club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    user.current_club_id = club.id
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me/profile", response_model=schemas.ProfileResponse)
def get_profile(
    email: str = Query(..., description="User email"),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    club_name = None
    if user.current_club_id:
        club = db.query(models.Club).filter(models.Club.id == user.current_club_id).first()
        club_name = club.name if club else None

    hand_rows = (
        db.query(models.HandHistory)
        .filter(models.HandHistory.user_id == user.id)
        .order_by(models.HandHistory.created_at.desc())
        .limit(20)
        .all()
    )

    return schemas.ProfileResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        balance=user.balance,
        current_club_id=user.current_club_id,
        profile_picture_url=user.profile_picture_url,
        current_club_name=club_name,
        hand_history=hand_rows,
    )
