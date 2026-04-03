"""
AI 素材生成服务 - 魔搭社区 API
使用 Qwen 图生图模型生成视频素材
"""
import os
import time
from typing import Optional

import requests
from PIL import Image
from io import BytesIO
from loguru import logger

from app.config import config


class ModelScopeImageGenerator:
    """魔搭社区图生图生成器"""

    def __init__(
        self,
        api_key: str = "",
        model: str = "Qwen/Qwen-Image-2512",
        output_dir: str = "./storage/generated_images",
    ):
        self.base_url = "https://api-inference.modelscope.cn/"
        self.api_key = api_key or config.app.get("modelscope_api_key", "")
        self.model = model
        self.output_dir = output_dir
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._ensure_output_dir()

    def _ensure_output_dir(self):
        """确保输出目录存在"""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        output_filename: str = "",
        timeout: int = 300,
    ) -> Optional[str]:
        """
        使用魔搭社区 API 生成图片

        Args:
            prompt: 图片描述 prompt
            negative_prompt: 负面描述（不想出现的内容）
            output_filename: 输出文件名（不含扩展名）
            timeout: 超时时间（秒）

        Returns:
            生成的图片保存路径，或 None（失败）
        """
        if not self.api_key:
            logger.error("魔搭社区 API Key 未配置，请设置 modelscope_api_key")
            return None

        if not output_filename:
            output_filename = f"generated_{int(time.time())}"

        output_path = os.path.join(self.output_dir, f"{output_filename}.jpg")

        try:
            # 1. 提交异步生成任务
            logger.info(f"提交图片生成任务: {prompt[:50]}...")

            payload = {
                "model": self.model,
                "prompt": prompt,
            }
            if negative_prompt:
                payload["negative_prompt"] = negative_prompt

            response = requests.post(
                f"{self.base_url}v1/images/generations",
                headers={**self.headers, "X-ModelScope-Async-Mode": "true"},
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            task_id = response.json().get("task_id")

            if not task_id:
                logger.error(f"获取 task_id 失败: {response.text}")
                return None

            logger.info(f"任务已提交，task_id: {task_id}")

            # 2. 轮询等待结果
            start_time = time.time()
            poll_interval = 5  # 每 5 秒轮询一次

            while True:
                if time.time() - start_time > timeout:
                    logger.error(f"图片生成超时（{timeout}秒）")
                    return None

                result = requests.get(
                    f"{self.base_url}v1/tasks/{task_id}",
                    headers={**self.headers, "X-ModelScope-Task-Type": "image_generation"},
                    timeout=30,
                )
                result.raise_for_status()
                data = result.json()

                task_status = data.get("task_status", "")

                if task_status == "SUCCEED":
                    output_images = data.get("output_images", [])
                    if not output_images:
                        logger.error("生成成功但无图片返回")
                        return None

                    # 3. 下载图片
                    image_url = output_images[0]
                    logger.info(f"下载图片: {image_url[:50]}...")

                    image_response = requests.get(image_url, timeout=60)
                    image_response.raise_for_status()

                    # 4. 保存图片
                    image = Image.open(BytesIO(image_response.content))
                    image.save(output_path, "JPEG", quality=95)
                    logger.success(f"图片已保存: {output_path}")
                    return output_path

                elif task_status == "FAILED":
                    error_msg = data.get("error", "Unknown error")
                    logger.error(f"图片生成失败: {error_msg}")
                    return None

                elif task_status == "PROCESSING" or task_status == "PENDING":
                    elapsed = int(time.time() - start_time)
                    logger.info(f"图片生成中... 已等待 {elapsed} 秒")

                else:
                    logger.warning(f"未知状态: {task_status}")

                time.sleep(poll_interval)

        except requests.exceptions.Timeout:
            logger.error("API 请求超时")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"API 请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"图片生成异常: {e}")
            return None

    def generate_from_scene_shot(
        self,
        visual_description: str,
        emotion: str = "",
        shot_id: int = 0,
    ) -> Optional[str]:
        """
        根据分镜画面描述生成图片

        Args:
            visual_description: 画面描述
            emotion: 情绪标签，会加入到 prompt 中
            shot_id: 分镜 ID（用于文件名）

        Returns:
            生成的图片路径
        """
        # 构建增强的 prompt
        prompt = visual_description
        if emotion:
            emotion_styles = {
                "suspenseful": "cinematic, mysterious atmosphere, dramatic lighting, dark tones",
                "tense": "intense, stressful, dramatic close-up, dynamic composition",
                "hopeful": "bright, optimistic, warm lighting, uplifting mood",
                "triumphant": "victorious, triumphant, heroic pose, golden hour lighting",
                "neutral": "natural, balanced, clean composition",
            }
            style = emotion_styles.get(emotion, "")
            if style:
                prompt = f"{visual_description}, {style}"

        filename = f"shot_{shot_id:02d}" if shot_id else f"generated_{int(time.time())}"
        return self.generate(prompt=prompt, output_filename=filename)


# 全局单例
_generator: Optional[ModelScopeImageGenerator] = None


def get_image_generator() -> ModelScopeImageGenerator:
    """获取图片生成器单例"""
    global _generator
    if _generator is None:
        _generator = ModelScopeImageGenerator()
    return _generator


def generate_image_for_scene(
    visual_description: str,
    emotion: str = "",
    shot_id: int = 0,
) -> Optional[str]:
    """
    根据分镜生成图片的快捷函数

    Args:
        visual_description: 画面描述
        emotion: 情绪标签
        shot_id: 分镜 ID

    Returns:
        生成的图片路径
    """
    generator = get_image_generator()
    return generator.generate_from_scene_shot(
        visual_description=visual_description,
        emotion=emotion,
        shot_id=shot_id,
    )
