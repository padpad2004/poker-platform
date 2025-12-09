import pytest
from fastapi import HTTPException

from app.tables_api import validate_nlh_table_rules


def test_validate_nlh_table_rules_accepts_standard_structure():
    # Standard 9-max NLH table with 1/2 blinds should be accepted
    assert validate_nlh_table_rules(9, 1, 2) is None


@pytest.mark.parametrize(
    "max_seats, small_blind, big_blind",
    [
        (1, 1, 2),  # not enough seats
        (10, 1, 2),  # too many seats
        (6, 0, 0),  # non-positive blinds
        (6, 1, 3),  # incorrect blind ratio
    ],
)
def test_validate_nlh_table_rules_rejects_invalid_configs(max_seats, small_blind, big_blind):
    with pytest.raises(HTTPException):
        validate_nlh_table_rules(max_seats, small_blind, big_blind)

