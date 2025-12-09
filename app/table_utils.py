from __future__ import annotations


def format_blind_value(value: float) -> str:
    """Format blind values without trailing zeros when possible."""

    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def default_table_name(small_blind: float, big_blind: float, game_type: str) -> str:
    """Return the default table name using blinds and game type."""

    normalized_game_type = (game_type or "NLH").upper()
    return f"{format_blind_value(small_blind)}/{format_blind_value(big_blind)} {normalized_game_type}"


def resolve_table_name(
    table_name: str | None, small_blind: float, big_blind: float, game_type: str | None
) -> str:
    """Choose a user-provided table name or fall back to the default."""

    cleaned_name = (table_name or "").strip()
    if cleaned_name:
        return cleaned_name

    return default_table_name(small_blind, big_blind, game_type or "NLH")
