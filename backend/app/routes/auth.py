from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlmodel import Session, select

from app.auth import (
    auth_is_bootstrapped,
    build_password_secret,
    create_session_for_user,
    normalize_username,
    require_admin_user,
    require_authenticated_user,
    revoke_token,
    verify_password,
)
from app.database import get_session
from app.models.team_photo import PhotographerTournamentAccess
from app.models.tournament import Tournament
from app.models.user_account import UserAccount

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthUserResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BootstrapStatusResponse(BaseModel):
    bootstrap_needed: bool


class BootstrapAdminRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None

    @field_validator("username")
    @classmethod
    def _valid_username(cls, v: str) -> str:
        n = normalize_username(v)
        if not n:
            raise ValueError("username is required")
        if len(n) < 3:
            raise ValueError("username must be at least 3 characters")
        return n

    @field_validator("password")
    @classmethod
    def _valid_password(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: Literal["admin", "director", "photographer"] = "director"
    is_active: bool = True

    @field_validator("username")
    @classmethod
    def _valid_username(cls, v: str) -> str:
        n = normalize_username(v)
        if not n:
            raise ValueError("username is required")
        if len(n) < 3:
            raise ValueError("username must be at least 3 characters")
        return n

    @field_validator("password")
    @classmethod
    def _valid_password(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[Literal["admin", "director", "photographer"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _valid_password(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


@router.get("/bootstrap-needed", response_model=BootstrapStatusResponse)
def bootstrap_needed(session: Session = Depends(get_session)):
    return BootstrapStatusResponse(bootstrap_needed=not auth_is_bootstrapped(session))


@router.post("/bootstrap-admin", response_model=AuthUserResponse, status_code=201)
def bootstrap_admin(payload: BootstrapAdminRequest, session: Session = Depends(get_session)):
    if auth_is_bootstrapped(session):
        raise HTTPException(status_code=400, detail="Auth is already bootstrapped")

    salt, pw_hash = build_password_secret(payload.password)
    user = UserAccount(
        username=payload.username,
        display_name=payload.display_name,
        role="admin",
        password_salt=salt,
        password_hash=pw_hash,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, session: Session = Depends(get_session)):
    username = normalize_username(payload.username)
    user = session.exec(select(UserAccount).where(UserAccount.username == username)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(payload.password, user.password_salt, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_session_for_user(session, user, request=request)
    session.refresh(user)
    return LoginResponse(access_token=token, user=AuthUserResponse.model_validate(user))


@router.post("/logout")
def logout(
    request: Request,
    _user: Optional[UserAccount] = Depends(require_authenticated_user),
    session: Session = Depends(get_session),
):
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            revoke_token(session, token)
    return {"success": True}


@router.get("/me", response_model=AuthUserResponse)
def me(user: Optional[UserAccount] = Depends(require_authenticated_user)):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return AuthUserResponse.model_validate(user)


@router.get("/users", response_model=List[AuthUserResponse])
def list_users(
    _admin: UserAccount = Depends(require_admin_user),
    session: Session = Depends(get_session),
):
    users = session.exec(select(UserAccount).order_by(UserAccount.username.asc())).all()
    return [AuthUserResponse.model_validate(u) for u in users]


@router.post("/users", response_model=AuthUserResponse, status_code=201)
def create_user(
    payload: CreateUserRequest,
    _admin: UserAccount = Depends(require_admin_user),
    session: Session = Depends(get_session),
):
    existing = session.exec(select(UserAccount).where(UserAccount.username == payload.username)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    salt, pw_hash = build_password_secret(payload.password)
    user = UserAccount(
        username=payload.username,
        display_name=payload.display_name,
        role=payload.role,
        password_salt=salt,
        password_hash=pw_hash,
        is_active=payload.is_active,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return AuthUserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=AuthUserResponse)
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    admin: UserAccount = Depends(require_admin_user),
    session: Session = Depends(get_session),
):
    user = session.get(UserAccount, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.is_active is False and user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        salt, pw_hash = build_password_secret(payload.password)
        user.password_salt = salt
        user.password_hash = pw_hash
    user.updated_at = datetime.utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    return AuthUserResponse.model_validate(user)


class PhotographyAccessUpdate(BaseModel):
    tournament_ids: List[int]


class PhotographyAccessResponse(BaseModel):
    user_id: int
    tournament_ids: List[int]


def _replace_photography_access(session: Session, user_id: int, tournament_ids: List[int]) -> List[int]:
    unique_ids = sorted({int(tournament_id) for tournament_id in tournament_ids})
    if unique_ids:
        found = session.exec(select(Tournament).where(Tournament.id.in_(unique_ids))).all()  # type: ignore[attr-defined]
        found_ids = {row.id for row in found}
        missing = [tournament_id for tournament_id in unique_ids if tournament_id not in found_ids]
        if missing:
            raise HTTPException(status_code=400, detail="One or more tournaments were not found")
    existing = session.exec(
        select(PhotographerTournamentAccess).where(PhotographerTournamentAccess.user_id == user_id)
    ).all()
    for row in existing:
        session.delete(row)
    session.flush()
    for tournament_id in unique_ids:
        session.add(PhotographerTournamentAccess(user_id=user_id, tournament_id=tournament_id))
    session.commit()
    return unique_ids


@router.get("/photography-access", response_model=List[PhotographyAccessResponse])
def list_photography_access(
    _admin: UserAccount = Depends(require_admin_user),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(PhotographerTournamentAccess).order_by(PhotographerTournamentAccess.user_id)).all()
    grouped: dict[int, List[int]] = {}
    for row in rows:
        grouped.setdefault(row.user_id, []).append(row.tournament_id)
    return [
        PhotographyAccessResponse(user_id=user_id, tournament_ids=sorted(ids))
        for user_id, ids in grouped.items()
    ]


@router.get("/users/{user_id}/photography-tournaments", response_model=PhotographyAccessResponse)
def get_user_photography_tournaments(
    user_id: int,
    _admin: UserAccount = Depends(require_admin_user),
    session: Session = Depends(get_session),
):
    user = session.get(UserAccount, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    rows = session.exec(
        select(PhotographerTournamentAccess).where(PhotographerTournamentAccess.user_id == user_id)
    ).all()
    return PhotographyAccessResponse(user_id=user_id, tournament_ids=sorted(row.tournament_id for row in rows))


@router.put("/users/{user_id}/photography-tournaments", response_model=PhotographyAccessResponse)
def set_user_photography_tournaments(
    user_id: int,
    payload: PhotographyAccessUpdate,
    _admin: UserAccount = Depends(require_admin_user),
    session: Session = Depends(get_session),
):
    user = session.get(UserAccount, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    tournament_ids = _replace_photography_access(session, user_id, payload.tournament_ids)
    return PhotographyAccessResponse(user_id=user_id, tournament_ids=tournament_ids)
