from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobSubmitRequest(BaseModel):
    model_name: str = Field(..., description="MatterGen pretrained model name")
    batch_size: int = Field(2, ge=1)
    num_batches: int = Field(1, ge=1)
    properties_to_condition_on: Optional[Dict[str, Any]] = None
    diffusion_guidance_factor: Optional[float] = None


class JobSubmitResponse(BaseModel):
    job_id: str
    status: str
    results_dir: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    results_dir: str
    created_at: str
    meta: Dict[str, Any]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatHistoryResponse(BaseModel):
    job_id: str
    messages: List[ChatMessage]


class ChatMessageRequest(BaseModel):
    message: str
    model: Optional[str] = None


class AnalysisRequest(BaseModel):
    model: Optional[str] = None


class Postw90SubmitRequest(BaseModel):
    module: str
    job_name: str = ""
    nproc: Optional[int] = None
    params: Optional[Dict[str, Any]] = None
