"""FastAPI dependencies: authentication, ownership scoping."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, User
from ..security import decode_access_token


def current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不可用")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
DbSession = Annotated[Session, Depends(get_db)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def account_for_user(db: Session, user: User, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None or (not user.is_admin and account.owner_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账号不存在")
    return account


def visible_account_ids(db: Session, user: User) -> list[int]:
    from sqlalchemy import select

    stmt = select(Account.id)
    if not user.is_admin:
        stmt = stmt.where(Account.owner_id == user.id)
    return list(db.scalars(stmt))
