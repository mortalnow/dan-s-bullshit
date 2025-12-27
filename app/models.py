from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

QuoteStatus = Literal["PENDING", "APPROVED", "REJECTED"]


class QuoteBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    source: Optional[str] = None
    submitted_by: str = Field(..., min_length=1, max_length=100)


class QuoteCreate(QuoteBase):
    pass


class QuoteAdminUpdate(BaseModel):
    status: QuoteStatus
    verified_by: Optional[str] = None


class QuoteResponse(BaseModel):
    id: str
    content: str
    content_hash: Optional[str] = None
    status: QuoteStatus
    source: Optional[str] = None
    created_at: Optional[datetime] = None
    submitted_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    likes: int = 0


class QuoteListResponse(BaseModel):
    items: list[QuoteResponse]
    next_cursor: Optional[str] = None


class SubmitResult(BaseModel):
    id: str
    status: QuoteStatus


class UserStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"


class User(BaseModel):
    email: str
    password: str
    admin_name: str
    status: UserStatus = UserStatus.PENDING
    is_admin: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserLogin(BaseModel):
    email: str
    password: str

