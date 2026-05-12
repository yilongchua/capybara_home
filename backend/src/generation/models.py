from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


GenerationJobKind = Literal["image", "video"]
GenerationJobStatus = Literal["queued", "submitted", "running", "completed", "failed", "timed_out"]


class GenerationJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("genjob"))
    thread_id: str
    kind: GenerationJobKind
    status: GenerationJobStatus = "queued"
    prompt_id: str | None = None
    filename_prefix: str
    expected_virtual_path: str
    output_virtual_path: str | None = None
    source_output_path: str | None = None
    prompt_excerpt: str = ""
    output_name: str
    aspect_ratio: str = "16:9"
    error: str | None = None
    completion_seq: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    model_config = ConfigDict(extra="allow")


class GenerationSnapshot(BaseModel):
    jobs: dict[str, GenerationJob] = Field(default_factory=dict)
    next_completion_seq: int = 1
    model_config = ConfigDict(extra="allow")
