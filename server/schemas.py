from typing import Literal, Optional

from pydantic import BaseModel, Field

ClientKind = Literal["pc", "vm", "container", "other"]


class Disk(BaseModel):
    mount: str
    total_bytes: int = 0
    used_bytes: int = 0
    percent: float = 0


class SnapshotPayload(BaseModel):
    ts: float
    hostname: str
    kind: ClientKind = "other"
    host_ip: str = ""
    cpu_percent: float = 0
    mem_percent: float = 0
    uptime_seconds: int = 0
    disks: list[Disk] = Field(default_factory=list)
    extra: Optional[dict] = None


class Ingest(BaseModel):
    token: str
    payload: SnapshotPayload