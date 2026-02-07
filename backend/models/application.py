from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Application(BaseModel):
    id: str = ""
    job_id: str
    job_url: str
    company: str
    title: str
    status: str = "started"  # started | filled | submitted | error
    fields_filled: int = 0
    fields_total: int = 0
    cover_letter_path: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
