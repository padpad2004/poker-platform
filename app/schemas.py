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
    balance: float
    current_club_id: Optional[int] = None
    profile_picture_url: Optional[str] = None
    university: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class HandHistoryRead(BaseModel):
    id: int
    table_name: str
    result: str
    net_change: int
    summary: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TableReportEntry(BaseModel):
    table_report_id: int
    table_id: int
    club_id: int
    user_id: int
    buy_in: int
    cash_out: Optional[int]
    profit_loss: int
    generated_at: datetime
    table_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TableReportEntryWithUser(TableReportEntry):
    username: str

    model_config = ConfigDict(from_attributes=True)


class ProfileResponse(UserMe):
    current_club_name: Optional[str] = None
    hand_history: List[HandHistoryRead]


class AdminUser(UserRead):
    balance: float
    current_club_id: Optional[int] = None
    profile_picture_url: Optional[str] = None
    university: Optional[str] = None


# ---------- Club ----------

class ClubBase(BaseModel):
    name: str
    crest_url: Optional[str] = None


class ClubCreate(ClubBase):
    pass


class ClubCrestUpdate(BaseModel):
    crest_url: Optional[str] = None


class ClubRead(ClubBase):
    id: int
    owner_id: int
    owner_email: Optional[EmailStr] = None
    is_owner: bool | None = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClubMemberRead(BaseModel):
    id: int
    club_id: int
    user_id: int
    role: str
    status: str
    created_at: datetime
    user_email: EmailStr
    balance: float

    model_config = ConfigDict(from_attributes=True)


class ClubMemberRoleUpdate(BaseModel):
    role: Literal["owner", "member"]


class PokerTableMeta(BaseModel):
    id: int
    club_id: int
    created_by_user_id: int
    max_seats: int
    small_blind: float
    big_blind: float
    bomb_pot_every_n_hands: Optional[int]
    bomb_pot_amount: Optional[float]
    game_type: str
    table_name: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClubDetail(ClubRead):
    members: List[ClubMemberRead]
    tables: List[PokerTableMeta]


class ClubTableCreate(BaseModel):
    max_seats: int = 9
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
    sitting_out: bool = False
    in_hand: bool
    has_folded: bool
    all_in: bool
    hole_cards: List[str]
    user_id: Optional[int]
    profile_picture_url: Optional[str] = None


class HandAction(BaseModel):
    type: Literal["action", "street"]
    street: str
    player_name: Optional[str] = None
    seat: Optional[int] = None
    action: Optional[str] = None
    amount: Optional[float] = None
    committed: Optional[float] = None
    stack: Optional[float] = None
    auto: Optional[bool] = None
    board: Optional[List[str]] = None


class HandResult(BaseModel):
    reason: str
    pot: float
    board: List[str]
    winners: List[dict]


class TableHandHistory(BaseModel):
    hand_number: int
    board: List[str]
    pot: float
    actions: List[HandAction]
    result: Optional[HandResult] = None


class TableState(BaseModel):
    id: int
    table_name: str
    game_type: str
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
    recent_hands: List[TableHandHistory] = []

    model_config = ConfigDict(from_attributes=True)


class CreateTableRequest(BaseModel):
    club_id: int
    max_seats: int = 9
    small_blind: float = 1
    big_blind: float = 2
    bomb_pot_every_n_hands: Optional[int] = None
    bomb_pot_amount: Optional[float] = None
    table_name: Optional[str] = None
    game_type: Literal["NLH", "PLO"] = "NLH"


class CreateTableResponse(BaseModel):
    table_id: int
    table_name: str


class AddPlayerRequest(BaseModel):
    name: str
    starting_stack: int = 100
    seat: Optional[int] = None


class SitMeRequest(BaseModel):
    seat: Optional[int] = None
    buy_in: int


class ChangeSeatRequest(BaseModel):
    seat: int


class LeaveTableResponse(BaseModel):
    table_id: int
    seat: int
    returned_amount: Optional[float]
    pending: bool = False


class AddPlayerResponse(BaseModel):
    table_id: int
    player_id: int
    seat: int


class ActionRequest(BaseModel):
    player_id: int
    action: Literal["fold", "check", "call", "raise_to"]
    amount: Optional[int] = None


class BalanceUpdateRequest(BaseModel):
    amount_delta: int


class BalanceUpdateResponse(BaseModel):
    user_id: int
    new_balance: float


class AdminOverview(BaseModel):
    users: List[AdminUser]
    clubs: List[ClubRead]

    model_config = ConfigDict(from_attributes=True)
