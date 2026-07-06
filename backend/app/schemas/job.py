from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class FileResponse(BaseModel):
    id: str
    proposal_type: str
    original_filename: str
    file_size_bytes: int
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class FileCounts(BaseModel):
    qualitative: int = 0
    quantitative: int = 0
    presentation: int = 0


class JobResponse(BaseModel):
    id: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    files: List[FileResponse] = []
    file_counts: FileCounts = FileCounts()
    superlative_count: int = 0
    typo_count: int = 0
    blind_count: int = 0
    competitor_count: int = 0

    model_config = {"from_attributes": True}


class FileUploadResponse(BaseModel):
    file_id: str
    original_filename: str
    proposal_type: str


class StartJobRequest(BaseModel):
    blind_eval: bool = False
    blind_keywords: List[dict] = []
    blind_logos: List[dict] = []
    competitor_eval: bool = False
    competitor_keywords: List[dict] = []
