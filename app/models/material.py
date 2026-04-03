"""
素材数据模型
"""
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Material(BaseModel):
    """素材数据库模型"""
    material_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_path: str  # 绝对路径
    file_type: str  # video / image
    description: str = ""  # Qwen VL 解读的描述
    keywords: List[str] = Field(default_factory=list)  # LLM 提取的关键词
    source_url: str = ""  # 来源 URL
    source: str = "local"  # pexels / pixabay / local
    duration: Optional[float] = None  # 视频时长(秒)
    thumbnail_path: Optional[str] = None  # 缩略图路径
    width: Optional[int] = None  # 分辨率宽
    height: Optional[int] = None  # 分辨率高
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    use_count: int = 0  # 被使用次数

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SceneShot(BaseModel):
    """视频分镜模型（内存/临时）"""
    shot_id: int  # 分镜序号
    phase: str = "MAIN"  # HOOK/CONFLICT/RESOLUTION/CLIMAX/MAIN
    script_text: str  # 对应文案内容
    visual_description: str = ""  # 画面描述（LLM 生成）
    emotion: str = "neutral"  # 情绪标签: suspenseful/tense/hopeful/triumphant/neutral
    keywords: List[str] = Field(default_factory=list)  # 检索关键词
    duration_hint: float = 5.0  # 建议时长
    matched_material_id: Optional[str] = None  # 匹配到的素材 ID
    matched_file_path: Optional[str] = None  # 匹配到的素材路径
    matched_similarity: Optional[float] = None  # 匹配相似度
    source: str = "new"  # new / existing / ai / download


class SceneShotResult(BaseModel):
    """分镜结果（用于返回给调用方）"""
    shots: List[SceneShot]
    total_shots: int
    matched_count: int  # 匹配到的素材数量
    new_download_count: int  # 新下载的素材数量
    ai_generated_count: int = 0  # AI 生成的素材数量
