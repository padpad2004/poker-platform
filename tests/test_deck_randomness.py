import unittest

from app.poker.cards import Card, Rank, Suit
from app.poker.deck import Deck


class DeckRandomnessTestCase(unittest.TestCase):
    def test_shuffle_creates_non_ordered_deck(self):
        deck = Deck()
        ordered_deck = [Card(rank, suit) for suit in Suit for rank in Rank]

        self.assertNotEqual(
            deck._cards,  # pylint: disable=protected-access
            ordered_deck,
            "Deck should not remain in ordered state after shuffling.",
        )

    def test_reset_resets_and_randomizes(self):
        deck = Deck()
        first_run = [deck.deal_one() for _ in range(5)]

        deck.reset()
        second_run = [deck.deal_one() for _ in range(5)]

        self.assertNotEqual(
            first_run,
            second_run,
            "Reset should reshuffle the deck to produce a different order of cards.",
        )
        self.assertEqual(deck.remaining(), 52 - 5)


if __name__ == "__main__":
    unittest.main()
