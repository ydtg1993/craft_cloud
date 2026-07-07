"""APScheduler-based task scheduler — replaces QTimer-based scheduling."""
from apscheduler.schedulers.qt import QtScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger


class AppScheduler:
    """Singleton APScheduler wrapper for the Qt main thread."""

    _instance = None

    def __new__(cls) -> "AppScheduler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self._scheduler = QtScheduler()
        logger.debug("APScheduler initialized")

    def start(self) -> None:
        self._scheduler.start()
        logger.info("APScheduler started")

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")

    def add_interval_job(self, func, minutes: int = 60, job_id: str | None = None) -> str:
        """Add a job that runs every N minutes."""
        trigger = IntervalTrigger(minutes=minutes)
        job = self._scheduler.add_job(func, trigger, id=job_id, replace_existing=True)
        logger.debug(f"Scheduled interval job '{job.id}': every {minutes} min")
        return job.id

    def add_cron_job(self, func, cron_expr: str, job_id: str | None = None) -> str:
        """Add a job with cron expression (e.g. '0 9 * * *' = daily at 9am).

        Uses APScheduler's built-in crontab parser which supports the full
        cron syntax: ``*/5`` (step), ``1,15`` (list), ``1-5`` (range),
        and month/day names.
        """
        trigger = CronTrigger.from_crontab(cron_expr)
        job = self._scheduler.add_job(func, trigger, id=job_id, replace_existing=True)
        logger.debug(f"Scheduled cron job '{job.id}': {cron_expr}")
        return job.id

    def remove_job(self, job_id: str) -> None:
        try:
            self._scheduler.remove_job(job_id)
            logger.debug(f"Removed job '{job_id}'")
        except Exception as e:
            logger.warning(f"移除调度任务 {job_id} 失败: {e}")

    def pause_job(self, job_id: str) -> None:
        try:
            self._scheduler.pause_job(job_id)
        except Exception as e:
            logger.warning(f"暂停调度任务 {job_id} 失败: {e}")

    def resume_job(self, job_id: str) -> None:
        try:
            self._scheduler.resume_job(job_id)
        except Exception as e:
            logger.warning(f"恢复调度任务 {job_id} 失败: {e}")
