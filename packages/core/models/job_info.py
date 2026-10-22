from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobInfo:
    job_id: str
    skill_id: str
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result_messages: list[str] = field(default_factory=list)
