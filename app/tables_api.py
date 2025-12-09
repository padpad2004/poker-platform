from datetime import datetime, timedelta
import time
from typing import Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.orm import Session

from app.poker.table import Table
from . import models, schemas
from .deps import get_current_user, get_db, is_club_owner
from .database import SessionLocal

router = APIRouter(prefix="/tables", tags=["tables"])
TABLE_EXPIRY = timedelta(hours=24)
SIT_OUT_AUTO_LEAVE_SECONDS = 6 * 60

# In-memory engine tables
TABLES: Dict[int, Table] = {}

# WebSocket connections per table: table_id -> { websocket: viewer_user_id or None }
TABLE_CONNECTIONS: Dict[int, Dict[WebSocket, Optional[int]]] = {}
# WebSocket connections keyed by seated user_id so we can notify all players at a table
USER_CONNECTIONS: Dict[int, Set[WebSocket]] = {}


@router.get("/online-count")
def get_online_player_count(current_user: models.User = Depends(get_current_user)):
    """Return the number of distinct authenticated users considered online.

    We count unique websocket participants and the requesting user so the
    current session is reflected even if they have not opened a table socket
    yet.
    """

    unique_players = set(USER_CONNECTIONS.keys())
    if current_user and current_user.id is not None:
        unique_players.add(current_user.id)
    return {"online_players": len(unique_players)}


def _get_engine_table(table_id: int, db: Session | None = None) -> Table:
    table = TABLES.get(table_id)
    if table:
        return table

    if db is None:
        raise HTTPException(status_code=404, detail="Engine table not found")

    table_meta = db.query(models.PokerTable).filter(models.PokerTable.id == table_id).first()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    if table_meta.status == "closed":
        raise HTTPException(status_code=400, detail="Table is closed")

    table = Table(
        max_seats=table_meta.max_seats,
        small_blind=table_meta.small_blind,
        big_blind=table_meta.big_blind,
        bomb_pot_every_n_hands=table_meta.bomb_pot_every_n_hands,
        bomb_pot_amount=table_meta.bomb_pot_amount,
        game_type=table_meta.game_type,
    )
    TABLES[table_id] = table
    _restore_persisted_stacks(table_id, table, db)
    return table


def _restore_persisted_stacks(table_id: int, engine_table: Table, db: Session) -> None:
    """Re-seat players using the last known stacks saved for this table."""

    persisted = (
        db.query(models.TableStack)
        .filter(models.TableStack.table_id == table_id)
        .all()
    )

    for row in persisted:
        user = db.query(models.User).filter(models.User.id == row.user_id).first()
        display_name = row.name or (user.username if user else "Player")
        profile_picture = row.profile_picture_url or (user.profile_picture_url if user else None)

        try:
            engine_table.add_player(
                name=display_name,
                starting_stack=row.stack,
                user_id=row.user_id,
                profile_picture_url=profile_picture,
                seat=row.seat,
            )
        except ValueError:
            # If seats clash due to data drift, fall back to automatic seating
            engine_table.add_player(
                name=display_name,
                starting_stack=row.stack,
                user_id=row.user_id,
                profile_picture_url=profile_picture,
                seat=None,
            )

    if engine_table.players:
        engine_table._next_player_id = max(p.id for p in engine_table.players) + 1


def _ensure_user_in_table_club(
    table_id: int,
    db: Session,
    current_user: models.User,
) -> models.PokerTable:
    table_meta = db.query(models.PokerTable).filter(models.PokerTable.id == table_id).first()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    table_meta = _close_table_if_expired(table_meta, db)

    club = table_meta.club
    is_owner = is_club_owner(db, club.id, current_user.id)
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
        game_type=engine_table.game_type,
        players=[
            schemas.PlayerState(
                id=p.id,
                name=p.name,
                seat=p.seat,
                stack=p.stack,
                committed=p.committed,
                sitting_out=getattr(p, "sitting_out", False),
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
        recent_hands=engine_table.recent_hands,
    )


def _table_state(
    table_id: int, engine_table: Table, viewer_user_id: Optional[int] = None
) -> schemas.TableState:
    return _table_state_for_viewer(table_id, engine_table, viewer_user_id=viewer_user_id)


def _player_for_user(engine_table: Table, user_id: int):
    for player in engine_table.players:
        if player.user_id == user_id:
            return player
    return None


def _active_session(table_id: int, user_id: int, db: Session):
    return (
        db.query(models.TableSession)
        .filter(
            models.TableSession.table_id == table_id,
            models.TableSession.user_id == user_id,
            models.TableSession.cash_out.is_(None),
        )
        .order_by(models.TableSession.created_at.desc())
        .first()
    )


def _finalize_session(table_id: int, user_id: int, cash_out: float, db: Session):
    session = _active_session(table_id, user_id, db)
    if not session:
        return

    payout = int(round(cash_out))
    session.cash_out = payout
    session.profit_loss = payout - session.buy_in
    session.closed_at = datetime.utcnow()
    db.add(session)


def _generate_table_report(
    table_meta: models.PokerTable, db: Session, engine_table: Table | None = None
) -> Optional[models.TableReport]:
    engine_table = engine_table or TABLES.get(table_meta.id)

    if engine_table:
        for player in engine_table.players:
            if player.user_id is None:
                continue
            _finalize_session(table_meta.id, player.user_id, player.stack, db)
            user = db.query(models.User).filter(models.User.id == player.user_id).first()
            if user:
                user.balance += int(round(player.stack))
                db.add(user)

    db.commit()

    sessions = (
        db.query(models.TableSession)
        .filter(models.TableSession.table_id == table_meta.id)
        .all()
    )

    if not sessions:
        return None

    report = models.TableReport(
        table_id=table_meta.id, club_id=table_meta.club_id, generated_at=datetime.utcnow()
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    for session in sessions:
        cash_out = session.cash_out if session.cash_out is not None else 0
        profit_loss = (
            session.profit_loss if session.profit_loss is not None else cash_out - session.buy_in
        )
        entry = models.TableReportEntry(
            table_report_id=report.id,
            table_id=table_meta.id,
            club_id=table_meta.club_id,
            user_id=session.user_id,
            buy_in=session.buy_in,
            cash_out=session.cash_out,
            profit_loss=profit_loss,
        )
        db.add(entry)

    db.commit()
    return report


def _close_table(table_meta: models.PokerTable, db: Session):
    engine_table = TABLES.pop(table_meta.id, None)
    _generate_table_report(table_meta, db, engine_table)
    table_meta.status = "closed"
    db.add(table_meta)
    db.commit()


def _close_table_if_expired(table_meta: models.PokerTable, db: Session):
    if table_meta.status != "active":
        return table_meta

    if table_meta.created_at < datetime.utcnow() - TABLE_EXPIRY:
        _close_table(table_meta, db)
    return table_meta


def _auto_remove_sitting_out_players(
    table_id: int, engine_table: Table, db: Session
) -> None:
    """Remove players who have been sitting out longer than the grace period."""

    cutoff = time.time() - SIT_OUT_AUTO_LEAVE_SECONDS
    any_updates = False

    for player in list(engine_table.players):
        if not getattr(player, "sitting_out", False):
            continue

        sat_out_since = getattr(player, "sat_out_since", None)
        if sat_out_since is None or sat_out_since > cutoff:
            continue

        if player.user_id is None:
            continue

        try:
            removed = engine_table.remove_player_by_user(player.user_id)
        except ValueError:
            continue

        user = db.query(models.User).filter(models.User.id == player.user_id).first()
        if user:
            user.balance += removed.stack
            db.add(user)
            any_updates = True

        _finalize_session(table_id, player.user_id, removed.stack, db)
        any_updates = True

    if any_updates:
        db.commit()


def close_table_and_report(table_meta: models.PokerTable, db: Session):
    _close_table(table_meta, db)


def _apply_timeouts(table_id: int, db: Session | None = None) -> Table:
    engine_table = _get_engine_table(table_id, db)
    while True:
        result = engine_table.enforce_action_timeout()
        if result is None:
            break
    if db is not None:
        _auto_remove_sitting_out_players(table_id, engine_table, db)
    return engine_table


def _auto_progress_hand(engine_table: Table) -> bool:
    """
    Advance the hand automatically when possible.

    Returns True if the hand reached showdown (finished), else False.
    """
    remaining = [p for p in engine_table.active_players() if not p.has_folded]
    if len(remaining) == 1 and engine_table.street != "showdown":
        winner = remaining[0]
        pot_before = engine_table.pot
        winner.stack += engine_table.pot
        engine_table.pot = 0
        engine_table.street = "showdown"
        engine_table.next_to_act_seat = None
        engine_table.action_deadline = None
        engine_table._finalize_hand(
            [winner], {winner.id: pot_before}, pot_before, reason="all_folded"
        )
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


def _record_hand_history(
    table_meta: models.PokerTable, engine_table: Table, db: Session
) -> None:
    """Persist per-user hand history entries for the finished hand."""

    if not engine_table.hand_start_stacks:
        return

    table_name = table_meta.table_name or f"Table #{table_meta.id}"

    for p in engine_table.players:
        if p.user_id is None:
            continue

        starting_stack = engine_table.hand_start_stacks.get(p.id)
        if starting_stack is None:
            continue

        net_change = p.stack - starting_stack
        if net_change > 0:
            result = "Win"
        elif net_change < 0:
            result = "Loss"
        else:
            result = "Even"

        summary_parts = [f"Hand #{engine_table.hand_number}"]
        if engine_table.board:
            board_str = " ".join(str(c) for c in engine_table.board)
            summary_parts.append(f"Board: {board_str}")
        summary = " | ".join(summary_parts)

        hand_row = models.HandHistory(
            user_id=p.user_id,
            table_name=table_name,
            result=result,
            net_change=int(round(net_change)),
            summary=summary,
        )
        db.add(hand_row)

    db.commit()


def _process_pending_leavers(table_id: int, engine_table: Table, db: Session) -> None:
    """Stand up any players who clicked leave during a hand."""

    if not getattr(engine_table, "pending_leave_user_ids", None):
        return

    pending_ids = list(engine_table.pending_leave_user_ids)
    any_updates = False

    for user_id in pending_ids:
        try:
            removed = engine_table.remove_player_by_user(user_id)
        except ValueError:
            engine_table.pending_leave_user_ids.discard(user_id)
            continue

        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user:
            user.balance += removed.stack
            db.add(user)
            any_updates = True

        if user_id is not None:
            _finalize_session(table_id, user_id, removed.stack, db)
            any_updates = True

        engine_table.pending_leave_user_ids.discard(user_id)

    if any_updates:
        db.commit()


def _persist_table_stacks(table_id: int, engine_table: Table, db: Session) -> None:
    """Store current in-play stacks so they survive server restarts."""

    existing = {
        row.user_id: row
        for row in db.query(models.TableStack).filter(models.TableStack.table_id == table_id)
    }

    seen_user_ids = set()

    for player in engine_table.players:
        if player.user_id is None:
            continue

        seen_user_ids.add(player.user_id)
        row = existing.get(player.user_id)
        if not row:
            row = models.TableStack(table_id=table_id, user_id=player.user_id)

        row.stack = int(round(player.stack))
        row.seat = player.seat
        row.name = player.name
        row.profile_picture_url = player.profile_picture_url
        db.add(row)

    for user_id, row in existing.items():
        if user_id not in seen_user_ids:
            db.delete(row)

    db.commit()


def _auto_start_hand_if_ready(engine_table: Table) -> bool:
    """Start a fresh hand when at least two players are seated."""
    active_players = [p for p in engine_table.players if not getattr(p, "sitting_out", False)]
    if len(active_players) < 2:
        return False

    if engine_table.street not in {"prehand", "showdown"}:
        return False

    engine_table.start_new_hand()
    return True


async def broadcast_table_state(table_id: int):
    # Broadcasts assume the engine table already exists; callers should
    # ensure it is initialized before invoking this function.
    engine_table = _get_engine_table(table_id)
    player_user_ids: Set[int] = set()
    connections: Dict[WebSocket, Optional[int]] = {}
    sent: Set[WebSocket] = set()
    db = SessionLocal()
    try:
        _apply_timeouts(table_id, db)
        _auto_progress_hand(engine_table)
        _auto_start_hand_if_ready(engine_table)
        _persist_table_stacks(table_id, engine_table, db)
        connections = TABLE_CONNECTIONS.get(table_id, {})
        player_user_ids = {p.user_id for p in engine_table.players if p.user_id is not None}

        # First notify anyone subscribed to the specific table
        for ws, viewer_user_id in list(connections.items()):
            try:
                state = _table_state_for_viewer(table_id, engine_table, viewer_user_id)
                await ws.send_json(state.dict())
                sent.add(ws)
            except Exception:
                connections.pop(ws, None)
    finally:
        db.close()

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

    tables = (
        db.query(models.PokerTable)
        .join(models.Club, models.PokerTable.club_id == models.Club.id)
        .join(models.ClubMember, models.ClubMember.club_id == models.Club.id)
        .filter(
            models.ClubMember.user_id == current_user.id,
            models.ClubMember.status == "approved",
            models.PokerTable.status == "active",
        )
        .all()
    )

    tables = [table for table in tables if _close_table_if_expired(table, db).status == "active"]

    return tables


@router.post("/", response_model=schemas.CreateTableResponse)
def create_table(
    req: schemas.CreateTableRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    club = db.query(models.Club).filter(models.Club.id == req.club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if req.game_type not in {"nlh", "plo"}:
        raise HTTPException(status_code=400, detail="Invalid game type")

    is_owner = is_club_owner(db, club.id, current_user.id)
    if not is_owner:
        raise HTTPException(
            status_code=403,
            detail="Only club owners can create tables",
        )

    provided_name = (req.table_name or "").strip()
    table_meta = models.PokerTable(
        club_id=req.club_id,
        created_by_user_id=current_user.id,
        table_name=provided_name or "Table",
        max_seats=req.max_seats,
        small_blind=req.small_blind,
        big_blind=req.big_blind,
        game_type=req.game_type,
        bomb_pot_every_n_hands=req.bomb_pot_every_n_hands,
        bomb_pot_amount=req.bomb_pot_amount,
        status="active",
    )
    db.add(table_meta)
    db.commit()
    db.refresh(table_meta)

    if not provided_name:
        table_meta.table_name = f"Table #{table_meta.id}"
        db.add(table_meta)
        db.commit()
        db.refresh(table_meta)

    engine_table = Table(
        max_seats=req.max_seats,
        small_blind=req.small_blind,
        big_blind=req.big_blind,
        bomb_pot_every_n_hands=req.bomb_pot_every_n_hands,
        bomb_pot_amount=req.bomb_pot_amount,
        game_type=req.game_type,
    )
    TABLES[table_meta.id] = engine_table

    return schemas.CreateTableResponse(
        table_id=table_meta.id, table_name=table_meta.table_name
    )


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

    existing_session = _active_session(table_id, current_user.id, db)
    if existing_session:
        raise HTTPException(status_code=400, detail="You already have an open session here")

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
    session = models.TableSession(table_id=table_id, user_id=current_user.id, buy_in=req.buy_in)
    db.add(session)
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

    if engine_table.street not in {"prehand", "showdown"}:
        raise HTTPException(status_code=400, detail="You can only change seats between hands")

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

    player = _player_for_user(engine_table, current_user.id)

    if not player:
        raise HTTPException(status_code=404, detail="You are not seated at this table")

    in_active_hand = (
        engine_table.street not in ("prehand", "showdown")
        and engine_table.next_to_act_seat is not None
    )

    if in_active_hand:
        engine_table.pending_leave_user_ids.add(current_user.id)
        return schemas.LeaveTableResponse(
            table_id=table_id,
            seat=player.seat,
            returned_amount=None,
            pending=True,
        )

    try:
        removed = engine_table.remove_player_by_user(current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.balance += removed.stack
    db.add(user)
    _finalize_session(table_id, current_user.id, removed.stack, db)
    db.commit()
    db.refresh(user)

    await broadcast_table_state(table_id)

    return schemas.LeaveTableResponse(
        table_id=table_id,
        seat=removed.seat,
        returned_amount=removed.stack,
    )


@router.post("/{table_id}/sit_out", response_model=schemas.TableState)
async def sit_out(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    table_meta = _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)

    player = _player_for_user(engine_table, current_user.id)
    if not player:
        raise HTTPException(status_code=404, detail="You are not seated at this table")

    engine_table.sit_out_player(player, auto=False, reason="manual")

    hand_finished = _auto_progress_hand(engine_table)
    if hand_finished:
        _record_hand_history(table_meta, engine_table, db)
        _process_pending_leavers(table_id, engine_table, db)
        _auto_start_hand_if_ready(engine_table)

    await broadcast_table_state(table_id)
    return _table_state(table_id, engine_table, viewer_user_id=current_user.id)


@router.post("/{table_id}/return", response_model=schemas.TableState)
async def return_to_play(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)

    player = _player_for_user(engine_table, current_user.id)
    if not player:
        raise HTTPException(status_code=404, detail="You are not seated at this table")

    engine_table.return_player_to_game(player)
    _auto_start_hand_if_ready(engine_table)

    await broadcast_table_state(table_id)
    return _table_state(
        table_id,
        engine_table,
        viewer_user_id=current_user.id,
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
    table_meta = _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _apply_timeouts(table_id, db)
    try:
        engine_table.player_action(req.player_id, req.action, req.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    hand_finished = _auto_progress_hand(engine_table)
    if hand_finished:
        _record_hand_history(table_meta, engine_table, db)
        _process_pending_leavers(table_id, engine_table, db)
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
    table_meta = _ensure_user_in_table_club(table_id, db, current_user)
    engine_table = _get_engine_table(table_id, db)
    winners, best_rank, results, payouts = engine_table.showdown()

    # Wallet balances are reconciled when players leave the table. Avoid
    # crediting winners here to prevent double-counting when they cash out.
    started = _auto_start_hand_if_ready(engine_table)
    await broadcast_table_state(table_id)

    return {
        "winners": [
            {
                "player_id": p.id,
                "name": p.name,
                "seat": p.seat,
                "stack": p.stack,
                "hand_rank": results[p.id]["hand_rank"],
                "best_five": [str(c) for c in results[p.id]["best_five"]],
            }
            for p in winners
        ],
        "best_rank": best_rank,
        "table": _table_state(table_id, engine_table, viewer_user_id=current_user.id),
        "auto_started": started,
    }
