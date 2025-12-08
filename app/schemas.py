from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime
from typing import Optional, List, Literal


# ---------- User ----------

class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserMe(UserBase):
    id: int
    balance: int
    current_club_id: Optional[int] = None
    profile_picture_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class HandHistoryRead(BaseModel):
    id: int
    table_name: str
    result: str
    net_change: int
    summary: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProfileResponse(UserMe):
    current_club_name: Optional[str] = None
    hand_history: List[HandHistoryRead]


class AdminUser(UserRead):
    balance: int
    current_club_id: Optional[int] = None
    profile_picture_url: Optional[str] = None


# ---------- Club ----------

class ClubBase(BaseModel):
    name: str
    crest_url: Optional[str] = None


class ClubCreate(ClubBase):
    pass


class ClubRead(ClubBase):
    id: int
    owner_id: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClubMemberRead(BaseModel):
    id: int
    club_id: int
    user_id: int
    role: str
    created_at: datetime
    user_email: EmailStr
    balance: int

    model_config = ConfigDict(from_attributes=True)


class PokerTableMeta(BaseModel):
    id: int
    club_id: int
    created_by_user_id: int
    max_seats: int
    small_blind: float
    big_blind: float
    bomb_pot_every_n_hands: Optional[int]
    bomb_pot_amount: Optional[float]
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClubDetail(ClubRead):
    members: List[ClubMemberRead]
    tables: List[PokerTableMeta]


class ClubTableCreate(BaseModel):
    max_seats: int = 6
    small_blind: float = 1
    big_blind: float = 2
    bomb_pot_every_n_hands: Optional[int] = None
    bomb_pot_amount: Optional[float] = None


# ---------- Poker Engine ----------

class PlayerState(BaseModel):
    id: int
    name: str
    seat: int
    stack: float
    committed: float
    in_hand: bool
    has_folded: bool
    all_in: bool
    hole_cards: List[str]
    user_id: Optional[int]
    profile_picture_url: Optional[str] = None

class TableState(BaseModel):
    id: int
    hand_number: int
    street: str
    pot: float
    board: List[str]
    current_bet: float
    next_to_act_seat: Optional[int]
    action_deadline: Optional[float]
    dealer_button_seat: Optional[int]
    small_blind_seat: Optional[int]
    big_blind_seat: Optional[int]
    small_blind: float
    big_blind: float
    players: List[PlayerState]

    model_config = ConfigDict(from_attributes=True)


class CreateTableRequest(BaseModel):
    club_id: int
    max_seats: int = 6
    small_blind: float = 1
    big_blind: float = 2
    bomb_pot_every_n_hands: Optional[int] = None
    bomb_pot_amount: Optional[float] = None


class CreateTableResponse(BaseModel):
    table_id: int


class AddPlayerRequest(BaseModel):
    name: str
    starting_stack: int = 100
    seat: Optional[int] = None


class SitMeRequest(BaseModel):
    seat: Optional[int] = None
    buy_in: int


class ChangeSeatRequest(BaseModel):
    seat: int


class AddPlayerResponse(BaseModel):
    table_id: int
    player_id: int
    seat: int


class ActionRequest(BaseModel):
    player_id: int
    action: Literal["fold", "call", "raise_to"]
    amount: Optional[int] = None


class BalanceUpdateRequest(BaseModel):
    amount_delta: int


class BalanceUpdateResponse(BaseModel):
    user_id: int
    new_balance: int


class AdminOverview(BaseModel):
    users: List[AdminUser]
    clubs: List[ClubRead]

    model_config = ConfigDict(from_attributes=True)
