from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, WebSocket, Depends
from sqlalchemy.orm import Session

from .poker.table import Table
from . import schemas, models
from .deps import get_db, get_current_user

router = APIRouter(prefix="/tables", tags=["tables"])

# In-memory engine tables
TABLES: Dict[int, Table] = {}

# WebSocket connections per table: table_id -> { websocket: viewer_user_id or None }
TABLE_CONNECTIONS: Dict[int, Dict[WebSocket, Optional[int]]] = {}


def _get_engine_table(table_id: int) -> Table:
    table = TABLES.get(table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Engine table not found")
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
            )
            for p in engine_table.players
        ],
    )


def _table_state(table_id: int, engine_table: Table) -> schemas.TableState:
    return _table_state_for_viewer(table_id, engine_table, viewer_user_id=None)


async def broadcast_table_state(table_id: int):
    engine_table = _get_engine_table(table_id)
    connections = TABLE_CONNECTIONS.get(table_id, {})
    for ws, viewer_user_id in list(connections.items()):
        try:
            state = _table_state_for_viewer(table_id, engine_table, viewer_user_id)
            await ws.send_json(state.dict())
        except Exception:
            connections.pop(ws, None)


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

    table_meta = models.PokerTable(
        club_id=req.club_id,
        created_by_user_id=current_user.id,
        max_seats=req.max_seats,
        small_blind=req.small_blind,
        big_blind=req.big_blind,
        status="active",
    )
    db.add(table_meta)
    db.commit()
    db.refresh(table_meta)

    engine_table = Table(
        max_seats=req.max_seats,
        small_blind=req.small_blind,
        big_blind=req.big_blind,
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
    engine_table = _get_engine_table(table_id)

    player = engine_table.add_player(
        player_id=len(engine_table.players) + 1,
        name=req.name,
        starting_stack=req.starting_stack,
        user_id=None,
    )
    await broadcast_table_state(table_id)
    return schemas.AddPlayerResponse(table_id=table_id, player_id=player.id, seat=player.seat)


@router.post("/{table_id}/sit_me", response_model=schemas.AddPlayerResponse)
async def sit_me(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id)

    for p in engine_table.players:
        if p.user_id == current_user.id:
            raise HTTPException(status_code=400, detail="User already seated at this table")

    player = engine_table.add_player(
        player_id=len(engine_table.players) + 1,
        name=current_user.email,
        starting_stack=100,
        user_id=current_user.id,
    )
    await broadcast_table_state(table_id)
    return schemas.AddPlayerResponse(table_id=table_id, player_id=player.id, seat=player.seat)


@router.post("/{table_id}/start_hand", response_model=schemas.TableState)
async def start_hand(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id)
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
    engine_table = _get_engine_table(table_id)
    try:
        engine_table.player_action(req.player_id, req.action, req.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 🔹 Auto-advance street when betting round is complete
    if engine_table.next_to_act_seat is None and engine_table.betting_round_complete():
        active = [p for p in engine_table.active_players() if not p.has_folded]
        if len(active) >= 2 and not all(p.all_in for p in active):
            if engine_table.street == "preflop":
                try:
                    engine_table.deal_flop()
                except ValueError:
                    pass
            elif engine_table.street == "flop":
                try:
                    engine_table.deal_turn()
                except ValueError:
                    pass
            elif engine_table.street == "turn":
                try:
                    engine_table.deal_river()
                except ValueError:
                    pass

    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table)


@router.post("/{table_id}/deal_flop", response_model=schemas.TableState)
async def deal_flop(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id)
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
    engine_table = _get_engine_table(table_id)
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
    engine_table = _get_engine_table(table_id)
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
    engine_table = _get_engine_table(table_id)
    return _table_state(table_id, engine_table)


@router.post("/{table_id}/showdown")
async def showdown(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id)
    winners, best_rank, results = engine_table.showdown()
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
        "table": _table_state(table_id, engine_table),
    }
