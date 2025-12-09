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
