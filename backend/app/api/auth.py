"""Admin creating/managing local console users."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..models import User, utcnow
from ..security import hash_password, verify_password
from .deps import AdminUser, CurrentUser, DbSession
from .schemas import ChangePassword, LoginRequest, TokenOut, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(payload: LoginRequest, db: DbSession) -> TokenOut:
    from ..security import create_access_token

    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(403, "账号已被停用")
    user.last_login_at = utcnow()
    db.add(user)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/change-password")
def change_password(payload: ChangePassword, user: CurrentUser, db: DbSession) -> dict[str, str]:
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(400, "原密码不正确")
    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    db.commit()
    return {"message": "密码已更新"}


@router.get("/users", response_model=list[UserOut])
def list_users(_: AdminUser, db: DbSession) -> list[UserOut]:
    rows = db.scalars(select(User).order_by(User.id)).all()
    return [UserOut.model_validate(row) for row in rows]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, _: AdminUser, db: DbSession) -> UserOut:
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(409, "用户名已存在")
    user = User(
        username=payload.username.strip(),
        display_name=payload.display_name.strip() or payload.username.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: dict, _: AdminUser, db: DbSession) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if "is_active" in payload:
        user.is_active = bool(payload["is_active"])
    if payload.get("password"):
        user.password_hash = hash_password(str(payload["password"]))
    if payload.get("display_name") is not None:
        user.display_name = str(payload["display_name"])[:64]
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
