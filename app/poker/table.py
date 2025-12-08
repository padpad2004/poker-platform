import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .deck import Deck
from .cards import Card


@dataclass
class Player:
    id: int
    name: str
    seat: int
    hole_cards: List[Card] = field(default_factory=list)
    in_hand: bool = True        # still in the current hand
    has_folded: bool = False
    stack: float = 100          # starting chips
    committed: float = 0        # chips committed this betting round
    all_in: bool = False
    user_id: Optional[int] = None  # real user id if seated, else None (bot / generic)
    profile_picture_url: Optional[str] = None  # chosen avatar for the seated player

    def __repr__(self) -> str:
        cards = " ".join(str(c) for c in self.hole_cards) if self.hole_cards else "--"
        return (
            f"Player(id={self.id}, seat={self.seat}, stack={self.stack}, "
            f"committed={self.committed}, user_id={self.user_id}, cards=[{cards}])"
        )


class Table:
    """
    Simple 2+ player Texas Hold'em table model:
    - Dealing logic
    - Winner evaluation
    - VERY basic betting (blinds, fold/call/raise_to)
    """

    def __init__(
        self,
        max_seats: int = 6,
        small_blind: float = 1,
        big_blind: float = 2,
        bomb_pot_every_n_hands: Optional[int] = None,
        bomb_pot_amount: Optional[float] = None,
        action_time_limit: float = 30,
    ):
        self.max_seats = max_seats
        self.players: List[Player] = []
        self.deck: Deck = Deck()
        self.board: List[Card] = []
        self.hand_number: int = 0

        # Betting-related
        self.pot: float = 0
        self.current_bet: float = 0      # current highest committed amount this street
        self.street: str = "prehand"   # prehand, preflop, flop, turn, river, showdown
        self.dealer_seat: int = 0
        self.dealer_button_seat: Optional[int] = None
        self.small_blind_seat: Optional[int] = None
        self.big_blind_seat: Optional[int] = None
        self.small_blind: float = small_blind
        self.big_blind: float = big_blind
        self.next_to_act_seat: Optional[int] = None
        self.action_deadline: Optional[float] = None  # epoch seconds for timer
        self.action_time_limit = action_time_limit
        # Tracks which seat will close the betting round once action returns
        # and all players have matched the current bet.
        self.action_closing_seat: Optional[int] = None

        # Bomb pot configuration
        self.bomb_pot_every_n_hands: Optional[int] = bomb_pot_every_n_hands
        self.bomb_pot_amount: Optional[float] = bomb_pot_amount

        # Internal id counter to ensure player ids remain unique even after seats are vacated
        self._next_player_id: int = 1

        # Simple in-memory history of recent hands (action-only, non-persisted)
        self.recent_hands: List[Dict[str, Any]] = []
        self.current_hand_log: Optional[Dict[str, Any]] = None

        # Track players who requested to leave during a hand so they can
        # automatically stand up once the hand finishes.
        self.pending_leave_user_ids: Set[int] = set()

    # ---------- Player & seating ----------

    def add_player(
        self,
        name: str,
        starting_stack: float = 100,
        user_id: Optional[int] = None,
        profile_picture_url: Optional[str] = None,
        seat: Optional[int] = None,
    ) -> Player:
        """
        Add a player to the table.
        user_id = real user id (for human seat), or None for generic/bot seat.
        """
        if len(self.players) >= self.max_seats:
            raise ValueError("Table is full")

        taken_seats = {p.seat for p in self.players}

        if seat is not None:
            if seat < 0 or seat >= self.max_seats:
                raise ValueError("Invalid seat number")
            if seat in taken_seats:
                raise ValueError("Seat already occupied")
            chosen_seat = seat
        else:
            chosen_seat = None
            for possible in range(self.max_seats):
                if possible not in taken_seats:
                    chosen_seat = possible
                    break

            if chosen_seat is None:
                raise ValueError("No available seats")

        new_player = Player(
            id=self._next_player_id,
            name=name,
            seat=chosen_seat,
            stack=starting_stack,
            user_id=user_id,
            profile_picture_url=profile_picture_url,
        )
        self._next_player_id += 1
        self.players.append(new_player)
        return new_player

    def get_player_by_id(self, player_id: int) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise ValueError(f"No player with id {player_id}")

    def move_player_to_seat(self, user_id: int, seat: int) -> Player:
        if seat < 0 or seat >= self.max_seats:
            raise ValueError("Invalid seat number")

        player = None
        for p in self.players:
            if p.user_id == user_id:
                player = p
                break

        if player is None:
            raise ValueError("Player not seated")

        for other in self.players:
            if other.user_id != user_id and other.seat == seat:
                raise ValueError("Seat already occupied")

        player.seat = seat
        return player

    def active_players(self) -> List[Player]:
        """Players still in the hand (haven't folded) and with chips."""
        return [
            p
            for p in self.players
            if p.in_hand and not p.has_folded and p.stack >= 0
        ]

    # ---------- Hand + dealing ----------

    def start_new_hand(self) -> None:
        """Reset deck, board, player state, post blinds, deal cards."""
        if len(self.players) < 2:
            raise ValueError("Need at least 2 players to start a hand")

        self.hand_number += 1
        self.deck.reset()
        self.board = []
        self.pot = 0
        self.current_bet = 0
        self.street = "preflop"
        self.small_blind_seat = None
        self.big_blind_seat = None
        self.dealer_button_seat = None
        self.action_closing_seat = None

        # Remember each player's stack before blinds or bomb pots are taken so
        # net changes can be calculated when the hand finishes.
        self.hand_start_stacks = {p.id: p.stack for p in self.players}

        # Choose a valid dealer button seat and rotate when possible.
        # If the previous dealer seat is now empty (e.g., player moved seats),
        # fall back to the lowest occupied seat to avoid errors when
        # advancing the button.
        occupied_seats = sorted(p.seat for p in self.players)
        if self.hand_number == 1 or self.dealer_seat not in occupied_seats:
            self.dealer_seat = occupied_seats[0]
        else:
            self.dealer_seat = self._next_seat(self.dealer_seat)

        self.dealer_button_seat = self.dealer_seat

        # Reset players
        for p in self.players:
            p.hole_cards = []
            p.in_hand = True
            p.has_folded = False
            p.committed = 0
            p.all_in = False

        # Start a fresh hand log
        self.current_hand_log = {
            "hand_number": self.hand_number,
            "actions": [],
            "board": [],
            "result": None,
            "pot": 0,
        }

        self._apply_bomb_pot_if_needed()

        # Note: blinds are logged inside post_blinds

        # Deal 2 cards to each player
        for _ in range(2):
            for p in self.players:
                p.hole_cards.append(self.deck.deal_one())

        # Post blinds
        self.post_blinds()

    def post_blinds(self) -> None:
        """Post small and big blinds and set next_to_act."""
        active_players = sorted(self.players, key=lambda p: p.seat)
        if len(active_players) < 2:
            raise ValueError("Need at least 2 players for blinds")

        sb_player = self._player_by_seat(self.dealer_seat)
        bb_player = self._player_by_seat(self._next_seat(self.dealer_seat))

        sb_amount = self._post_blind(sb_player, self.small_blind)
        self._log_action("preflop", sb_player, "small_blind", sb_amount)
        bb_amount = self._post_blind(bb_player, self.big_blind)
        self._log_action("preflop", bb_player, "big_blind", bb_amount)

        self.small_blind_seat = sb_player.seat
        self.big_blind_seat = bb_player.seat

        self.current_bet = max(self.current_bet, self.big_blind)

        self.next_to_act_seat = self._next_player_to_act(bb_player.seat)
        # The big blind should have the option to check/raise if action comes
        # back around without a raise.
        self.action_closing_seat = bb_player.seat
        self._set_action_deadline()

    def _apply_bomb_pot_if_needed(self) -> None:
        """If configured, take bomb pot contributions from each player."""
        if not self.bomb_pot_every_n_hands or not self.bomb_pot_amount:
            return

        if self.hand_number % self.bomb_pot_every_n_hands != 0:
            return

        for p in self.players:
            contribution = min(p.stack, self.bomb_pot_amount)
            p.stack -= contribution
            p.committed += contribution
            self.pot += contribution
            if p.stack == 0:
                p.all_in = True
            self._log_action("preflop", p, "bomb_pot", contribution)

        # Bomb pot contributions set the initial current bet
        self.current_bet = max(self.current_bet, self.bomb_pot_amount)

    def _post_blind(self, player: Player, amount: float) -> float:
        post = min(player.stack, amount)
        player.stack -= post
        player.committed += post
        self.pot += post
        if player.stack == 0:
            player.all_in = True
        return post

    def _player_by_seat(self, seat: int) -> Player:
        for p in self.players:
            if p.seat == seat:
                return p
        raise ValueError(f"No player in seat {seat}")

    def _next_seat(self, seat: int) -> int:
        occupied = sorted(p.seat for p in self.players)
        if seat not in occupied:
            raise ValueError("Seat not occupied")
        idx = occupied.index(seat)
        return occupied[(idx + 1) % len(occupied)]

    def _previous_seat(self, seat: int) -> int:
        occupied = sorted(p.seat for p in self.players)
        if seat not in occupied:
            raise ValueError("Seat not occupied")
        idx = occupied.index(seat)
        return occupied[(idx - 1) % len(occupied)]

    def _log_action(
        self,
        street: str,
        player: Optional[Player],
        action: str,
        amount: Optional[float] = None,
        auto: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.current_hand_log is None:
            return

        event: Dict[str, Any] = {
            "type": "action",
            "street": street,
            "player_name": player.name if player else None,
            "seat": player.seat if player else None,
            "action": action,
            "amount": amount,
            "committed": player.committed if player else None,
            "stack": player.stack if player else None,
            "auto": auto,
        }

        if extra:
            event.update(extra)

        self.current_hand_log["actions"].append(event)

    def _log_street_transition(self, street: str) -> None:
        if self.current_hand_log is None:
            return
        self.current_hand_log["actions"].append(
            {
                "type": "street",
                "street": street,
                "board": [str(c) for c in self.board],
            }
        )

    def _finalize_hand(
        self,
        winners: List[Player],
        payouts: Dict[int, float],
        pot_amount: float,
        reason: str,
    ) -> None:
        """Push the current hand log into the rolling history buffer."""

        if self.current_hand_log is None:
            return

        result_payload = {
            "reason": reason,
            "pot": pot_amount,
            "winners": [
                {
                    "player_name": w.name,
                    "seat": w.seat,
                    "amount": payouts.get(w.id, 0),
                }
                for w in winners
            ],
            "board": [str(c) for c in self.board],
        }

        self.current_hand_log["result"] = result_payload
        self.current_hand_log["board"] = [str(c) for c in self.board]
        self.current_hand_log["pot"] = pot_amount

        self.recent_hands.append(self.current_hand_log)
        # Keep only the last 50 hands similar to ClubGG history
        self.recent_hands = self.recent_hands[-50:]
        self.current_hand_log = None

    def _next_player_to_act(self, start_from_seat: int) -> Optional[int]:
        """Return the next eligible seat to act, starting after the given seat."""
        if not self.players:
            return None

        seat = start_from_seat
        while True:
            seat = self._next_seat(seat)
            player = self._player_by_seat(seat)

            if player.in_hand and not player.has_folded and not player.all_in:
                return seat

            if seat == start_from_seat:
                return None

    def _previous_active_seat(self, start_from_seat: Optional[int]) -> Optional[int]:
        """Return the previous eligible seat before the given one."""
        if start_from_seat is None or not self.players:
            return None

        seat = start_from_seat
        while True:
            seat = self._previous_seat(seat)
            player = self._player_by_seat(seat)

            if player.in_hand and not player.has_folded and not player.all_in:
                return seat

            if seat == start_from_seat:
                return None

    def remove_player_by_user(self, user_id: int) -> Player:
        """Remove a seated player by their user id and clear related markers."""

        for idx, p in enumerate(self.players):
            if p.user_id == user_id:
                removed = self.players.pop(idx)

                if self.dealer_seat == removed.seat:
                    self.dealer_seat = None
                if self.dealer_button_seat == removed.seat:
                    self.dealer_button_seat = None
                if self.small_blind_seat == removed.seat:
                    self.small_blind_seat = None
                if self.big_blind_seat == removed.seat:
                    self.big_blind_seat = None
                if self.next_to_act_seat == removed.seat:
                    self.next_to_act_seat = None
                if self.next_to_act_seat is None:
                    self.action_deadline = None

                return removed

        raise ValueError("No player for that user id")

    def _set_action_deadline(self) -> None:
        if self.next_to_act_seat is None:
            self.action_deadline = None
            return
        self.action_deadline = time.time() + self.action_time_limit

    def enforce_action_timeout(self) -> Optional[str]:
        """Auto-fold if the current player has exceeded the 30 second window."""
        if self.next_to_act_seat is None or self.action_deadline is None:
            return None

        if time.time() < self.action_deadline:
            return None

        try:
            player = self._player_by_seat(self.next_to_act_seat)
        except ValueError:
            # If the tracked seat was cleared due to a disconnect, stop the timer
            self.next_to_act_seat = None
            self.action_deadline = None
            return None
        action = "fold"
        try:
            self._apply_action(player.id, action, auto=True)
        except Exception:
            # If the auto action fails, give up and clear the deadline to avoid loops
            self.next_to_act_seat = None
            self.action_deadline = None
            return None

        return action

    # ---------- Betting logic ----------

    def player_action(self, player_id: int, action: str, amount: float | None = None) -> None:
        """
        Very simple betting for the current street:
        - 'fold'
        - 'call'
        - 'raise_to'  (amount = total committed target, e.g. raise_to=10)
        """
        self._apply_action(player_id, action, amount)

    def _apply_action(
        self, player_id: int, action: str, amount: float | None = None, auto: bool = False
    ) -> None:
        """Shared action handler for user and auto-timeout actions."""
        if self.next_to_act_seat is None:
            raise ValueError("No player is set to act")

        acting_player = self.get_player_by_id(player_id)
        if acting_player.seat != self.next_to_act_seat:
            raise ValueError(f"Not {acting_player.name}'s turn to act")

        if acting_player.has_folded or not acting_player.in_hand or acting_player.all_in:
            raise ValueError("Player cannot act (folded or all-in)")

        event_amount: Optional[float] = None

        if action == "fold":
            acting_player.has_folded = True
            acting_player.in_hand = False

        elif action == "check":
            if acting_player.committed != self.current_bet:
                raise ValueError("Cannot check when facing a bet")

        elif action == "call":
            to_call = self.current_bet - acting_player.committed
            if to_call <= 0:
                pass
            else:
                put_in = min(acting_player.stack, to_call)
                acting_player.stack -= put_in
                acting_player.committed += put_in
                self.pot += put_in
                if acting_player.stack == 0:
                    acting_player.all_in = True
                event_amount = put_in

        elif action == "raise_to":
            if amount is None:
                raise ValueError("amount required for raise_to")

            if amount <= self.current_bet:
                raise ValueError("raise_to amount must be greater than current bet")

            to_put_total = amount - acting_player.committed
            if to_put_total <= 0:
                raise ValueError("Player has already committed that much")

            put_in = min(acting_player.stack, to_put_total)
            acting_player.stack -= put_in
            acting_player.committed += put_in
            self.pot += put_in
            self.current_bet = max(self.current_bet, acting_player.committed)
            if acting_player.stack == 0:
                acting_player.all_in = True
            event_amount = put_in
            # A raise sets the closing action back to the raiser.
            self.action_closing_seat = acting_player.seat

        else:
            raise ValueError(f"Unknown action: {action}")

        # If the player who would close action can no longer act, advance the
        # closing seat to the previous eligible player.
        if (
            self.action_closing_seat == acting_player.seat
            and (acting_player.has_folded or acting_player.all_in)
        ):
            self.action_closing_seat = self._previous_active_seat(acting_player.seat)

        self._log_action(self.street, acting_player, action, event_amount, auto=auto)
        self._advance_turn()

    def _advance_turn(self) -> None:
        if all(p.has_folded or p.all_in for p in self.players):
            self.next_to_act_seat = None
            self.action_deadline = None
            return

        if self.action_closing_seat == self.next_to_act_seat and self._betting_round_settled():
            self.next_to_act_seat = None
            self.action_deadline = None
            return

        next_seat = self._next_player_to_act(self.next_to_act_seat)

        if next_seat is None:
            self.next_to_act_seat = None
            self.action_deadline = None
            return

        self.next_to_act_seat = next_seat
        self._set_action_deadline()

    def _betting_round_complete(self) -> bool:
        """Internal check: all active players have matched current_bet or are all-in/folded."""
        return self._betting_round_settled() and self.next_to_act_seat is None

    def betting_round_complete(self) -> bool:
        """Public helper used by API to decide if we can auto-advance the street."""
        return self._betting_round_complete()

    def _betting_round_settled(self) -> bool:
        for p in self.players:
            if not p.in_hand or p.has_folded or p.all_in:
                continue
            if p.committed != self.current_bet:
                return False
        return True

    # ---------- Streets ----------

    def reset_committed_for_new_street(self) -> None:
        self.current_bet = 0
        for p in self.players:
            p.committed = 0
        self.next_to_act_seat = self._next_player_to_act(self.dealer_seat)
        # With no existing bet, action closes after everyone has acted once.
        self.action_closing_seat = self._previous_active_seat(self.next_to_act_seat)
        self._set_action_deadline()

    def deal_flop(self) -> None:
        if self.street != "preflop":
            raise ValueError("Flop can only be dealt after preflop betting")
        self.board.extend([self.deck.deal_one() for _ in range(3)])
        self.street = "flop"
        self._log_street_transition("flop")
        self.reset_committed_for_new_street()

    def deal_turn(self) -> None:
        if self.street != "flop":
            raise ValueError("Turn can only be dealt after flop")
        self.board.append(self.deck.deal_one())
        self.street = "turn"
        self._log_street_transition("turn")
        self.reset_committed_for_new_street()

    def deal_river(self) -> None:
        if self.street != "turn":
            raise ValueError("River can only be dealt after turn")
        self.board.append(self.deck.deal_one())
        self.street = "river"
        self._log_street_transition("river")
        self.reset_committed_for_new_street()

    # ---------- Showdown ----------

    def determine_winner(self):
        """Return winner(s), their best-hand rank, and the best five cards for each player."""
        from .hand_evaluator import best_hand

        best_rank = None
        winners: List[Player] = []
        results = {}

        active_players = [p for p in self.players if p.in_hand and not p.has_folded]

        for p in active_players:
            seven = p.hole_cards + self.board
            rank, best_five_cards = best_hand(seven)
            results[p.id] = {"hand_rank": rank, "best_five": best_five_cards}

            if best_rank is None or rank > best_rank:
                best_rank = rank
                winners = [p]
            elif rank == best_rank:
                winners.append(p)

        return winners, best_rank, results

    def showdown(self):
        """Evaluate the board, pay out the pot to winner(s), and return result details."""
        winners, best_rank, results = self.determine_winner()

        payouts: dict[int, float] = {}
        pot_before = self.pot

        if winners and self.pot > 0:
            share = self.pot / len(winners)

            for w in winners:
                w.stack += share
                payouts[w.id] = share

            self.pot = 0

        self.street = "showdown"
        self._finalize_hand(winners, payouts, pot_before, reason="showdown")
        return winners, best_rank, results, payouts

    def __repr__(self) -> str:
        players = ", ".join(repr(p) for p in self.players)
        board_cards = " ".join(str(c) for c in self.board) if self.board else "--"
        return (
            f"Table(hand={self.hand_number}, street={self.street}, pot={self.pot}, "
            f"board=[{board_cards}], players=[{players}])"
        )
