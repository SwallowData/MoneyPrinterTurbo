"""
视觉理解服务 - Qwen VL API
用于素材解读，提取图片/视频关键帧的描述和关键词
"""
import base64
import os
from typing import List, Optional, Tuple

from loguru import logger

from app.config import config

# Qwen VL 模型名称
QWEN_VL_MODELS = {
    "plus": "qwen-vl-plus",      # 更便宜，支持 4K
    "max": "qwen-vl-max",        # 更强，支持 4K
    "max-new": "qwen-vl-max-new", # 最新版
}


class VisionService:
    """Qwen VL 视觉理解服务"""

    def __init__(self, api_key: str = "", model: str = "qwen-vl-plus"):
        self.api_key = api_key or config.app.get("qwen_vl_api_key", "")
        self.model = model or config.app.get("qwen_vl_model", "qwen-vl-plus")
        self._ensure_deps()

    def _ensure_deps(self):
        """确保依赖已安装"""
        try:
            import dashscope
            dashscope.api_key = self.api_key
        except ImportError:
            logger.warning("dashscope 未安装，将无法使用 Qwen VL API")

    def analyze_image(
        self,
        image_path: str,
        prompt: str = "请详细描述这张图片的内容，包括主体、场景、氛围等关键元素。"
    ) -> Tuple[str, List[str]]:
        """
        分析单张图片

        Args:
            image_path: 图片路径
            prompt: 提问提示词

        Returns:
            (描述文本, 关键词列表)
        """
        try:
            import dashscope
            from dashscope import MultiModalConversation

            dashscope.api_key = self.api_key

            # 读取图片并转为 base64
            with open(image_path, "rb") as f:
                img_base64 = base64.b64encode(f.read()).decode("utf-8")

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"image": f"data:image/jpeg;base64,{img_base64}"},
                        {"text": prompt},
                    ],
                }
            ]

            response = MultiModalConversation.call(
                model=self.model,
                messages=messages,
            )

            if response and response.status_code == 200:
                content = response.output.choices[0].message.content[0]["text"]
                keywords = self._extract_keywords(content)
                return content, keywords
            else:
                error_msg = response.message if response else "Unknown error"
                logger.error(f"Qwen VL API 错误: {error_msg}")
                return "", []

        except Exception as e:
            logger.error(f"图片分析失败: {e}")
            return "", []

    def analyze_video_frames(
        self,
        video_path: str,
        frame_count: int = 3,
        prompt: str = "请详细描述这个视频片段的内容，包括主体、场景、动作、氛围等关键元素。"
    ) -> Tuple[str, List[str]]:
        """
        分析视频（提取关键帧）

        Args:
            video_path: 视频路径
            frame_count: 提取的关键帧数量
            prompt: 提问提示词

        Returns:
            (描述文本, 关键词列表)
        """
        try:
            from moviepy.editor import VideoFileClip

            clip = VideoFileClip(video_path)
            duration = clip.duration

            if duration <= 0:
                logger.warning(f"视频时长无效: {video_path}")
                return "", []

            # 均匀提取关键帧
            timestamps = [duration * i / (frame_count + 1) for i in range(1, frame_count + 1)]

            frame_descriptions = []
            for ts in timestamps:
                frame_path = self._extract_frame(video_path, ts)
                if frame_path:
                    desc, _ = self.analyze_image(frame_path, prompt)
                    if desc:
                        frame_descriptions.append(f"[{int(ts)}s] {desc}")
                    # 删除临时帧
                    try:
                        os.remove(frame_path)
                    except Exception:
                        pass

            if frame_descriptions:
                full_description = f"视频总时长: {int(duration)}秒\n" + "\n".join(frame_descriptions)
                keywords = self._extract_keywords(" ".join(frame_descriptions))
                return full_description, keywords

            return "", []

        except Exception as e:
            logger.error(f"视频分析失败: {e}")
            return "", []

    def _extract_frame(self, video_path: str, timestamp: float) -> Optional[str]:
        """提取指定时间点的帧图片"""
        try:
            import cv2

            video_path = video_path.replace("\\", "/")
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            success, frame = cap.read()
            cap.release()

            if success:
                # 保存为临时文件
                temp_dir = os.path.join(os.path.dirname(video_path), "temp_frames")
                os.makedirs(temp_dir, exist_ok=True)
                frame_path = os.path.join(temp_dir, f"frame_{int(timestamp)}.jpg")
                cv2.imwrite(frame_path, frame)
                return frame_path
            return None
        except Exception as e:
            logger.error(f"提取帧失败: {e}")
            return None

    def _extract_keywords(self, text: str) -> List[str]:
        """从描述文本中提取关键词"""
        # 使用 LLM 提取关键词
        prompt = f"""
请从以下描述文本中提取5-10个关键词，用于素材检索。
要求：
1. 提取的名词或短语应该具有检索意义
2. 返回JSON数组格式
3. 只返回关键词，不要其他内容
4. 使用中文

描述文本：
{text}

输出格式：
["关键词1", "关键词2", "关键词3", ...]
""".strip()

        try:
            from app.services.llm import _generate_response
            response = _generate_response(prompt)
            if response and "Error:" not in response:
                import json
                keywords = json.loads(response)
                if isinstance(keywords, list):
                    return keywords[:10]
        except Exception as e:
            logger.warning(f"关键词提取失败: {e}")

        # 降级：简单分词
        import re
        words = re.findall(r"[\u4e00-\u9fa5a-zA-Z]{2,}", text)
        return list(set(words))[:10]

    def get_thumbnail(self, video_path: str, timestamp: float = 0.5) -> Optional[str]:
        """获取视频缩略图"""
        try:
            import cv2

            video_path = video_path.replace("\\", "/")
            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)

            if total_frames <= 0 or fps <= 0:
                cap.release()
                return None

            # 在指定时间点提取帧
            frame_idx = int(min(timestamp, 0.99) * total_frames)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            success, frame = cap.read()
            cap.release()

            if success:
                thumb_dir = os.path.join(os.path.dirname(video_path), "thumbnails")
                os.makedirs(thumb_dir, exist_ok=True)
                from app.utils.utils import md5
                thumb_name = f"thumb_{md5(video_path)}.jpg"
                thumb_path = os.path.join(thumb_dir, thumb_name)
                cv2.imwrite(thumb_path, frame)
                return thumb_path
            return None
        except Exception as e:
            logger.error(f"生成缩略图失败: {e}")
            return None


# 全局单例
_vision_service: Optional[VisionService] = None


def get_vision_service() -> VisionService:
    """获取视觉服务单例"""
    global _vision_service
    if _vision_service is None:
        _vision_service = VisionService()
    return _vision_service


def analyze_material(
    file_path: str,
    file_type: str = "video",
    force: bool = False,
) -> Tuple[str, List[str], Optional[str]]:
    """
    分析素材的统一入口

    Args:
        file_path: 素材路径
        file_type: 素材类型 (video/image)
        force: 是否强制重新分析

    Returns:
        (描述, 关键词列表, 缩略图路径)
    """
    # 检查是否已有分析结果
    if not force:
        from app.services.material_db import get_material_db
        db = get_material_db()
        existing = db.get_by_path(file_path)
        if existing and existing.description:
            return existing.description, existing.keywords, existing.thumbnail_path

    # 执行分析
    service = get_vision_service()

    if file_type == "video":
        description, keywords = service.analyze_video_frames(file_path)
        thumbnail = service.get_thumbnail(file_path)
    else:
        description, keywords = service.analyze_image(file_path)
        thumbnail = file_path  # 图片本身作为缩略图

    return description, keywords, thumbnail
