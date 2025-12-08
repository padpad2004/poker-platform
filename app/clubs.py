from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from . import models, schemas
from .deps import get_db, get_current_user
from .tables_api import TABLES, TABLE_CONNECTIONS

router = APIRouter(prefix="/clubs", tags=["clubs"])


@router.post("/", response_model=schemas.ClubRead)
def create_club(
    club_in: schemas.ClubCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = models.Club(
        name=club_in.name,
        crest_url=club_in.crest_url or "/static/crests/crest-crown.svg",
        owner_id=current_user.id,
        status="inactive",
    )
    db.add(club)
    db.commit()
    db.refresh(club)

    # owner is also a member
    member = models.ClubMember(club_id=club.id, user_id=current_user.id, role="owner")
    db.add(member)
    db.commit()

    return club


@router.get("/", response_model=list[schemas.ClubRead])
def list_my_clubs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    clubs = (
        db.query(models.Club)
        .join(models.ClubMember, models.Club.id == models.ClubMember.club_id)
        .filter(models.ClubMember.user_id == current_user.id)
        .all()
    )
    return clubs


@router.post("/{club_id}/join", response_model=schemas.ClubRead)
def join_club(
    club_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    existing = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.user_id == current_user.id,
        )
        .first()
    )
    if existing:
        return club

    member = models.ClubMember(
        club_id=club_id,
        user_id=current_user.id,
        role="member",
    )
    db.add(member)
    db.commit()
    return club


@router.post("/{club_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_club(
    club_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    membership = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.user_id == current_user.id,
        )
        .first()
    )

    if not membership:
        raise HTTPException(status_code=404, detail="User is not a member of this club")

    if membership.role == "owner":
        raise HTTPException(status_code=400, detail="Club owners cannot leave their own club")

    db.delete(membership)

    if current_user.current_club_id == club_id:
        current_user.current_club_id = None
        db.add(current_user)

    db.commit()

@router.get("/{club_id}", response_model=schemas.ClubDetail)
def get_club_detail(
    club_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

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

    member_rows = (
        db.query(models.ClubMember, models.User.email.label("email"))
        .join(models.User, models.ClubMember.user_id == models.User.id)
        .filter(models.ClubMember.club_id == club_id)
        .all()
    )

    members = [
        schemas.ClubMemberRead(
            id=member.id,
            club_id=member.club_id,
            user_id=member.user_id,
            role=member.role,
            created_at=member.created_at,
            user_email=email,
        )
        for member, email in member_rows
    ]

    tables = (
        db.query(models.PokerTable)
        .filter(
            models.PokerTable.club_id == club_id,
            models.PokerTable.status == "active",
        )
        .all()
    )

    return schemas.ClubDetail(
        id=club.id,
        name=club.name,
        crest_url=club.crest_url,
        owner_id=club.owner_id,
        status=club.status,
        created_at=club.created_at,
        members=members,
        tables=tables,
    )


@router.post(
    "/{club_id}/members/{user_id}/balance",
    response_model=schemas.BalanceUpdateResponse,
)
def adjust_member_balance(
    club_id: int,
    user_id: int,
    payload: schemas.BalanceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if club.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only club owners can adjust balances")

    membership = (
        db.query(models.ClubMember)
        .filter(models.ClubMember.club_id == club_id, models.ClubMember.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="User is not a member of this club")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_balance = user.balance + payload.amount_delta
    if new_balance < 0:
        raise HTTPException(status_code=400, detail="Balance cannot be negative")

    user.balance = new_balance
    db.add(user)
    db.commit()
    db.refresh(user)

    return schemas.BalanceUpdateResponse(user_id=user.id, new_balance=user.balance)


@router.delete(
    "/{club_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    club_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if club.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only club owners can remove members")

    membership = (
        db.query(models.ClubMember)
        .filter(models.ClubMember.club_id == club_id, models.ClubMember.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="User is not a member of this club")

    if membership.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove the club owner")

    db.delete(membership)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user and user.current_club_id == club_id:
        user.current_club_id = None
        db.add(user)

    db.commit()


@router.post(
    "/{club_id}/tables",
    response_model=schemas.PokerTableMeta,
    status_code=status.HTTP_201_CREATED,
)
def open_table(
    club_id: int,
    payload: schemas.ClubTableCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if club.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only club owners can open tables",
        )

    if payload.small_blind <= 0 or payload.big_blind <= 0:
        raise HTTPException(status_code=400, detail="Blinds must be positive")
    if payload.big_blind <= payload.small_blind:
        raise HTTPException(status_code=400, detail="Big blind must exceed small blind")

    table = models.PokerTable(
        club_id=club_id,
        created_by_user_id=current_user.id,
        max_seats=payload.max_seats,
        small_blind=payload.small_blind,
        big_blind=payload.big_blind,
        bomb_pot_every_n_hands=payload.bomb_pot_every_n_hands,
        bomb_pot_amount=payload.bomb_pot_amount,
        status="active",
    )

    db.add(table)
    db.commit()
    db.refresh(table)

    return table


@router.delete(
    "/{club_id}/tables/{table_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def close_table(
    club_id: int,
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if club.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only club owners can close tables")

    table = (
        db.query(models.PokerTable)
        .filter(
            models.PokerTable.id == table_id,
            models.PokerTable.club_id == club_id,
            models.PokerTable.status == "active",
        )
        .first()
    )

    if not table:
        raise HTTPException(status_code=404, detail="Active table not found")

    table.status = "closed"
    db.add(table)
    db.commit()

    TABLES.pop(table_id, None)
    TABLE_CONNECTIONS.pop(table_id, None)
