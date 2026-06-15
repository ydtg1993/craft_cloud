"""User repository — SQLAlchemy-backed CRUD for the users table."""
from sqlalchemy import select, update, func
from sqlalchemy.exc import SQLAlchemyError
from model.orm_models import User
from core.database import db_write_guard
from loguru import logger
from datetime import datetime


class UserRepository:
    """用户表仓库 — 管理 Telegram 账号信息。"""

    def __init__(self, db):
        self.db = db

    def _session(self):
        return self.db._get_session()

    def upsert_user(self, *, tg_id: int, api_id: int, api_hash: str,
                    phone: str = "", username: str = "", avatar: str = "") -> int:
        """插入或更新用户记录，返回用户数据库 ID。

        如果 tg_id 已存在，则更新 api_id/api_hash/username/phone/login_at；
        否则创建新记录。完成后将该用户设为当前激活用户。
        """
        with db_write_guard(timeout=5.0):
            session = self._session()
            try:
                # 先置零所有用户的 active，确保同一时间只有一个激活用户
                session.execute(update(User).values(active=0))

                existing = session.execute(
                    select(User).where(User.tg_id == tg_id)
                ).scalar_one_or_none()

                if existing:
                    existing.api_id = api_id
                    existing.api_hash = api_hash
                    if phone:
                        existing.phone = phone
                    if username:
                        existing.username = username
                    if avatar:
                        existing.avatar = avatar
                    existing.active = 1
                    existing.login_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    session.commit()
                    logger.info(f"[DB] 用户已更新: tg_id={tg_id}, username={username}")
                    return existing.id

                user = User(
                    tg_id=tg_id,
                    api_id=api_id,
                    api_hash=api_hash,
                    phone=phone,
                    username=username,
                    avatar=avatar,
                    active=1,
                )
                session.add(user)
                session.commit()
                logger.info(f"[DB] 新用户已创建: tg_id={tg_id}, username={username}")
                return user.id
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 用户 upsert 失败: {e}, tg_id={tg_id}")
                raise

    def set_active_user(self, tg_id: int) -> bool:
        """将指定用户设为当前激活用户（其余 active=0）。"""
        with db_write_guard(timeout=5.0):
            session = self._session()
            try:
                session.execute(update(User).values(active=0))
                session.execute(
                    update(User).where(User.tg_id == tg_id).values(active=1)
                )
                session.commit()
                logger.info(f"[DB] 已切换激活用户: tg_id={tg_id}")
                return True
            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"[DB] 切换激活用户失败: {e}, tg_id={tg_id}")
                return False

    def get_active_user(self) -> dict | None:
        """获取当前激活的用户信息，无则返回 None。"""
        session = self._session()
        try:
            row = session.execute(
                select(User).where(User.active == 1)
            ).scalar_one_or_none()
            return row.to_dict() if row else None
        finally:
            session.rollback()

    def get_active_credentials(self) -> dict | None:
        """获取当前激活用户的 Telethon 凭证，无则返回 None。

        Returns:
            dict with keys api_id, api_hash, or None if no active user.
        """
        user = self.get_active_user()
        if not user:
            return None
        return {"api_id": user["api_id"], "api_hash": user["api_hash"]}
