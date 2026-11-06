"""Create the first admin account. Idempotent: an existing user is never changed."""

from __future__ import annotations

import logging

from sqlalchemy import select

from .db import SessionLocal
from .models import User
from .security import hash_password
from .settings import get_settings

logger = logging.getLogger(__name__)


def seed_admin() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == settings.admin_username))
        if existing:
            return
        if settings.is_production and settings.admin_password in {"admin12345", ""}:
            logger.warning(
                "ADMIN_PASSWORD is still the example value; set a strong password in .env "
                "before exposing the service"
            )
        db.add(
            User(
                username=settings.admin_username,
                display_name="管理员",
                password_hash=hash_password(settings.admin_password),
                role="admin",
            )
        )
        db.commit()
        logger.info("created initial admin user: %s", settings.admin_username)
