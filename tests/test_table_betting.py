from app.poker.table import Table


def test_raiser_does_not_get_extra_action_after_calls():
    table = Table()
    player_sb = table.add_player("Alice")  # seat 0, small blind
    player_bb = table.add_player("Bob")    # seat 1, big blind
    player_raiser = table.add_player("Charlie")  # seat 2, acts first preflop

    table.start_new_hand()

    table.player_action(player_raiser.id, "raise_to", 6)
    table.player_action(player_sb.id, "call")
    table.player_action(player_bb.id, "call")

    assert table.next_to_act_seat is None


def test_minimum_raise_required():
    table = Table()
    table.add_player("Alice")  # seat 0, small blind
    table.add_player("Bob")    # seat 1, big blind
    player = table.add_player("Charlie")  # seat 2, acts first preflop

    table.start_new_hand()

    # Minimum raise from the big blind (2) is to 4; anything less should fail.
    try:
        table.player_action(player.id, "raise_to", 3)
    except ValueError as exc:  # Expected
        assert "minimum raise" in str(exc)
    else:
        raise AssertionError("Short raise should be rejected")


def test_short_all_in_does_not_reopen_betting():
    table = Table()
    short_stack = table.add_player("Alice", starting_stack=8)  # seat 0, small blind
    player_bb = table.add_player("Bob")                        # seat 1, big blind
    player_raiser = table.add_player("Charlie")                # seat 2, acts first preflop

    table.start_new_hand()

    # Full raise from 2 -> 6 establishes a 4 chip raise size
    table.player_action(player_raiser.id, "raise_to", 6)
    previous_closer = table.action_closing_seat

    # Short all-in from the small blind to 8 (only a +2 raise) should not reopen action
    table.player_action(short_stack.id, "raise_to", 8)

    assert table.action_closing_seat == previous_closer
    assert table.last_raise_amount == 4


def test_no_bet_street_requires_full_orbit():
    table = Table()
    player_sb = table.add_player("Alice")  # seat 0, small blind & button
    player_bb = table.add_player("Bob")    # seat 1, big blind

    table.start_new_hand()

    # Preflop: small blind completes the call, big blind checks.
    table.player_action(player_sb.id, "call")
    table.player_action(player_bb.id, "check")

    table.deal_flop()

    # On the flop with no bet, the big blind acts first and a check should
    # still pass action to the small blind instead of ending the street.
    assert table.next_to_act_seat == player_bb.seat
    table.player_action(player_bb.id, "check")

    assert table.next_to_act_seat == player_sb.seat
