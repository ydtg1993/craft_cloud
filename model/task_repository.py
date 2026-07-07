"""Task history repository — 持久化已完成/失败的任务记录。"""

from sqlalchemy import select, desc, delete
from model.orm_models import TaskHistory
from core.database import db_write_guard


class TaskRepository:
    """任务历史记录的 CRUD 操作。"""

    def __init__(self, db):
        self.db = db

    def _session(self):
        return self.db._get_session()

    def _read(self, func):
        """Execute a read-only function and rollback to release DB locks."""
        session = self._session()
        try:
            return func(session)
        finally:
            session.rollback()

    def add_task(self, task_id: str, task_type: str, description: str = "",
                 file_size: str = "", status: str = "completed",
                 error_msg: str = "", _bg: bool = False):
        """新增一条任务记录（完成或失败时调用）。"""
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            record = TaskHistory(
                task_id=task_id,
                task_type=task_type,
                description=description,
                file_size=file_size,
                status=status,
                error_msg=error_msg,
            )
            session.add(record)
            session.commit()

    def update_task(self, task_id: str, status: str, error_msg: str = "",
                    _bg: bool = False):
        """更新已有任务记录的状态（按 task_id 字段查找）。"""
        with db_write_guard(timeout=None if _bg else 5.0):
            session = self._session()
            record = session.execute(
                select(TaskHistory).where(TaskHistory.task_id == task_id)
            ).scalar_one_or_none()
            if record is not None:
                record.status = status
                if error_msg:
                    record.error_msg = error_msg
                session.commit()

    def get_recent_tasks(self, limit: int = 50):
        """获取最近的任务历史记录，按创建时间倒序。"""
        def _query(session):
            rows = session.execute(
                select(TaskHistory)
                .order_by(desc(TaskHistory.created_time))
                .limit(limit)
            ).scalars().all()
            return [r.to_dict() for r in rows]
        return self._read(_query)

    def clear_history(self):
        """清空所有任务历史记录。"""
        with db_write_guard(timeout=5.0):
            session = self._session()
            session.execute(delete(TaskHistory))
            session.commit()
