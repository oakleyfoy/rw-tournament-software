"""Named tournament phone lists for manual SMS sends."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class SmsPhoneList(SQLModel, table=True):
    """Tournament-scoped named list of uploaded phone recipients."""

    __tablename__ = "sms_phone_list"

    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SmsPhoneListMember(SQLModel, table=True):
    """Recipient row inside a named phone list."""

    __tablename__ = "sms_phone_list_member"

    id: Optional[int] = Field(default=None, primary_key=True)
    phone_list_id: int = Field(foreign_key="sms_phone_list.id", index=True)
    raw_name: Optional[str] = None
    phone_number: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
