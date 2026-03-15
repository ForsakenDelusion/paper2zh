"""数据模型"""

from enum import Enum

from pydantic import BaseModel


class JobStage(str, Enum):
    """任务阶段"""

    PENDING = "pending"
    CONVERTING = "converting"
    SPLITTING = "splitting"
    TAGGING = "tagging"
    TRANSLATING = "translating"
    COMPLETED = "completed"
    FAILED = "failed"


class JobProgress(BaseModel):
    """进度信息"""

    stage: JobStage
    current: int = 0
    total: int = 0
    message: str = ""


class JobInfo(BaseModel):
    """任务完整信息"""

    job_id: str
    filename: str
    progress: JobProgress
    created_at: str
    result_path: str | None = None
    error: str | None = None


class TranslateConfig(BaseModel):
    """翻译配置"""

    backend: str = "hybrid-auto-engine"
    model: str = "deepseek-chat"
    api_key: str | None = None
    base_url: str | None = None
    lang: str = "en"
