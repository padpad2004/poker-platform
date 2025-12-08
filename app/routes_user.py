from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app import models, schemas
from app.deps import get_db, get_current_user

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
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    owner_membership = (
        db.query(models.ClubMember)
        .filter(models.ClubMember.user_id == current_user.id, models.ClubMember.role == "owner")
        .first()
    )
    if not owner_membership:
        raise HTTPException(
            status_code=403, detail="Only club owners can adjust wallet balances"
        )

    current_user.balance += body.amount
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user

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


@router.get("/me/export")
def export_user_data(
    email: str = Query(..., description="User email"),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    memberships = (
        db.query(models.ClubMember)
        .filter(models.ClubMember.user_id == user.id)
        .all()
    )
    hand_histories = (
        db.query(models.HandHistory)
        .filter(models.HandHistory.user_id == user.id)
        .order_by(models.HandHistory.created_at.desc())
        .all()
    )

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() + "Z",
            "balance": user.balance,
            "current_club_id": user.current_club_id,
            "profile_picture_url": user.profile_picture_url,
        },
        "memberships": [
            {
                "club_id": membership.club_id,
                "club_name": membership.club.name if membership.club else None,
                "role": membership.role,
                "joined_at": membership.created_at.isoformat() + "Z",
            }
            for membership in memberships
        ],
        "hand_history": [
            {
                "id": hand.id,
                "table_name": hand.table_name,
                "result": hand.result,
                "net_change": hand.net_change,
                "summary": hand.summary,
                "created_at": hand.created_at.isoformat() + "Z",
            }
            for hand in hand_histories
        ],
    }

    filename = f"poker-user-data-{user.id}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
