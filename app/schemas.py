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

    model_config = ConfigDict(from_attributes=True)


# ---------- Club ----------

class ClubBase(BaseModel):
    name: str


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

    model_config = ConfigDict(from_attributes=True)


class PokerTableMeta(BaseModel):
    id: int
    club_id: int
    created_by_user_id: int
    max_seats: int
    small_blind: int
    big_blind: int
    bomb_pot_every_n_hands: Optional[int]
    bomb_pot_amount: Optional[int]
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClubDetail(ClubRead):
    members: List[ClubMemberRead]
    tables: List[PokerTableMeta]


# ---------- Poker Engine ----------

class PlayerState(BaseModel):
    id: int
    name: str
    seat: int
    stack: int
    committed: int
    in_hand: bool
    has_folded: bool
    all_in: bool
    hole_cards: List[str]
    user_id: Optional[int]

class TableState(BaseModel):
    id: int
    hand_number: int
    street: str
    pot: int
    board: List[str]
    current_bet: int
    next_to_act_seat: Optional[int]
    action_deadline: Optional[float]
    dealer_button_seat: Optional[int]
    small_blind_seat: Optional[int]
    big_blind_seat: Optional[int]
    small_blind: int
    big_blind: int
    players: List[PlayerState]

    model_config = ConfigDict(from_attributes=True)


class CreateTableRequest(BaseModel):
    club_id: int
    max_seats: int = 6
    small_blind: int = 1
    big_blind: int = 2
    bomb_pot_every_n_hands: Optional[int] = None
    bomb_pot_amount: Optional[int] = None


class CreateTableResponse(BaseModel):
    table_id: int


class AddPlayerRequest(BaseModel):
    name: str
    starting_stack: int = 100
    seat: Optional[int] = None


class SitMeRequest(BaseModel):
    seat: Optional[int] = None
    buy_in: int


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
