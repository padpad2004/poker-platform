from sqlalchemy.orm import Session

from app import models
from app.tables_api import TABLES, TABLE_CONNECTIONS


def delete_club_with_relations(club: models.Club, db: Session) -> None:
    """Remove a club and all related records.

    Cleans up active table references, club members, and resets the
    current_club_id field for users that were linked to the club before
    deleting the club itself.
    """

    tables = db.query(models.PokerTable).filter(models.PokerTable.club_id == club.id).all()
    for table in tables:
        TABLES.pop(table.id, None)
        TABLE_CONNECTIONS.pop(table.id, None)
        db.delete(table)

    db.query(models.ClubMember).filter(models.ClubMember.club_id == club.id).delete(
        synchronize_session=False
    )

    db.query(models.User).filter(models.User.current_club_id == club.id).update(
        {"current_club_id": None}, synchronize_session=False
    )

    db.delete(club)
