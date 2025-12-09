from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    balance = Column(Float, nullable=False, default=0)
    current_club_id = Column(Integer, ForeignKey("clubs.id"), nullable=True)
    profile_picture_url = Column(String, nullable=True)
    university = Column(String, nullable=True)

    # ONLY through club_members
    memberships = relationship("ClubMember", back_populates="user")
    hand_histories = relationship("HandHistory", back_populates="user")


class Club(Base):
    __tablename__ = "clubs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    crest_url = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, default="inactive")
    created_at = Column(DateTime, default=datetime.utcnow)

    # ONLY through club_members
    members = relationship("ClubMember", back_populates="club")


class ClubMember(Base):
    __tablename__ = "club_members"

    id = Column(Integer, primary_key=True, index=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, default="member")
    status = Column(String, default="approved")  # approved | pending
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="memberships")
    club = relationship("Club", back_populates="members")


class HandHistory(Base):
    __tablename__ = "hand_histories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    table_name = Column(String, nullable=False)
    result = Column(String, nullable=False)
    net_change = Column(Integer, default=0)
    summary = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="hand_histories")


class TableSession(Base):
    __tablename__ = "table_sessions"

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer, ForeignKey("poker_tables.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    buy_in = Column(Integer, nullable=False)
    cash_out = Column(Integer, nullable=True)
    profit_loss = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


class TableReport(Base):
    __tablename__ = "table_reports"

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer, ForeignKey("poker_tables.id"), nullable=False)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)


class TableReportEntry(Base):
    __tablename__ = "table_report_entries"

    id = Column(Integer, primary_key=True, index=True)
    table_report_id = Column(Integer, ForeignKey("table_reports.id"), nullable=False)
    table_id = Column(Integer, ForeignKey("poker_tables.id"), nullable=False)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    buy_in = Column(Integer, nullable=False)
    cash_out = Column(Integer, nullable=True)
    profit_loss = Column(Integer, nullable=False)


class PokerTable(Base):
    __tablename__ = "poker_tables"

    id = Column(Integer, primary_key=True, index=True)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    table_name = Column(String, nullable=False, default="Table")
    max_seats = Column(Integer, default=9)
    small_blind = Column(Float, default=1.0)
    big_blind = Column(Float, default=2.0)
    game_type = Column(String, default="nlh")  # nlh | plo
    bomb_pot_every_n_hands = Column(Integer, nullable=True)
    bomb_pot_amount = Column(Float, nullable=True)
    status = Column(String, default="active")  # active | closed
    created_at = Column(DateTime, default=datetime.utcnow)

    # These two relationships are SAFE — they do NOT create ambiguous FK conflicts
    club = relationship("Club", foreign_keys=[club_id])
    creator = relationship("User", foreign_keys=[created_by_user_id])


class TableStack(Base):
    __tablename__ = "table_stacks"

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer, ForeignKey("poker_tables.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    seat = Column(Integer, nullable=False)
    stack = Column(Integer, nullable=False)
    name = Column(String, nullable=True)
    profile_picture_url = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
