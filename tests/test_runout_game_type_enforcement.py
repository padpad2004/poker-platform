import pytest

from app.poker.table import Table


def test_request_runouts_rejected_for_non_nlh_table():
    table = Table(game_type="PLO")

    with pytest.raises(ValueError, match="Run-outs are only supported for NLH"):
        table.request_runouts(player_id=1, runouts=2)


def test_respond_runouts_rejected_for_non_nlh_table():
    table = Table(game_type="plo")
    table.runout_requested_by = 2
    table.runout_requested_count = 2

    with pytest.raises(ValueError, match="Run-outs are only supported for NLH"):
        table.respond_runouts(player_id=1, accept=True)


def test_resolve_runouts_rejected_for_non_nlh_table():
    table = Table(game_type="plo")

    with pytest.raises(ValueError, match="Run-outs are only supported for NLH"):
        table.resolve_all_in_showdown()
