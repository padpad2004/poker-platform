import time
from dataclasses import dataclass, field
from typing import List, Optional

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
    stack: int = 100            # starting chips
    committed: int = 0          # chips committed this betting round
    all_in: bool = False
    user_id: Optional[int] = None  # real user id if seated, else None (bot / generic)

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
        small_blind: int = 1,
        big_blind: int = 2,
        bomb_pot_every_n_hands: Optional[int] = None,
        bomb_pot_amount: Optional[int] = None,
    ):
        self.max_seats = max_seats
        self.players: List[Player] = []
        self.deck: Deck = Deck()
        self.board: List[Card] = []
        self.hand_number: int = 0

        # Betting-related
        self.pot: int = 0
        self.current_bet: int = 0      # current highest committed amount this street
        self.street: str = "prehand"   # prehand, preflop, flop, turn, river, showdown
        self.dealer_seat: int = 0
        self.small_blind: int = small_blind
        self.big_blind: int = big_blind
        self.next_to_act_seat: Optional[int] = None
        self.action_deadline: Optional[float] = None  # epoch seconds for timer

        # Bomb pot configuration
        self.bomb_pot_every_n_hands: Optional[int] = bomb_pot_every_n_hands
        self.bomb_pot_amount: Optional[int] = bomb_pot_amount

    # ---------- Player & seating ----------

    def add_player(
        self,
        player_id: int,
        name: str,
        starting_stack: int = 100,
        user_id: Optional[int] = None,
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
            id=player_id,
            name=name,
            seat=chosen_seat,
            stack=starting_stack,
            user_id=user_id,
        )
        self.players.append(new_player)
        return new_player

    def get_player_by_id(self, player_id: int) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise ValueError(f"No player with id {player_id}")

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

        # Rotate dealer
        if self.hand_number > 1:
            self.dealer_seat = (self.dealer_seat + 1) % len(self.players)

        # Reset players
        for p in self.players:
            p.hole_cards = []
            p.in_hand = True
            p.has_folded = False
            p.committed = 0
            p.all_in = False

        self._apply_bomb_pot_if_needed()

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

        self._post_blind(sb_player, self.small_blind)
        self._post_blind(bb_player, self.big_blind)

        self.current_bet = max(self.current_bet, self.big_blind)

        self.next_to_act_seat = self._next_seat(bb_player.seat)
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

        # Bomb pot contributions set the initial current bet
        self.current_bet = max(self.current_bet, self.bomb_pot_amount)

    def _post_blind(self, player: Player, amount: int) -> None:
        post = min(player.stack, amount)
        player.stack -= post
        player.committed += post
        self.pot += post
        if player.stack == 0:
            player.all_in = True

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

    def _set_action_deadline(self) -> None:
        if self.next_to_act_seat is None:
            self.action_deadline = None
            return
        self.action_deadline = time.time() + 30

    def enforce_action_timeout(self) -> Optional[str]:
        """Auto-act if the current player has exceeded the 30 second window."""
        if self.next_to_act_seat is None or self.action_deadline is None:
            return None

        if time.time() < self.action_deadline:
            return None

        player = self._player_by_seat(self.next_to_act_seat)
        action = "call" if player.committed == self.current_bet else "fold"
        try:
            self._apply_action(player.id, action, auto=True)
        except Exception:
            # If the auto action fails, give up and clear the deadline to avoid loops
            self.next_to_act_seat = None
            self.action_deadline = None
            return None

        return action

    # ---------- Betting logic ----------

    def player_action(self, player_id: int, action: str, amount: int | None = None) -> None:
        """
        Very simple betting for the current street:
        - 'fold'
        - 'call'
        - 'raise_to'  (amount = total committed target, e.g. raise_to=10)
        """
        self._apply_action(player_id, action, amount)

    def _apply_action(
        self, player_id: int, action: str, amount: int | None = None, auto: bool = False
    ) -> None:
        """Shared action handler for user and auto-timeout actions."""
        if self.next_to_act_seat is None:
            raise ValueError("No player is set to act")

        acting_player = self.get_player_by_id(player_id)
        if acting_player.seat != self.next_to_act_seat:
            raise ValueError(f"Not {acting_player.name}'s turn to act")

        if acting_player.has_folded or not acting_player.in_hand or acting_player.all_in:
            raise ValueError("Player cannot act (folded or all-in)")

        if action == "fold":
            acting_player.has_folded = True
            acting_player.in_hand = False

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

        else:
            raise ValueError(f"Unknown action: {action}")

        self._advance_turn()

    def _advance_turn(self) -> None:
        if all(p.has_folded or p.all_in for p in self.players):
            self.next_to_act_seat = None
            self.action_deadline = None
            return

        start_seat = self.next_to_act_seat
        seat = start_seat
        while True:
            seat = self._next_seat(seat)
            p = self._player_by_seat(seat)
            if p.in_hand and not p.has_folded and not p.all_in:
                if self._betting_round_complete():
                    self.next_to_act_seat = None
                else:
                    self.next_to_act_seat = seat
                self._set_action_deadline()
                return

            if seat == start_seat:
                self.next_to_act_seat = None
                self.action_deadline = None
                return

    def _betting_round_complete(self) -> bool:
        """Internal check: all active players have matched current_bet or are all-in/folded."""
        for p in self.players:
            if not p.in_hand or p.has_folded or p.all_in:
                continue
            if p.committed != self.current_bet:
                return False
        return True

    def betting_round_complete(self) -> bool:
        """Public helper used by API to decide if we can auto-advance the street."""
        return self._betting_round_complete()

    # ---------- Streets ----------

    def reset_committed_for_new_street(self) -> None:
        self.current_bet = 0
        for p in self.players:
            p.committed = 0
        self.next_to_act_seat = self._next_seat(self.dealer_seat)
        self._set_action_deadline()

    def deal_flop(self) -> None:
        if self.street != "preflop":
            raise ValueError("Flop can only be dealt after preflop betting")
        self.board.extend([self.deck.deal_one() for _ in range(3)])
        self.street = "flop"
        self.reset_committed_for_new_street()

    def deal_turn(self) -> None:
        if self.street != "flop":
            raise ValueError("Turn can only be dealt after flop")
        self.board.append(self.deck.deal_one())
        self.street = "turn"
        self.reset_committed_for_new_street()

    def deal_river(self) -> None:
        if self.street != "turn":
            raise ValueError("River can only be dealt after turn")
        self.board.append(self.deck.deal_one())
        self.street = "river"
        self.reset_committed_for_new_street()

    # ---------- Showdown ----------

    def determine_winner(self):
        """Return winner(s) and their best-hand rank tuple."""
        from .hand_evaluator import best_hand

        best_rank = None
        winners: List[Player] = []
        results = {}

        active_players = [p for p in self.players if p.in_hand and not p.has_folded]

        for p in active_players:
            seven = p.hole_cards + self.board
            rank = best_hand(seven)
            results[p.id] = rank

            if best_rank is None or rank > best_rank:
                best_rank = rank
                winners = [p]
            elif rank == best_rank:
                winners.append(p)

        return winners, best_rank, results

    def showdown(self):
        """Evaluate the board, pay out the pot to winner(s), and return result details."""
        winners, best_rank, results = self.determine_winner()

        if winners and self.pot > 0:
            share = self.pot // len(winners)
            remainder = self.pot % len(winners)

            for idx, w in enumerate(winners):
                w.stack += share
                if idx < remainder:
                    w.stack += 1

            self.pot = 0

        self.street = "showdown"
        return winners, best_rank, results

    def __repr__(self) -> str:
        players = ", ".join(repr(p) for p in self.players)
        board_cards = " ".join(str(c) for c in self.board) if self.board else "--"
        return (
            f"Table(hand={self.hand_number}, street={self.street}, pot={self.pot}, "
            f"board=[{board_cards}], players=[{players}])"
        )
