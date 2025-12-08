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
    await broadcast_table_state(table_id)
    return schemas.AddPlayerResponse(table_id=table_id, player_id=player.id, seat=player.seat)


@router.post("/{table_id}/sit_me", response_model=schemas.AddPlayerResponse)
async def sit_me(
    table_id: int,
    req: schemas.SitMeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id)

    for p in engine_table.players:
        if p.user_id == current_user.id:
            raise HTTPException(status_code=400, detail="User already seated at this table")

    if req.buy_in <= 0:
        raise HTTPException(status_code=400, detail="Buy-in must be positive")

    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.balance < req.buy_in:
        raise HTTPException(status_code=400, detail="Insufficient balance for buy-in")

    try:
        player = engine_table.add_player(
            player_id=len(engine_table.players) + 1,
            name=current_user.username,
            starting_stack=req.buy_in,
            user_id=current_user.id,
            seat=req.seat,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user.balance -= req.buy_in
    db.add(user)
    db.commit()
    db.refresh(user)

    await broadcast_table_state(table_id)
    return schemas.AddPlayerResponse(table_id=table_id, player_id=player.id, seat=player.seat)


@router.post("/{table_id}/start_hand", response_model=schemas.TableState)
async def start_hand(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
): 
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id)
    engine_table.start_new_hand()
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table)


@router.post("/{table_id}/action", response_model=schemas.TableState)
async def player_action(
    table_id: int,
    req: schemas.ActionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id)
    try:
        engine_table.player_action(req.player_id, req.action, req.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    hand_finished = _auto_progress_hand(engine_table)
    if hand_finished:
        _auto_start_hand_if_ready(engine_table)
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table)


@router.post("/{table_id}/deal_flop", response_model=schemas.TableState)
async def deal_flop(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
): 
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id)
    engine_table.deal_flop()
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table)


@router.post("/{table_id}/deal_turn", response_model=schemas.TableState)
async def deal_turn(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id)
    engine_table.deal_turn()
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table)


@router.post("/{table_id}/deal_river", response_model=schemas.TableState)
async def deal_river(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id)
    engine_table.deal_river()
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table)


@router.get("/{table_id}", response_model=schemas.TableState)
async def get_table_state(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id)
    return _table_state(table_id, engine_table)


@router.get("/{table_id}", response_model=schemas.PokerTableMeta)
def get_table(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Return metadata for a table within a club the user can access."""

    return _ensure_user_in_table_club(table_id, db, current_user)
