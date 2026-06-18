from typing import List, Dict, Optional, Any

from pydantic import BaseModel


class ProjectCreateRequest(BaseModel):
    name: str
    title: str = ""
    genre: str = ""
    total_chapters: int = 0
    description: str = ""
    outline_layers: Optional[Dict[str, bool]] = None  # {"L1": true, "L2": true}
    extra_requirements: str = ""
    role_presets: Optional[Dict[str, Dict]] = None  # {"manager": {...}, "worker": {...}, ...}
    word_count_min: int = 3000
    word_count_max: int = 5000
    max_rounds_writing: int = 10
    max_rounds_outline: int = 8


class OutlineLayersRequest(BaseModel):
    layers: Dict[str, bool]


class OutlineNodeEditRequest(BaseModel):
    label: Optional[str] = None
    summary: Optional[str] = None
    attrs: Optional[Dict[str, Any]] = None


class AiEditRequest(BaseModel):
    instruction: str


class EngineChatRequest(BaseModel):
    message: str
    layer: str = ""
    chapter: int = 0


class OutlineGenerateRequest(BaseModel):
    layer: str = ""
    requirements: str = ""


class WritingStartRequest(BaseModel):
    start_chapter: int = 1
    total_chapters: int = 0
