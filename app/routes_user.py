from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app import models, schemas
from app.deps import get_db, get_current_user

router = APIRouter(tags=["users"])

UK_UNIVERSITIES = [
    "AECC University College",
    "Abertay University",
    "Aberystwyth University",
    "Anglia Ruskin University",
    "Arden University",
    "Arts University Bournemouth",
    "Aston University",
    "Bangor University",
    "Bath Spa University",
    "Birkbeck, University of London",
    "Birmingham City University",
    "Bournemouth University",
    "BPP University",
    "Brunel University London",
    "Buckinghamshire New University",
    "Canterbury Christ Church University",
    "Cardiff Metropolitan University",
    "Cardiff University",
    "City, University of London",
    "Coventry University",
    "Cranfield University",
    "Durham University",
    "Edge Hill University",
    "Edinburgh Napier University",
    "Falmouth University",
    "Glasgow Caledonian University",
    "Guildhall School of Music and Drama",
    "Harper Adams University",
    "Hartpury University",
    "Heriot-Watt University",
    "Imperial College London",
    "Keele University",
    "King's College London",
    "Kingston University",
    "Lancaster University",
    "Leeds Arts University",
    "Leeds Beckett University",
    "Leeds Conservatoire",
    "Leeds Trinity University",
    "Liverpool Hope University",
    "Liverpool John Moores University",
    "London Business School",
    "London Metropolitan University",
    "London School of Economics and Political Science",
    "London South Bank University",
    "Loughborough University",
    "Manchester Metropolitan University",
    "Middlesex University",
    "Newcastle University",
    "Newman University, Birmingham",
    "Northumbria University",
    "Norwich University of the Arts",
    "Nottingham Trent University",
    "The Open University",
    "Oxford Brookes University",
    "Plymouth Marjon University",
    "Queen Margaret University",
    "Queen Mary University of London",
    "Queen's University Belfast",
    "Ravensbourne University London",
    "Regent's University London",
    "Richmond American University London",
    "Robert Gordon University",
    "Royal Academy of Music",
    "Royal Agricultural University",
    "Royal Central School of Speech and Drama",
    "Royal College of Art",
    "Royal College of Music",
    "Royal Conservatoire of Scotland",
    "Royal Holloway, University of London",
    "Royal Northern College of Music",
    "Royal Veterinary College",
    "Sheffield Hallam University",
    "Solent University",
    "St George's, University of London",
    "St Mary's University, Twickenham",
    "Staffordshire University",
    "Swansea University",
    "Teesside University",
    "The Courtauld Institute of Art",
    "The University of Law",
    "Trinity Laban Conservatoire of Music and Dance",
    "Ulster University",
    "University College Birmingham",
    "University College London",
    "University for the Creative Arts",
    "University of Aberdeen",
    "University of Bath",
    "University of Bedfordshire",
    "University of Birmingham",
    "University of Bolton",
    "University of Bradford",
    "University of Brighton",
    "University of Bristol",
    "University of Buckingham",
    "University of Cambridge",
    "University of Central Lancashire",
    "University of Chester",
    "University of Chichester",
    "University of Cumbria",
    "University of Derby",
    "University of Dundee",
    "University of East Anglia",
    "University of East London",
    "University of Edinburgh",
    "University of Essex",
    "University of Exeter",
    "University of Glasgow",
    "University of Gloucestershire",
    "University of Greenwich",
    "University of Hertfordshire",
    "University of the Highlands and Islands",
    "University of Huddersfield",
    "University of Hull",
    "University of Kent",
    "University of Leeds",
    "University of Leicester",
    "University of Lincoln",
    "University of Liverpool",
    "University of London",
    "University of Manchester",
    "University of Northampton",
    "University of Northumbria at Newcastle",
    "University of Nottingham",
    "University of Oxford",
    "University of Plymouth",
    "University of Portsmouth",
    "University of Reading",
    "University of Roehampton",
    "University of Salford",
    "University of Sheffield",
    "University of South Wales",
    "University of Southampton",
    "University of St Andrews",
    "University of Stirling",
    "University of Strathclyde",
    "University of Suffolk",
    "University of Sunderland",
    "University of Surrey",
    "University of Sussex",
    "University of the Arts London",
    "University of the West of England",
    "University of the West of Scotland",
    "University of Wales Trinity Saint David",
    "University of Warwick",
    "University of Westminster",
    "University of West London",
    "University of Winchester",
    "University of Wolverhampton",
    "University of Worcester",
    "University of York",
    "Wrexham University",
    "York St John University",
]

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

    membership = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club.id,
            models.ClubMember.user_id == user.id,
            models.ClubMember.status == "approved",
        )
        .first()
    )
    if not membership and club.owner_id != user.id:
        raise HTTPException(status_code=403, detail="User is not approved for this club")

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
    club_id = user.current_club_id

    if not club_id:
        membership = (
            db.query(models.ClubMember)
            .filter(
                models.ClubMember.user_id == user.id,
                models.ClubMember.status == "approved",
            )
            .order_by(models.ClubMember.created_at.desc())
            .first()
        )
        if membership:
            club_id = membership.club_id

    if club_id:
        club = db.query(models.Club).filter(models.Club.id == club_id).first()
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
        current_club_id=club_id,
        profile_picture_url=user.profile_picture_url,
        university=user.university,
        current_club_name=club_name,
        hand_history=hand_rows,
    )


@router.get("/me/game-history", response_model=list[schemas.TableReportEntry])
def get_game_history(
    email: str = Query(..., description="User email"),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = (
        db.query(models.TableReportEntry, models.TableReport.generated_at)
        .join(
            models.TableReport,
            models.TableReport.id == models.TableReportEntry.table_report_id,
        )
        .filter(models.TableReportEntry.user_id == user.id)
        .order_by(models.TableReport.generated_at.desc())
        .all()
    )

    return [
        schemas.TableReportEntry(
            table_report_id=entry.table_report_id,
            table_id=entry.table_id,
            club_id=entry.club_id,
            user_id=entry.user_id,
            buy_in=entry.buy_in,
            cash_out=entry.cash_out,
            profit_loss=entry.profit_loss,
            generated_at=generated_at,
        )
        for entry, generated_at in rows
    ]


class UniversityUpdateRequest(BaseModel):
    university: str | None = None


@router.post("/me/university", response_model=schemas.UserMe)
def update_university(
    body: UniversityUpdateRequest,
    email: str = Query(..., description="User email"),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.university and body.university not in UK_UNIVERSITIES:
        raise HTTPException(status_code=400, detail="Invalid university selection")

    user.university = body.university or None
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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
            "university": user.university,
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
