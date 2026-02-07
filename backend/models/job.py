from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    NEW = "new"
    REVIEWING = "reviewing"
    APPLYING = "applying"
    APPLIED = "applied"
    REJECTED = "rejected"
    INTERVIEW = "interview"


class JobListing(BaseModel):
    id: str = ""
    title: str
    company: str
    location: str = ""
    url: str = ""
    description: str = ""
    source: str = ""
    date_posted: str = ""
    job_type: str = ""
    is_remote: bool = False
    status: JobStatus = JobStatus.NEW
    match_score: float = Field(0.0, ge=0.0, le=100.0)
    ats_platform: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
