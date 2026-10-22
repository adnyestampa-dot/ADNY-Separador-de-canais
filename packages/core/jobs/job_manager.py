from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from packages.core.models.job_info import JobInfo, JobStatus

logger = logging.getLogger(__name__)


class JobSignals(QObject):
    started = Signal(str)
    progress = Signal(str, int, str)
    finished = Signal(str, object)
    failed = Signal(str, str)


@dataclass(slots=True)
class JobSpec:
    job_id: str
    skill_id: str
    fn: Callable[[], Any]


class Worker(QRunnable):
    def __init__(self, spec: JobSpec, signals: JobSignals) -> None:
        super().__init__()
        self.spec = spec
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            self.signals.started.emit(self.spec.job_id)
        except RuntimeError:
            return
        logger.info("Job iniciado: %s skill=%s", self.spec.job_id, self.spec.skill_id)
        try:
            result = self.spec.fn()
            self.signals.finished.emit(self.spec.job_id, result)
            logger.info("Job concluído: %s", self.spec.job_id)
        except Exception as exc:
            logger.exception("Job falhou: %s", self.spec.job_id)
            try:
                self.signals.failed.emit(self.spec.job_id, str(exc))
            except RuntimeError:
                pass


class JobManager(QObject):
    """Manages background job execution via QThreadPool."""

    job_started = Signal(object)
    job_progress = Signal(object)
    job_finished = Signal(object, object)
    job_failed = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._signals = JobSignals()
        self._signals.started.connect(self._on_started)
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._jobs: dict[str, JobInfo] = {}
        self._thread_pool = QThreadPool.globalInstance()

    def submit(self, skill_id: str, fn: Callable[[], Any]) -> JobInfo:
        job_id = str(uuid.uuid4())
        info = JobInfo(
            job_id=job_id,
            skill_id=skill_id,
            status=JobStatus.PENDING,
            started_at=datetime.now(),
        )
        self._jobs[job_id] = info
        spec = JobSpec(job_id=job_id, skill_id=skill_id, fn=fn)
        worker = Worker(spec, self._signals)
        self._thread_pool.start(worker)
        return info

    def get_job(self, job_id: str) -> JobInfo | None:
        return self._jobs.get(job_id)

    def has_running_skill(self, skill_id: str) -> bool:
        return any(
            info.skill_id == skill_id
            and info.status in (JobStatus.PENDING, JobStatus.RUNNING)
            for info in self._jobs.values()
        )

    def _on_started(self, job_id: str) -> None:
        info = self._jobs.get(job_id)
        if info:
            info.status = JobStatus.RUNNING
            self.job_started.emit(info)

    def _on_progress(self, job_id: str, percent: int, message: str) -> None:
        info = self._jobs.get(job_id)
        if info:
            info.progress = percent
            info.message = message
            self.job_progress.emit(info)

    def _on_finished(self, job_id: str, result: Any) -> None:
        info = self._jobs.get(job_id)
        if info:
            info.status = JobStatus.COMPLETED
            info.progress = 100
            info.finished_at = datetime.now()
            if hasattr(result, "messages"):
                info.result_messages = list(result.messages)
        self.job_finished.emit(info, result)

    def _on_failed(self, job_id: str, error: str) -> None:
        info = self._jobs.get(job_id)
        if info:
            info.status = JobStatus.FAILED
            info.error = error
            info.finished_at = datetime.now()
        self.job_failed.emit(info, error)
