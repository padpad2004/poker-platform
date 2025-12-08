from typing import Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.orm import Session

from app.poker.table import Table
from . import models, schemas
from .deps import get_current_user, get_db

router = APIRouter(prefix="/tables", tags=["tables"])

# In-memory engine tables
TABLES: Dict[int, Table] = {}

# WebSocket connections per table: table_id -> { websocket: viewer_user_id or None }
TABLE_CONNECTIONS: Dict[int, Dict[WebSocket, Optional[int]]] = {}
# WebSocket connections keyed by seated user_id so we can notify all players at a table
USER_CONNECTIONS: Dict[int, Set[WebSocket]] = {}


def _get_engine_table(table_id: int, db: Session | None = None) -> Table:
    table = TABLES.get(table_id)
    if table:
        return table

    if db is None:
        raise HTTPException(status_code=404, detail="Engine table not found")

    table_meta = db.query(models.PokerTable).filter(models.PokerTable.id == table_id).first()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    table = Table(
        max_seats=table_meta.max_seats,
        small_blind=table_meta.small_blind,
        big_blind=table_meta.big_blind,
        bomb_pot_every_n_hands=table_meta.bomb_pot_every_n_hands,
        bomb_pot_amount=table_meta.bomb_pot_amount,
    )
    TABLES[table_id] = table
    return table


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


def _table_state_for_viewer(
    table_id: int,
    engine_table: Table,
    viewer_user_id: Optional[int],
) -> schemas.TableState:
    return schemas.TableState(
        id=table_id,
        hand_number=engine_table.hand_number,
        street=engine_table.street,
        pot=engine_table.pot,
        board=[str(c) for c in engine_table.board],
        current_bet=engine_table.current_bet,
        next_to_act_seat=engine_table.next_to_act_seat,
        action_deadline=engine_table.action_deadline,
        dealer_button_seat=engine_table.dealer_button_seat,
        small_blind_seat=engine_table.small_blind_seat,
        big_blind_seat=engine_table.big_blind_seat,
        small_blind=engine_table.small_blind,
        big_blind=engine_table.big_blind,
        players=[
            schemas.PlayerState(
                id=p.id,
                name=p.name,
                seat=p.seat,
                stack=p.stack,
                committed=p.committed,
                in_hand=p.in_hand,
                has_folded=p.has_folded,
                all_in=p.all_in,
                hole_cards=(
                    [str(c) for c in p.hole_cards]
                    if (p.user_id is None or p.user_id == viewer_user_id)
                    else ["XX"] * len(p.hole_cards)
                ),
                user_id=p.user_id,
                profile_picture_url=p.profile_picture_url,
            )
            for p in engine_table.players
        ],
    )


def _table_state(
    table_id: int, engine_table: Table, viewer_user_id: Optional[int] = None
) -> schemas.TableState:
    return _table_state_for_viewer(table_id, engine_table, viewer_user_id=viewer_user_id)


def _apply_timeouts(table_id: int, db: Session | None = None) -> Table:
    engine_table = _get_engine_table(table_id, db)
    while True:
        result = engine_table.enforce_action_timeout()
        if result is None:
            break
    return engine_table


def _auto_progress_hand(engine_table: Table) -> bool:
    """
    Advance the hand automatically when possible.

    Returns True if the hand reached showdown (finished), else False.
    """
    remaining = [p for p in engine_table.active_players() if not p.has_folded]
    if len(remaining) == 1 and engine_table.street != "showdown":
        winner = remaining[0]
        winner.stack += engine_table.pot
        engine_table.pot = 0
        engine_table.street = "showdown"
        engine_table.next_to_act_seat = None
        engine_table.action_deadline = None
        return True

    if engine_table.street == "showdown":
        return True

    if engine_table.next_to_act_seat is None and engine_table.betting_round_complete():
        try:
            if remaining and all(p.all_in for p in remaining):
                if engine_table.street == "preflop":
                    engine_table.deal_flop()
                    engine_table.deal_turn()
                    engine_table.deal_river()
                elif engine_table.street == "flop":
                    engine_table.deal_turn()
                    engine_table.deal_river()
                elif engine_table.street == "turn":
                    engine_table.deal_river()
                engine_table.showdown()
                return True

            if engine_table.street == "preflop":
                engine_table.deal_flop()
            elif engine_table.street == "flop":
                engine_table.deal_turn()
            elif engine_table.street == "turn":
                engine_table.deal_river()
            elif engine_table.street == "river":
                engine_table.showdown()
                return True
        except ValueError:
            pass

    return engine_table.street == "showdown"


def _auto_start_hand_if_ready(engine_table: Table) -> bool:
    """Start a fresh hand when at least two players are seated."""
    if len(engine_table.players) < 2:
        return False

    if engine_table.street not in {"prehand", "showdown"}:
        return False

    engine_table.start_new_hand()
    return True


async def broadcast_table_state(table_id: int):
    # Broadcasts assume the engine table already exists; callers should
    # ensure it is initialized before invoking this function.
    engine_table = _get_engine_table(table_id)
    _apply_timeouts(table_id)
    _auto_progress_hand(engine_table)
    _auto_start_hand_if_ready(engine_table)
    connections = TABLE_CONNECTIONS.get(table_id, {})
    player_user_ids = {p.user_id for p in engine_table.players if p.user_id is not None}

    sent: Set[WebSocket] = set()

    # First notify anyone subscribed to the specific table
    for ws, viewer_user_id in list(connections.items()):
        try:
            state = _table_state_for_viewer(table_id, engine_table, viewer_user_id)
            await ws.send_json(state.dict())
            sent.add(ws)
        except Exception:
            connections.pop(ws, None)

    # Also notify any user-level websocket connections for seated players
    for user_id in player_user_ids:
        sockets = USER_CONNECTIONS.get(user_id, set())
        for ws in list(sockets):
            if ws in sent:
                continue
            try:
                state = _table_state_for_viewer(
                    table_id, engine_table, viewer_user_id=user_id
                )
                await ws.send_json(state.dict())
                sent.add(ws)
            except Exception:
                sockets.discard(ws)
        if not sockets:
            USER_CONNECTIONS.pop(user_id, None)


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


@router.post("/", response_model=schemas.CreateTableResponse)
def create_table(
    req: schemas.CreateTableRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == req.club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    is_owner = club.owner_id == current_user.id
    if not is_owner:
        raise HTTPException(
            status_code=403,
            detail="Only club owners can create tables",
        )

    table_meta = models.PokerTable(
        club_id=req.club_id,
        created_by_user_id=current_user.id,
        max_seats=req.max_seats,
        small_blind=req.small_blind,
        big_blind=req.big_blind,
        bomb_pot_every_n_hands=req.bomb_pot_every_n_hands,
        bomb_pot_amount=req.bomb_pot_amount,
        status="active",
    )
    db.add(table_meta)
    db.commit()
    db.refresh(table_meta)

    engine_table = Table(
        max_seats=req.max_seats,
        small_blind=req.small_blind,
        big_blind=req.big_blind,
        bomb_pot_every_n_hands=req.bomb_pot_every_n_hands,
        bomb_pot_amount=req.bomb_pot_amount,
    )
    TABLES[table_meta.id] = engine_table

    return schemas.CreateTableResponse(table_id=table_meta.id)


@router.post("/{table_id}/players", response_model=schemas.AddPlayerResponse)
async def add_player(
    table_id: int,
    req: schemas.AddPlayerRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id, db)

    player = engine_table.add_player(
        name=req.name,
        starting_stack=req.starting_stack,
        user_id=None,
        seat=req.seat,
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
    engine_table = _get_engine_table(table_id, db)

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
            name=current_user.username,
            starting_stack=req.buy_in,
            user_id=current_user.id,
            profile_picture_url=current_user.profile_picture_url,
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


@router.post("/{table_id}/change_seat", response_model=schemas.AddPlayerResponse)
async def change_seat(
    table_id: int,
    req: schemas.ChangeSeatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id, db)

    try:
        player = engine_table.move_player_to_seat(current_user.id, req.seat)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await broadcast_table_state(table_id)
    return schemas.AddPlayerResponse(table_id=table_id, player_id=player.id, seat=player.seat)


@router.post("/{table_id}/leave", response_model=schemas.LeaveTableResponse)
async def leave_table(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id, db)

    if not engine_table.players:
        raise HTTPException(status_code=400, detail="Table is already empty")

    if not any(p.user_id == current_user.id for p in engine_table.players):
        raise HTTPException(status_code=404, detail="You are not seated at this table")

    if engine_table.street not in ("prehand", "showdown") and engine_table.next_to_act_seat is not None:
        raise HTTPException(status_code=400, detail="You can only leave between hands")

    try:
        removed = engine_table.remove_player_by_user(current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.balance += removed.stack
    db.add(user)
    db.commit()
    db.refresh(user)

    await broadcast_table_state(table_id)

    return schemas.LeaveTableResponse(
        table_id=table_id,
        seat=removed.seat,
        returned_amount=removed.stack,
    )


@router.post("/{table_id}/start_hand", response_model=schemas.TableState)
async def start_hand(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)
    engine_table.start_new_hand()
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table, viewer_user_id=current_user.id)


@router.post("/{table_id}/action", response_model=schemas.TableState)
async def player_action(
    table_id: int,
    req: schemas.ActionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)
    try:
        engine_table.player_action(req.player_id, req.action, req.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    hand_finished = _auto_progress_hand(engine_table)
    if hand_finished:
        _auto_start_hand_if_ready(engine_table)
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table, viewer_user_id=current_user.id)


@router.post("/{table_id}/deal_flop", response_model=schemas.TableState)
async def deal_flop(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)
    engine_table.deal_flop()
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table, viewer_user_id=current_user.id)


@router.post("/{table_id}/deal_turn", response_model=schemas.TableState)
async def deal_turn(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)
    engine_table.deal_turn()
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table, viewer_user_id=current_user.id)


@router.post("/{table_id}/deal_river", response_model=schemas.TableState)
async def deal_river(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)
    engine_table.deal_river()
    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table, viewer_user_id=current_user.id)


@router.get("/{table_id}", response_model=schemas.TableState)
async def get_table_state(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)
    return _table_state(table_id, engine_table, viewer_user_id=current_user.id)


@router.get("/{table_id}/meta", response_model=schemas.PokerTableMeta)
def get_table(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Return metadata for a table within a club the user can access."""

    return _ensure_user_in_table_club(table_id, db, current_user)


@router.post("/{table_id}/showdown")
async def showdown(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id, db)
    winners, best_rank, results = engine_table.showdown()
    started = _auto_start_hand_if_ready(engine_table)
    await broadcast_table_state(table_id)

    return {
        "winners": [
            {
                "player_id": p.id,
                "name": p.name,
                "seat": p.seat,
                "stack": p.stack,
                "hand_rank": results[p.id],
            }
            for p in winners
        ],
        "best_rank": best_rank,
        "table": _table_state(table_id, engine_table, viewer_user_id=current_user.id),
        "auto_started": started,
    }
