from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from . import models, schemas
from .deps import get_db, get_current_user
from .tables_api import TABLES, TABLE_CONNECTIONS, close_table_and_report
from .club_cleanup import delete_club_with_relations

router = APIRouter(prefix="/clubs", tags=["clubs"])


def _get_owner_ids(db: Session, club_id: int) -> list[int]:
    return [
        member.user_id
        for member in db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.role == "owner",
            models.ClubMember.status == "approved",
        )
        .all()
    ]


def _owner_count(db: Session, club_id: int) -> int:
    return (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.role == "owner",
            models.ClubMember.status == "approved",
        )
        .count()
    )


def _is_club_owner(db: Session, club_id: int, user_id: int) -> bool:
    return (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.user_id == user_id,
            models.ClubMember.role == "owner",
            models.ClubMember.status == "approved",
        )
        .first()
        is not None
    )


def _ensure_club_owner(db: Session, club_id: int, user_id: int) -> models.Club:
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if not _is_club_owner(db, club_id, user_id):
        raise HTTPException(status_code=403, detail="Only club owners can perform this action")

    return club


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

    return schemas.ClubRead(
        id=club.id,
        name=club.name,
        crest_url=club.crest_url,
        owner_id=club.owner_id,
        status=club.status,
        created_at=club.created_at,
        owner_ids=[current_user.id],
        membership_role="owner",
    )


@router.patch("/{club_id}/crest", response_model=schemas.ClubRead)
def update_club_crest(
    club_id: int,
    payload: schemas.ClubCrestUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = _ensure_club_owner(db, club_id, current_user.id)

    club.crest_url = payload.crest_url or "/static/crests/crest-crown.svg"
    db.add(club)
    db.commit()
    db.refresh(club)
    return schemas.ClubRead(
        id=club.id,
        name=club.name,
        crest_url=club.crest_url,
        owner_id=club.owner_id,
        status=club.status,
        created_at=club.created_at,
        owner_ids=_get_owner_ids(db, club.id),
        membership_role="owner",
    )


@router.get("/", response_model=list[schemas.ClubRead])
def list_my_clubs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    rows = (
        db.query(models.Club, models.ClubMember.role.label("membership_role"))
        .join(models.ClubMember, models.Club.id == models.ClubMember.club_id)
        .filter(
            models.ClubMember.user_id == current_user.id,
            models.ClubMember.status == "approved",
        )
        .all()
    )
    return [
        schemas.ClubRead(
            id=club.id,
            name=club.name,
            crest_url=club.crest_url,
            owner_id=club.owner_id,
            status=club.status,
            created_at=club.created_at,
            owner_ids=_get_owner_ids(db, club.id),
            membership_role=membership_role,
        )
        for club, membership_role in rows
    ]


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
        status="pending",
    )
    db.add(member)
    db.commit()
    return schemas.ClubRead(
        id=club.id,
        name=club.name,
        crest_url=club.crest_url,
        owner_id=club.owner_id,
        status=club.status,
        created_at=club.created_at,
        owner_ids=_get_owner_ids(db, club.id),
        membership_role=member.role,
    )


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


@router.delete("/{club_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_club(
    club_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = _ensure_club_owner(db, club_id, current_user.id)

    delete_club_with_relations(club, db)
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

    owner_ids = _get_owner_ids(db, club.id)
    is_owner = _is_club_owner(db, club.id, current_user.id)
    is_member = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club.id,
            models.ClubMember.user_id == current_user.id,
            models.ClubMember.status == "approved",
        )
        .first()
        is not None
    )
    if not (is_owner or is_member):
        raise HTTPException(status_code=403, detail="Not a member of this club")

    member_rows = (
        db.query(
            models.ClubMember,
            models.User.email.label("email"),
            models.User.balance.label("balance"),
        )
        .join(models.User, models.ClubMember.user_id == models.User.id)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.status == "approved",
        )
        .all()
    )

    members = [
        schemas.ClubMemberRead(
            id=member.id,
            club_id=member.club_id,
            user_id=member.user_id,
            role=member.role,
            status=member.status,
            created_at=member.created_at,
            user_email=email,
            balance=balance,
        )
        for member, email, balance in member_rows
    ]

    tables = (
        db.query(models.PokerTable)
        .filter(
            models.PokerTable.club_id == club_id,
            models.PokerTable.status == "active",
        )
        .all()
    )

    expiry_cutoff = datetime.utcnow() - timedelta(hours=24)
    for table in list(tables):
        if table.created_at < expiry_cutoff:
            close_table_and_report(table, db)

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
        owner_ids=owner_ids,
        status=club.status,
        created_at=club.created_at,
        members=members,
        tables=tables,
    )


@router.get("/{club_id}/pending-members", response_model=list[schemas.ClubMemberRead])
def list_pending_members(
    club_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_club_owner(db, club_id, current_user.id)

    pending_rows = (
        db.query(
            models.ClubMember,
            models.User.email.label("email"),
            models.User.balance.label("balance"),
        )
        .join(models.User, models.ClubMember.user_id == models.User.id)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.status == "pending",
        )
        .all()
    )

    return [
        schemas.ClubMemberRead(
            id=member.id,
            club_id=member.club_id,
            user_id=member.user_id,
            role=member.role,
            status=member.status,
            created_at=member.created_at,
            user_email=email,
            balance=balance,
        )
        for member, email, balance in pending_rows
    ]


@router.post("/{club_id}/pending-members/{user_id}/approve", response_model=schemas.ClubMemberRead)
def approve_pending_member(
    club_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_club_owner(db, club_id, current_user.id)

    membership = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.user_id == user_id,
            models.ClubMember.status == "pending",
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Pending member not found")

    membership.status = "approved"
    db.add(membership)
    db.commit()
    db.refresh(membership)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    balance = user.balance if user else 0
    email = user.email if user else ""

    return schemas.ClubMemberRead(
        id=membership.id,
        club_id=membership.club_id,
        user_id=membership.user_id,
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
        user_email=email,
        balance=balance,
    )


@router.delete("/{club_id}/pending-members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deny_pending_member(
    club_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_club_owner(db, club_id, current_user.id)

    membership = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.user_id == user_id,
            models.ClubMember.status == "pending",
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Pending member not found")

    db.delete(membership)
    db.commit()


@router.get("/{club_id}/game-history", response_model=list[schemas.TableReportEntry])
def get_club_game_history(
    club_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    is_owner = _is_club_owner(db, club.id, current_user.id)
    is_member = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club.id,
            models.ClubMember.user_id == current_user.id,
            models.ClubMember.status == "approved",
        )
        .first()
        is not None
    )
    if not (is_owner or is_member):
        raise HTTPException(status_code=403, detail="Not a member of this club")

    rows = (
        db.query(models.TableReportEntry, models.TableReport.generated_at)
        .join(
            models.TableReport,
            models.TableReport.id == models.TableReportEntry.table_report_id,
        )
        .filter(models.TableReport.club_id == club_id)
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


@router.patch(
    "/{club_id}/members/{user_id}/role",
    response_model=schemas.ClubMemberRead,
)
def update_member_role(
    club_id: int,
    user_id: int,
    payload: schemas.ClubRoleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_club_owner(db, club_id, current_user.id)

    membership = (
        db.query(models.ClubMember)
        .filter(
            models.ClubMember.club_id == club_id,
            models.ClubMember.user_id == user_id,
            models.ClubMember.status == "approved",
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="User is not an approved member of this club")

    if membership.role == "owner" and payload.role != "owner" and _owner_count(db, club_id) <= 1:
        raise HTTPException(status_code=400, detail="At least one owner is required for each club")

    membership.role = payload.role
    db.add(membership)
    db.commit()
    db.refresh(membership)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    balance = user.balance if user else 0
    email = user.email if user else ""

    return schemas.ClubMemberRead(
        id=membership.id,
        club_id=membership.club_id,
        user_id=membership.user_id,
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
        user_email=email,
        balance=balance,
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
    club = _ensure_club_owner(db, club_id, current_user.id)

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
    club = _ensure_club_owner(db, club_id, current_user.id)

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
    _ensure_club_owner(db, club_id, current_user.id)

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
    _ensure_club_owner(db, club_id, current_user.id)

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

    close_table_and_report(table, db)
    TABLE_CONNECTIONS.pop(table_id, None)
