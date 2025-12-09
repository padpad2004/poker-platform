from itertools import combinations
from typing import List, Tuple

from .cards import Card, Rank


# Hand ranking categories from worst → best.
# We will return tuples, and Python will compare them lexicographically.
# Higher first element = better hand now.
HAND_RANKS = {
    "high_card": 1,
    "one_pair": 2,
    "two_pair": 3,
    "three_of_a_kind": 4,
    "straight": 5,
    "flush": 6,
    "full_house": 7,
    "four_of_a_kind": 8,
    "straight_flush": 9,
    "royal_flush": 10,
}


def card_values(cards: List[Card]) -> List[int]:
    # Sorted high → low (Ace=14 highest)
    return sorted([c.rank for c in cards], reverse=True)


def is_flush(cards: List[Card]) -> Tuple[bool, List[int]]:
    suits = [c.suit for c in cards]
    if len(set(suits)) == 1:
        return True, card_values(cards)
    return False, []


def is_straight(cards: List[Card]) -> Tuple[bool, int]:
    ranks = sorted({c.rank for c in cards})
    # Special case: 5-high straight (A2345)
    if ranks == [Rank.TWO, Rank.THREE, Rank.FOUR, Rank.FIVE, Rank.ACE]:
        return True, Rank.FIVE
    if len(ranks) != 5:
        return False, 0
    if max(ranks) - min(ranks) == 4:
        return True, max(ranks)
    return False, 0


def evaluate_5(cards: List[Card]) -> Tuple:
    """
    Evaluate exactly 5 cards; return a ranking tuple.
    Higher tuple = better hand.
    """

    values = card_values(cards)
    ranks = [c.rank for c in cards]

    # Count occurrences of each rank
    counts = {r: ranks.count(r) for r in set(ranks)}
    count_values = sorted(counts.values(), reverse=True)

    # Check flush
    flush, flush_values = is_flush(cards)

    # Check straight
    straight, high_straight = is_straight(cards)

    # Royal / Straight flush
    if flush and straight:
        if high_straight == Rank.ACE:
            return (HAND_RANKS["royal_flush"],)
        return (HAND_RANKS["straight_flush"], high_straight)

    # Four of a kind
    if count_values[0] == 4:
        four = max(counts, key=lambda r: ranks.count(r))
        kicker = max(r for r in ranks if r != four)
        return (HAND_RANKS["four_of_a_kind"], four, kicker)

    # Full house
    if count_values == [3, 2]:
        three = max(counts, key=lambda r: ranks.count(r) if ranks.count(r) == 3 else 0)
        pair = max(counts, key=lambda r: ranks.count(r) if ranks.count(r) == 2 else 0)
        return (HAND_RANKS["full_house"], three, pair)

    # Flush
    if flush:
        return (HAND_RANKS["flush"], *flush_values)

    # Straight
    if straight:
        return (HAND_RANKS["straight"], high_straight)

    # Three of a kind
    if count_values[0] == 3:
        trips = max(counts, key=lambda r: ranks.count(r) if ranks.count(r) == 3 else 0)
        kickers = sorted((r for r in ranks if r != trips), reverse=True)
        return (HAND_RANKS["three_of_a_kind"], trips, *kickers)

    # Two pair
    if count_values == [2, 2, 1]:
        pairs = sorted((r for r in counts if counts[r] == 2), reverse=True)
        kicker = max(r for r in ranks if r not in pairs)
        return (HAND_RANKS["two_pair"], *pairs, kicker)

    # One pair
    if count_values == [2, 1, 1, 1]:
        pair = max(counts, key=lambda r: ranks.count(r) if ranks.count(r) == 2 else 0)
        kickers = sorted((r for r in ranks if r != pair), reverse=True)
        return (HAND_RANKS["one_pair"], pair, *kickers)

    # High card
    return (HAND_RANKS["high_card"], *values)


def best_hand(seven_cards: List[Card]) -> Tuple[Tuple, List[Card]]:
    """Legacy helper for NLH hands (choose any 5 of 7)."""
    return best_hand_for_game([], seven_cards, game_type="nlh")


def best_hand_for_game(
    hole_cards: List[Card], board: List[Card], game_type: str = "nlh"
) -> Tuple[Tuple, List[Card]]:
    """Return best hand for Hold'em or PLO."""

    best_rank: Tuple | None = None
    best_combo: List[Card] | None = None

    if game_type == "plo":
        for hole_combo in combinations(hole_cards, 2):
            for board_combo in combinations(board, 3):
                five_cards = list(hole_combo + board_combo)
                rank = evaluate_5(five_cards)
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    best_combo = five_cards
    else:
        for combo in combinations(hole_cards + board, 5):
            five_cards = list(combo)
            rank = evaluate_5(five_cards)
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_combo = five_cards

    if best_rank is None or best_combo is None:
        raise ValueError("Unable to determine best hand from the provided cards")

    return best_rank, best_combo
