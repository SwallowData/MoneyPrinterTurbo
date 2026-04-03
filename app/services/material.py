import os
import random
import uuid
from typing import List, Optional, Tuple
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.models.material import Material, SceneShot, SceneShotResult
from app.services.material_db import get_material_db
from app.services import vision
from app.utils import utils
from app.utils.timer import log_elapsed

requested_count = 0


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global requested_count
    requested_count += 1
    return api_keys[requested_count % len(api_keys)]


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=False,
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if w == video_width and h == video_height:
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=False, timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it (with retry on network errors)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=False,
                timeout=(60, 240),
                stream=True,
            )
            response.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            logger.info(f"video downloaded: {video_path} (attempt {attempt + 1}/{max_retries})")
            break
        except Exception as e:
            logger.warning(f"download attempt {attempt + 1}/{max_retries} failed for {video_url}: {e}")
            if os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except Exception:
                    pass
            if attempt == max_retries - 1:
                logger.error(f"failed to download video after {max_retries} attempts: {video_url}")
                return ""

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            clip.close()
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            try:
                os.remove(video_path)
            except Exception:
                pass
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
    return ""


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
) -> List[str]:
    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay

    with log_elapsed(f"搜索视频 (源: {source})"):
        for search_term in search_terms:
            video_items = search_videos(
                search_term=search_term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
            )
            logger.info(f"found {len(video_items)} videos for '{search_term}'")

            for item in video_items:
                if item.url not in valid_video_urls:
                    valid_video_items.append(item)
                    valid_video_urls.append(item.url)
                    found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if video_contact_mode.value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    with log_elapsed("下载视频"):
        total_duration = 0.0
        for item in valid_video_items:
            try:
                logger.info(f"downloading video: {item.url}")
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    seconds = min(max_clip_duration, item.duration)
                    total_duration += seconds
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                        )
                        break
            except Exception as e:
                logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
        logger.success(f"downloaded {len(video_paths)} videos")
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )


# ===========================================
# 素材管理系统 - 匹配与入库
# ===========================================

def match_materials(
    shots: List[SceneShot],
    match_threshold: float = 0.6,
) -> Tuple[List[SceneShot], List[SceneShot]]:
    """
    匹配分镜与素材库

    Args:
        shots: 分镜列表
        match_threshold: 匹配阈值 (0-1)

    Returns:
        (已匹配的分镜列表, 未匹配的分镜列表)
    """
    db = get_material_db()
    matched_shots = []
    unmatched_shots = []

    for shot in shots:
        # 合并 visual_description 和 keywords 进行检索
        search_keywords = shot.keywords.copy()
        if shot.visual_description:
            # 从描述中提取关键词
            search_keywords.append(shot.visual_description[:50])

        # 搜索相似素材
        results = db.search_by_keywords(
            keywords=search_keywords,
            file_type="video",
            limit=5,
        )

        if results:
            best_material, best_score = results[0]
            # 归一化分数（简单算法，分数范围 0-2，映射到 0-1）
            normalized_score = min(best_score / 2.0, 1.0)

            if normalized_score >= match_threshold:
                shot.matched_material_id = best_material.material_id
                shot.matched_file_path = best_material.file_path
                shot.matched_similarity = normalized_score
                shot.source = "existing"
                matched_shots.append(shot)

                # 增加使用次数
                db.increment_use_count(best_material.material_id)
                logger.info(f"分镜 {shot.shot_id} 匹配到素材: {best_material.file_path} (相似度: {normalized_score:.2f})")
                continue

        # 未匹配
        shot.source = "new"
        unmatched_shots.append(shot)
        logger.info(f"分镜 {shot.shot_id} 未匹配到素材，需要下载")

    return matched_shots, unmatched_shots


def register_material(
    file_path: str,
    source: str = "local",
    source_url: str = "",
    duration: Optional[float] = None,
    force_analyze: bool = False,
) -> Optional[Material]:
    """
    注册新素材到素材库

    Args:
        file_path: 素材文件路径
        source: 来源 (pexels/pixabay/local)
        source_url: 原始 URL
        duration: 视频时长
        force_analyze: 是否强制重新分析

    Returns:
        注册的 Material 对象，或 None
    """
    # 检查是否已存在（使用文件名匹配，兼容不同环境下的路径）
    db = get_material_db()
    filename = os.path.basename(file_path)
    existing = db.get_by_filename(filename)
    if existing and not force_analyze:
        logger.debug(f"素材已存在（文件名匹配）: {filename}")
        return existing

    # 确定文件类型
    ext = os.path.splitext(file_path)[1].lower()
    file_type = "video" if ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"] else "image"

    # 获取视频时长
    if file_type == "video" and duration is None:
        try:
            clip = VideoFileClip(file_path)
            duration = clip.duration
            clip.close()
        except Exception as e:
            logger.warning(f"获取视频时长失败: {file_path} => {e}")
            duration = 0

    # 创建素材对象
    material = Material(
        material_id=str(uuid.uuid4()),
        file_path=file_path,
        file_type=file_type,
        source=source,
        source_url=source_url,
        duration=duration,
    )

    # 使用视觉服务分析素材
    logger.info(f"🎬 开始解读素材: [{filename}]")
    description, keywords, thumbnail_path = vision.analyze_material(
        file_path=file_path,
        file_type=file_type,
        force=force_analyze,
    )

    material.description = description
    material.keywords = keywords
    material.thumbnail_path = thumbnail_path

    # 输出解读结果到日志
    logger.info(f"📝 素材描述: {description[:200] if description else '无'}...")
    logger.info(f"🏷️  提取关键词: {keywords}")

    # 写入数据库
    if db.insert(material):
        logger.success(f"✅ 素材注册成功: {material.material_id} [{filename}]")
        return material
    else:
        logger.error(f"❌ 素材注册失败: {file_path}")
        return None


def get_materials_for_shots(
    shots: List[SceneShot],
    task_id: str,
    params,
    match_threshold: float = 0.6,
) -> SceneShotResult:
    """
    根据分镜获取素材（优先使用素材库，必要时下载）

    Args:
        shots: 分镜列表
        task_id: 任务 ID
        params: 视频参数
        match_threshold: 匹配阈值

    Returns:
        SceneShotResult: 包含所有分镜的匹配结果
    """
    # 1. 先匹配素材库
    matched_shots, unmatched_shots = match_materials(shots, match_threshold)
    logger.info(f"素材匹配完成: {len(matched_shots)} 命中, {len(unmatched_shots)} 需要下载")

    # 2. 如果有未匹配的，需要下载新素材
    new_download_count = 0
    if unmatched_shots:
        # 收集需要下载的关键词
        download_keywords = []
        for shot in unmatched_shots:
            download_keywords.extend(shot.keywords[:3])  # 每个分镜取前3个关键词

        # 去重
        download_keywords = list(dict.fromkeys(download_keywords))[:10]

        if download_keywords:
            logger.info(f"开始下载新素材，关键词: {download_keywords}")
            # 下载视频
            new_videos = download_videos(
                task_id=task_id,
                search_terms=download_keywords,
                source=params.video_source,
                video_aspect=params.video_aspect,
                video_contact_mode=VideoConcatMode.random,
                audio_duration=sum(s.duration_hint for s in unmatched_shots),
                max_clip_duration=params.video_clip_duration,
            )

            # 3. 注册新下载的素材
            for video_path in new_videos:
                if video_path and os.path.exists(video_path):
                    # 从 URL 推断来源
                    source = "pexels" if "pexels" in str(params.video_source).lower() else params.video_source
                    material = register_material(
                        file_path=video_path,
                        source=source,
                    )
                    if material:
                        new_download_count += 1
                        # 更新分镜的素材信息（如果有未匹配的分镜需要素材）
                        for shot in unmatched_shots:
                            if shot.matched_file_path is None:
                                shot.matched_material_id = material.material_id
                                shot.matched_file_path = material.file_path
                                shot.source = "new"
                                break

    # 4. 整理结果
    all_shots = matched_shots + unmatched_shots
    all_shots.sort(key=lambda x: x.shot_id)

    # 分配素材给未匹配的分镜（如果有新下载的）
    new_materials = [s for s in all_shots if s.source == "new" and s.matched_file_path]
    for i, shot in enumerate(unmatched_shots):
        if shot.matched_file_path is None and i < len(new_materials):
            shot.matched_material_id = new_materials[i].matched_material_id
            shot.matched_file_path = new_materials[i].matched_file_path

    return SceneShotResult(
        shots=all_shots,
        total_shots=len(all_shots),
        matched_count=len(matched_shots),
        new_download_count=new_download_count,
    )


def get_video_paths_from_shots(shots: List[SceneShot]) -> List[str]:
    """
    从分镜结果获取视频路径列表

    Args:
        shots: 分镜列表

    Returns:
        视频路径列表
    """
    paths = []
    for shot in shots:
        if shot.matched_file_path and os.path.exists(shot.matched_file_path):
            paths.append(shot.matched_file_path)
    return paths
