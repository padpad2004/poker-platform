from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional, List, Literal


# ---------- User ----------

class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True


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

    class Config:
        orm_mode = True


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
    players: List[PlayerState]

    class Config:
        orm_mode = True


class CreateTableRequest(BaseModel):
    club_id: int
    max_seats: int = 6
    small_blind: int = 1
    big_blind: int = 2


class CreateTableResponse(BaseModel):
    table_id: int


class AddPlayerRequest(BaseModel):
    name: str
    starting_stack: int = 100


class AddPlayerResponse(BaseModel):
    table_id: int
    player_id: int
    seat: int


class ActionRequest(BaseModel):
    player_id: int
    action: Literal["fold", "call", "raise_to"]
    amount: Optional[int] = None

from pydantic import EmailStr
from typing import Optional

class UserMe(BaseModel):
    id: int
    email: EmailStr
    balance: int
    current_club_id: Optional[int] = None

    class Config:
        orm_mode = True
