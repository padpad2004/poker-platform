from random import SystemRandom
from typing import List

from .cards import Card, Rank, Suit


class Deck:
    def __init__(self):
        self._cards: List[Card] = []
        self.reset()

    def reset(self) -> None:
        """Create a new ordered 52-card deck."""
        self._cards = [Card(rank, suit) for suit in Suit for rank in Rank]
        self.shuffle()

    def shuffle(self) -> None:
        """Shuffle deck using a cryptographically secure RNG."""
        SystemRandom().shuffle(self._cards)

    def deal_one(self) -> Card:
        if not self._cards:
            raise ValueError("Deck is empty")
        return self._cards.pop()

    def remaining(self) -> int:
        return len(self._cards)

    def __len__(self) -> int:
        return len(self._cards)

    def __repr__(self) -> str:
        return f"Deck({self._cards})"
