import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, and_, func, select

from app.database import get_session
from app.models.auth_session import AuthSession
from app.models.user_account import UserAccount

_AUTH_SESSION_HOURS = int(os.getenv("AUTH_SESSION_HOURS", "24"))
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=64,
    )
    return digest.hex()


def build_password_secret(password: str) -> tuple[str, str]:
    salt_hex = secrets.token_hex(16)
    return salt_hex, hash_password(password, salt_hex)


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    actual = hash_password(password, salt_hex)
    return hmac.compare_digest(actual, expected_hash)


def create_access_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _extract_bearer_token(request: Request) -> Optional[str]:
    auth = (request.headers.get("authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token or None


def auth_is_bootstrapped(session: Session) -> bool:
    count = session.exec(select(func.count(UserAccount.id))).one()
    return int(count or 0) > 0


def create_session_for_user(
    session: Session,
    user: UserAccount,
    request: Optional[Request] = None,
) -> str:
    token = create_access_token()
    now = datetime.utcnow()
    auth_session = AuthSession(
        user_id=user.id,  # type: ignore[arg-type]
        token_hash=hash_token(token),
        expires_at=now + timedelta(hours=_AUTH_SESSION_HOURS),
        user_agent=(request.headers.get("user-agent") if request else None),
        ip_address=(request.client.host if request and request.client else None),
    )
    session.add(auth_session)
    user.last_login_at = now
    user.updated_at = now
    session.add(user)
    session.commit()
    return token


def get_user_from_token(session: Session, token: str) -> Optional[UserAccount]:
    now = datetime.utcnow()
    token_hash_value = hash_token(token)
    auth_session = session.exec(
        select(AuthSession).where(
            and_(
                AuthSession.token_hash == token_hash_value,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
    ).first()
    if not auth_session:
        return None

    user = session.get(UserAccount, auth_session.user_id)
    if not user or not user.is_active:
        return None
    return user


def revoke_token(session: Session, token: str) -> None:
    session_row = session.exec(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    ).first()
    if not session_row:
        return
    session_row.revoked_at = datetime.utcnow()
    session.add(session_row)
    session.commit()


def require_authenticated_user(
    request: Request,
    session: Session = Depends(get_session),
) -> Optional[UserAccount]:
    """Protect private API routes once auth has been bootstrapped.

    If zero users exist, auth is considered not bootstrapped yet and routes
    are temporarily open so the first admin can be created.
    """
    if not auth_is_bootstrapped(session):
        request.state.current_user = None
        return None

    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user = get_user_from_token(session, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    request.state.current_user = user
    return user


def require_admin_user(
    request: Request,
    user: Optional[UserAccount] = Depends(require_authenticated_user),
) -> UserAccount:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if (user.role or "").lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    request.state.current_user = user
    return user

