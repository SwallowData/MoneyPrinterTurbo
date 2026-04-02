import glob
import itertools
import os
import random
import gc
import shutil
import subprocess
from typing import List
from loguru import logger
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import ImageFont

from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services.utils import video_effects
from app.utils import utils
from app.utils.timer import log_elapsed

class SubClippedVideoClip:
    def __init__(self, file_path, start_time=None, end_time=None, width=None, height=None, duration=None):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        if duration is None:
            self.duration = end_time - start_time
        else:
            self.duration = duration

    def __str__(self):
        return f"SubClippedVideoClip(file_path={self.file_path}, start_time={self.start_time}, end_time={self.end_time}, duration={self.duration}, width={self.width}, height={self.height})"


audio_codec = "aac"
video_codec = "libx264"
fps = 30

def close_clip(clip):
    if clip is None:
        return
        
    try:
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            clip.reader.close()
            
        # close audio resources
        if hasattr(clip, 'audio') and clip.audio is not None:
            if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                clip.audio.reader.close()
            del clip.audio
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                clip.mask.reader.close()
            del clip.mask
            
        # handle child clips in composite clips
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")
    
    del clip
    gc.collect()

def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]
        
    for file in files:
        try:
            os.remove(file)
        except:
            pass

def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        return random.choice(files)

    return ""


# --- GPU encoding auto-detection ---

_nvenc_available: bool | None = None

def get_video_codec() -> str:
    """Auto-detect the best available video encoder."""
    global _nvenc_available

    # Allow override via environment variable
    env_codec = os.environ.get("VIDEO_CODEC", "")
    if env_codec:
        logger.info(f"video codec overridden by env: {env_codec}")
        return env_codec

    # Cache the detection result
    if _nvenc_available is not None:
        if _nvenc_available:
            return "h264_nvenc"
        return "libx264"

    # Detect h264_nvenc availability
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders", "-hide_banner"],
            capture_output=True, text=True, timeout=10,
        )
        if "h264_nvenc" in result.stdout:
            _nvenc_available = True
            logger.info("video codec: h264_nvenc (GPU encoding)")
            return "h264_nvenc"
    except Exception as e:
        logger.debug(f"failed to detect GPU encoder: {e}")

    _nvenc_available = False
    logger.info("video codec: libx264 (CPU encoding)")
    return "libx264"


def get_ffmpeg_params(codec: str | None = None) -> list[str]:
    """Get additional ffmpeg parameters for the given codec."""
    codec = codec or get_video_codec()
    if codec == "h264_nvenc":
        return ["-preset", "p4", "-tune", "hq"]
    return []


def concat_videos_ffmpeg(clip_files: List[str], output_path: str) -> bool:
    """Concatenate video clips using FFmpeg concat demuxer without re-encoding."""
    output_dir = os.path.dirname(output_path)
    filelist = os.path.join(output_dir, "filelist.txt")

    try:
        with open(filelist, "w", encoding="utf-8") as f:
            for clip_file in clip_files:
                f.write(f"file '{clip_file}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", filelist,
            "-c", "copy",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.warning(f"ffmpeg concat failed (will fallback to MoviePy): {result.stderr}")
            return False

        logger.info(f"ffmpeg concat succeeded, merged {len(clip_files)} clips without re-encoding")
        return True

    except Exception as e:
        logger.warning(f"ffmpeg concat error (will fallback to MoviePy): {e}")
        return False

    finally:
        try:
            os.remove(filelist)
        except Exception:
            pass


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
) -> str:
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"audio duration: {audio_duration} seconds")
    # Required duration of each clip
    req_dur = audio_duration / len(video_paths)
    req_dur = max_clip_duration
    logger.info(f"maximum clip duration: {req_dur} seconds")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    processed_clips = []
    subclipped_items = []
    video_duration = 0
    for video_path in video_paths:
        clip = VideoFileClip(video_path)
        clip_duration = clip.duration
        clip_w, clip_h = clip.size
        close_clip(clip)
        
        start_time = 0

        while start_time < clip_duration:
            end_time = min(start_time + max_clip_duration, clip_duration)            
            if clip_duration - start_time >= max_clip_duration:
                subclipped_items.append(SubClippedVideoClip(file_path= video_path, start_time=start_time, end_time=end_time, width=clip_w, height=clip_h))
            start_time = end_time    
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    # random subclipped_items order
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(subclipped_items)
        
    logger.debug(f"total subclipped items: {len(subclipped_items)}")

    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    with log_elapsed("片段切分与编码"):
        for i, subclipped_item in enumerate(subclipped_items):
            if video_duration > audio_duration:
                break

            logger.debug(f"processing clip {i+1}: {subclipped_item.width}x{subclipped_item.height}, current duration: {video_duration:.2f}s, remaining: {audio_duration - video_duration:.2f}s")

            try:
                clip = VideoFileClip(subclipped_item.file_path).subclipped(subclipped_item.start_time, subclipped_item.end_time)
                clip_duration = clip.duration
                # Not all videos are same size, so we need to resize them
                clip_w, clip_h = clip.size
                if clip_w != video_width or clip_h != video_height:
                    clip_ratio = clip.w / clip.h
                    video_ratio = video_width / video_height
                    logger.debug(f"resizing clip, source: {clip_w}x{clip_h}, ratio: {clip_ratio:.2f}, target: {video_width}x{video_height}, ratio: {video_ratio:.2f}")

                    if clip_ratio == video_ratio:
                        clip = clip.resized(new_size=(video_width, video_height))
                    else:
                        if clip_ratio > video_ratio:
                            scale_factor = video_width / clip_w
                        else:
                            scale_factor = video_height / clip_h

                        new_width = int(clip_w * scale_factor)
                        new_height = int(clip_h * scale_factor)

                        background = ColorClip(size=(video_width, video_height), color=(0, 0, 0)).with_duration(clip_duration)
                        clip_resized = clip.resized(new_size=(new_width, new_height)).with_position("center")
                        clip = CompositeVideoClip([background, clip_resized])

                shuffle_side = random.choice(["left", "right", "top", "bottom"])
                if video_transition_mode.value == VideoTransitionMode.none.value:
                    clip = clip
                elif video_transition_mode.value == VideoTransitionMode.fade_in.value:
                    clip = video_effects.fadein_transition(clip, 1)
                elif video_transition_mode.value == VideoTransitionMode.fade_out.value:
                    clip = video_effects.fadeout_transition(clip, 1)
                elif video_transition_mode.value == VideoTransitionMode.slide_in.value:
                    clip = video_effects.slidein_transition(clip, 1, shuffle_side)
                elif video_transition_mode.value == VideoTransitionMode.slide_out.value:
                    clip = video_effects.slideout_transition(clip, 1, shuffle_side)
                elif video_transition_mode.value == VideoTransitionMode.shuffle.value:
                    transition_funcs = [
                        lambda c: video_effects.fadein_transition(c, 1),
                        lambda c: video_effects.fadeout_transition(c, 1),
                        lambda c: video_effects.slidein_transition(c, 1, shuffle_side),
                        lambda c: video_effects.slideout_transition(c, 1, shuffle_side),
                    ]
                    shuffle_transition = random.choice(transition_funcs)
                    clip = shuffle_transition(clip)

                if clip.duration > max_clip_duration:
                    clip = clip.subclipped(0, max_clip_duration)

                # wirte clip to temp file
                clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
                clip.write_videofile(
                    clip_file, logger=None, fps=fps,
                    codec=get_video_codec(),
                    ffmpeg_params=get_ffmpeg_params(),
                )

                close_clip(clip)

                processed_clips.append(SubClippedVideoClip(file_path=clip_file, duration=clip.duration, width=clip_w, height=clip_h))
                video_duration += clip.duration

            except Exception as e:
                logger.error(f"failed to process clip: {str(e)}")

        # loop processed clips until the video duration matches or exceeds the audio duration.
        if video_duration < audio_duration:
            logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
            base_clips = processed_clips.copy()
            for clip in itertools.cycle(base_clips):
                if video_duration >= audio_duration:
                    break
                processed_clips.append(clip)
                video_duration += clip.duration
            logger.info(f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, looped {len(processed_clips)-len(base_clips)} clips")

    # merge video clips using FFmpeg concat (no re-encoding) with MoviePy fallback
    with log_elapsed("片段合并"):
        logger.info("starting clip merging process")
        if not processed_clips:
            logger.warning("no clips available for merging")
            return combined_video_path

        # if there is only one clip, use it directly
        if len(processed_clips) == 1:
            logger.info("using single clip directly")
            shutil.copy(processed_clips[0].file_path, combined_video_path)
            delete_files([clip.file_path for clip in processed_clips])
            logger.info("video combining completed")
            return combined_video_path

        clip_files = [clip.file_path for clip in processed_clips]

        # Try FFmpeg concat demuxer first (no re-encoding, much faster)
        if concat_videos_ffmpeg(clip_files, combined_video_path):
            delete_files(clip_files)
            logger.info("video combining completed")
            return combined_video_path

        # Fallback: use MoviePy to concatenate all clips at once
        logger.info("fallback to MoviePy concatenation")
        try:
            clips = []
            for clip_info in processed_clips:
                try:
                    c = VideoFileClip(clip_info.file_path)
                    clips.append(c)
                except Exception as e:
                    logger.error(f"failed to load clip {clip_info.file_path}: {e}")

            if clips:
                merged_clip = concatenate_videoclips(clips)
                merged_clip.write_videofile(
                    filename=combined_video_path,
                    threads=threads,
                    logger=None,
                    temp_audiofile_path=output_dir,
                    audio_codec=audio_codec,
                    fps=fps,
                    codec=get_video_codec(),
                    ffmpeg_params=get_ffmpeg_params(),
                )
                close_clip(merged_clip)

        except Exception as e:
            logger.error(f"MoviePy concatenation failed: {e}")

        # clean temp files
        delete_files(clip_files)

    logger.info("video combining completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # Create ImageFont
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    return result, height


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
):
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"generating video: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # https://github.com/harry0703/MoneyPrinterTurbo/issues/217
    # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'final-1.mp4.tempTEMP_MPY_wvf_snd.mp3'
    # write into the same directory as the output file
    output_dir = os.path.dirname(output_file)

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "STHeitiMedium.ttc"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"  ⑤ font: {font_path}")

    def create_text_clip(subtitle_item):
        params.font_size = int(params.font_size)
        params.stroke_width = int(params.stroke_width)
        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        wrapped_txt, txt_height = wrap_text(
            phrase, max_width=max_width, font=font_path, fontsize=params.font_size
        )
        interline = int(params.font_size * 0.25)
        size=(int(max_width), int(txt_height + params.font_size * 0.25 + (interline * (wrapped_txt.count("\n") + 1))))

        _clip = TextClip(
            text=wrapped_txt,
            font=font_path,
            font_size=params.font_size,
            color=params.text_fore_color,
            bg_color=params.text_background_color,
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            # interline=interline,
            # size=size,
        )
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.with_start(subtitle_item[0][0])
        _clip = _clip.with_end(subtitle_item[0][1])
        _clip = _clip.with_duration(duration)
        if params.subtitle_position == "bottom":
            _clip = _clip.with_position(("center", max(10, video_height * 0.92 - _clip.h)))
        elif params.subtitle_position == "top":
            _clip = _clip.with_position(("center", video_height * 0.05))
        elif params.subtitle_position == "custom":
            # Ensure the subtitle is fully within the screen bounds
            margin = 10  # Additional margin, in pixels
            max_y = video_height - _clip.h - margin
            min_y = margin
            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
            custom_y = max(
                min_y, min(custom_y, max_y)
            )  # Constrain the y value within the valid range
            _clip = _clip.with_position(("center", custom_y))
        else:  # center
            _clip = _clip.with_position(("center", "center"))
        return _clip

    with log_elapsed("最终视频渲染"):
        video_clip = VideoFileClip(video_path).without_audio()
        audio_clip = AudioFileClip(audio_path).with_effects(
            [afx.MultiplyVolume(params.voice_volume)]
        )

        def make_textclip(text):
            return TextClip(
                text=text,
                font=font_path,
                font_size=params.font_size,
            )

        if subtitle_path and os.path.exists(subtitle_path):
            sub = SubtitlesClip(
                subtitles=subtitle_path, encoding="utf-8", make_textclip=make_textclip
            )
            text_clips = []
            for item in sub.subtitles:
                clip = create_text_clip(subtitle_item=item)
                text_clips.append(clip)
            video_clip = CompositeVideoClip([video_clip, *text_clips])

        bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
        if bgm_file:
            try:
                bgm_clip = AudioFileClip(bgm_file).with_effects(
                    [
                        afx.MultiplyVolume(params.bgm_volume),
                        afx.AudioFadeOut(3),
                        afx.AudioLoop(duration=video_clip.duration),
                    ]
                )
                audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
            except Exception as e:
                logger.error(f"failed to add bgm: {str(e)}")

        video_clip = video_clip.with_audio(audio_clip)
        video_clip.write_videofile(
            output_file,
            audio_codec=audio_codec,
            temp_audiofile_path=output_dir,
            threads=params.n_threads or 4,
            logger=None,
            fps=fps,
            codec=get_video_codec(),
            ffmpeg_params=get_ffmpeg_params(),
        )
        video_clip.close()
        del video_clip


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    for material in materials:
        if not material.url:
            continue

        ext = utils.parse_extension(material.url)
        try:
            clip = VideoFileClip(material.url)
        except Exception:
            clip = ImageClip(material.url)

        width = clip.size[0]
        height = clip.size[1]
        if width < 480 or height < 480:
            logger.warning(f"low resolution material: {width}x{height}, minimum 480x480 required")
            continue

        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"processing image: {material.url}")
            # Create an image clip and set its duration to 3 seconds
            clip = (
                ImageClip(material.url)
                .with_duration(clip_duration)
                .with_position("center")
            )
            # Apply a zoom effect using the resize method.
            # A lambda function is used to make the zoom effect dynamic over time.
            # The zoom effect starts from the original size and gradually scales up to 120%.
            # t represents the current time, and clip.duration is the total duration of the clip (3 seconds).
            # Note: 1 represents 100% size, so 1.2 represents 120% size.
            zoom_clip = clip.resized(
                lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
            )

            # Optionally, create a composite video clip containing the zoomed clip.
            # This is useful when you want to add other elements to the video.
            final_clip = CompositeVideoClip([zoom_clip])

            # Output the video to a file.
            video_file = f"{material.url}.mp4"
            final_clip.write_videofile(
                video_file, fps=30, logger=None,
                codec=get_video_codec(),
                ffmpeg_params=get_ffmpeg_params(),
            )
            close_clip(clip)
            material.url = video_file
            logger.success(f"image processed: {video_file}")
    return materials