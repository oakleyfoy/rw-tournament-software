from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class UserAccount(SQLModel, table=True):
    __tablename__ = "user_account"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=100)
    display_name: Optional[str] = Field(default=None, max_length=150)
    role: str = Field(default="director", max_length=20)  # admin | director
    password_salt: str = Field(max_length=128)
    password_hash: str = Field(max_length=256)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = Field(default=None)

