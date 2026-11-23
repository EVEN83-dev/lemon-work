# -*- coding: utf-8 -*-
"""Skill: video_reader — 视频内容阅读（关键帧 + 本地视觉模型）

能力边界（如实）：
  - 能：读取容器元数据（分辨率/FPS/时长），抽关键帧，拼图后交给本地视觉模型
        概括场景、人物/物体、画面文字，并可回答用户针对视频的问题。
  - 不能：音频转写（本机无 whisper/ffmpeg），因此对白/旁白无法转文字。
  - 依赖：opencv-python（cv2）、Pillow；视觉模型 qwen3.5 / qwen3-vl（Ollama）。
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import base64
import math
import os
import re
import threading
import time
from typing import Any, Dict, List, Tuple

try:
    from skills_registry import SkillDef, SkillResult
except Exception:
    from standard_mode.core.skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "video_reader",
    "description": ("读取视频内容：抽取关键帧并调用本地视觉模型概括场景、人物/物体、"
                    "画面文字；无旁挂字幕时用 faster-whisper 本地转写对白/旁白。"),
    "category": "media",
    "version": "1.1.0",
}

_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".m4v", ".wmv", ".mpg", ".mpeg"}

# ── faster-whisper 模型缓存（首次加载/下载较慢，进程内复用）──
_WHISPER_MODEL = None
_WHISPER_MODEL_NAME = ""
_WHISPER_LOCK = threading.Lock()
_WHISPER_RUN_LOCK = threading.Lock()
_DEFAULT_WHISPER_MODEL = os.environ.get("LW_WHISPER_MODEL", "small").strip() or "small"


def _patch_av_compat():
    """PyAV >= 19 移除了 av.open(metadata_errors=...)；
    faster-whisper 1.2.1 仍会传这个参数，这里做一次幂等兼容垫片。"""
    try:
        import av
        if getattr(av, "_lw_meta_compat", False):
            return
        _orig_open = av.open

        def _open(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return _orig_open(*args, **kwargs)

        av.open = _open
        av._lw_meta_compat = True
    except Exception:
        logger.debug("suppressed exception")


def transcribe_media(path: str, model_name: str = "", language: str = "auto",
                     max_chars: int = 4000) -> Tuple[str, str, Dict[str, Any]]:
    """本地 faster-whisper 语音转写（视频/音频文件均可）。

    返回 (文本, 错误, 元信息)。模型首次使用会从 HuggingFace 下载，
    默认 small（中文效果优于 base/tiny）。
    """
    global _WHISPER_MODEL, _WHISPER_MODEL_NAME
    _patch_av_compat()
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        return "", f"faster-whisper 未安装: {e}", {}

    # 国内网络默认走镜像（不覆盖用户已显式设置的 HF_ENDPOINT）
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    name = (model_name or _DEFAULT_WHISPER_MODEL).strip() or "small"

    with _WHISPER_LOCK:
        if _WHISPER_MODEL is None or _WHISPER_MODEL_NAME != name:
            last_err = None
            for cand in (name, "base", "tiny"):
                try:
                    _WHISPER_MODEL = WhisperModel(
                        cand, device="cpu", compute_type="int8",
                        cpu_threads=max(1, min(8, os.cpu_count() or 4)))
                    _WHISPER_MODEL_NAME = cand
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
            if _WHISPER_MODEL is None:
                return "", f"语音模型加载失败: {last_err}", {}
        model = _WHISPER_MODEL
        used_model = _WHISPER_MODEL_NAME

    lang = None if (not language or str(language).lower() == "auto") else str(language)
    initial_prompt = None
    if lang == "zh":
        initial_prompt = ("以下是柠檬工作台（Lemon Work）的中文语音，可能包含"
                          "多智能体、AI 工作台、语音转写等词。")
    try:
        with _WHISPER_RUN_LOCK:
            segments, info = model.transcribe(
                path, language=lang, vad_filter=True, beam_size=5,
                condition_on_previous_text=False,
                initial_prompt=initial_prompt)
            parts: List[str] = []
            total = 0
            for seg in segments:
                t = (seg.text or "").strip()
                if not t:
                    continue
                parts.append(t)
                total += len(t)
                if total >= max_chars:
                    break
        text = "\n".join(parts).strip()[:max_chars]
        meta = {
            "model": used_model,
            "language": getattr(info, "language", "") or "",
            "duration": round(float(getattr(info, "duration", 0) or 0), 2),
        }
        return text, "", meta
    except Exception as e:
        return "", f"音频转写失败: {e}", {}


def _fmt_sec(sec: float) -> str:
    sec = max(0.0, float(sec or 0.0))
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m}分{s:.1f}秒" if m else f"{s:.1f}秒"


def _build_montage(frames: List[Tuple[float, Any]], out_path: str) -> bool:
    """把关键帧拼成 2 列网格并标注时间戳；成功返回 True。"""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False
    try:
        thumbs = []
        tw = 480
        for ts, frame in frames:
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            ratio = tw / max(1, img.width)
            img = img.resize((tw, max(1, int(img.height * ratio))))
            thumbs.append((ts, img))
        if not thumbs:
            return False
        cols = 2
        rows = int(math.ceil(len(thumbs) / cols))
        pad = 8
        label_h = 20
        cell_w = max(i.width for _, i in thumbs) + pad * 2
        cell_h = max(i.height for _, i in thumbs) + pad * 2 + label_h
        canvas = Image.new("RGB", (cell_w * cols, cell_h * rows), (18, 18, 22))
        draw = ImageDraw.Draw(canvas)
        for idx, (ts, img) in enumerate(thumbs):
            r, c = divmod(idx, cols)
            x = c * cell_w + pad
            y = r * cell_h + pad
            canvas.paste(img, (x, y))
            draw.text((x, y + img.height + 3), f"t={ts:.1f}s", fill=(255, 190, 120))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        canvas.save(out_path, "JPEG", quality=86)
        return True
    except Exception:
        return False


def _read_text(path: str) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                return f.read()
        except Exception:
            continue
    return ""


def _load_subtitle(video_path: str) -> Tuple[str, str]:
    """读取视频旁挂字幕（.srt/.vtt/.ass/.ssa），返回 (路径, 文本)。

    本机没有 whisper/ffmpeg 时，旁挂字幕是获取“对白/旁白”的唯一可靠来源。
    """
    stem = os.path.splitext(video_path)[0]
    for ext in (".srt", ".vtt", ".ass", ".ssa"):
        path = stem + ext
        if not os.path.exists(path):
            continue
        raw = _read_text(path)
        if not raw.strip():
            continue
        lines: List[str] = []
        if ext in (".srt", ".vtt"):
            for ln in raw.splitlines():
                s = ln.strip()
                if (not s or s.isdigit() or "-->" in s
                        or s.upper().startswith("WEBVTT")):
                    continue
                s = re.sub(r"<[^>]+>", "", s)
                if s and (not lines or lines[-1] != s):
                    lines.append(s)
        else:
            for ln in raw.splitlines():
                if not ln.strip().lower().startswith("dialogue:"):
                    continue
                parts = ln.split(",", 9)
                if len(parts) >= 10:
                    t = re.sub(r"\{[^}]*\}", "", parts[9]).replace("\\N", " ").strip()
                    if t and (not lines or lines[-1] != t):
                        lines.append(t)
        text = "\n".join(lines).strip()
        if text:
            return path, text[:4000]
    return "", ""


def execute(video_path: str = "", prompt: str = "",
            max_frames: int = 4, interval_sec: float = 0,
            transcribe: bool = True, language: str = "auto",
            asr_model: str = "") -> SkillResult:
    if not video_path:
        return SkillResult(success=False, error="video_path 参数为空")
    if not os.path.exists(video_path):
        return SkillResult(success=False, error=f"视频不存在: {video_path}")
    ext = os.path.splitext(video_path)[1].lower()
    if ext not in _VIDEO_EXTS:
        return SkillResult(success=False,
                           error=f"不支持的视频格式: {ext}（支持 {', '.join(sorted(_VIDEO_EXTS))}）")
    try:
        import cv2
    except Exception as e:
        return SkillResult(success=False, error=f"opencv 未安装，无法读取视频: {e}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        return SkillResult(
            success=False,
            error=("视频无法解码（可能是编码器不受支持）。可先转成 H.264 MP4 再试。"),
        )
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = (total / fps) if fps > 0 else 0.0
        n = max(1, min(int(max_frames or 4), 8))

        times: List[float] = []
        if interval_sec and interval_sec > 0:
            t = 0.0
            while len(times) < n and (duration <= 0 or t <= duration):
                times.append(t)
                t += float(interval_sec)
        elif duration > 0:
            times = [duration * (i + 0.5) / n for i in range(n)]
        else:
            times = [float(i) for i in range(n)]

        frames: List[Tuple[float, Any]] = []
        for t in times:
            if fps > 0 and total > 0:
                fidx = min(total - 1, max(0, int(t * fps)))
                cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
            else:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append((float(t), frame))
        if not frames:
            return SkillResult(success=False, error="未能从视频中抽到任何关键帧")
    finally:
        cap.release()

    # 落盘关键帧（本机 data/video_frames/，便于用户复核）
    stem = os.path.splitext(os.path.basename(video_path))[0]
    out_dir = os.path.join(os.getcwd(), "data", "video_frames",
                           f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)
    frame_paths = []
    for i, (t, frame) in enumerate(frames):
        fp = os.path.join(out_dir, f"frame_{i + 1:02d}_{t:.1f}s.jpg")
        try:
            cv2.imwrite(fp, frame)
            frame_paths.append(fp)
        except Exception:
            logger.debug("suppressed exception")

    montage_path = os.path.join(out_dir, "montage.jpg")
    has_montage = _build_montage(frames, montage_path)

    # ★ 2026-11-23: 旁挂字幕优先；没有字幕再用 faster-whisper 本地转写
    sub_path, sub_text = _load_subtitle(video_path)
    asr_text, asr_err, asr_meta = "", "", {}
    if transcribe and not sub_text:
        asr_text, asr_err, asr_meta = transcribe_media(
            video_path, model_name=asr_model, language=language)
    dialogue = sub_text or asr_text
    dialogue_src = "旁挂字幕" if sub_text else ("本地语音转写" if asr_text else "")

    summary = ""
    if has_montage:
        try:
            try:
                from vision_client import describe_images
            except Exception:
                from standard_mode.core.vision_client import describe_images
            with open(montage_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            q = (prompt or "请概括这个视频的内容").strip()
            sub_note = ""
            if dialogue:
                sub_note = (f"\n\n该视频的对白来源：{dialogue_src}，请结合它回答（原文）：\n"
                            f"{dialogue[:2500]}")
            summary = describe_images(
                [b64],
                ("这是同一段视频按时间顺序抽取的关键帧拼图（从左到右、从上到下，"
                 f"标注了时间戳）。请用中文概括视频内容、场景变化、出现的人物/物体/"
                 f"画面文字，并回答用户问题：{q}" + sub_note),
                timeout=150,
            )
        except Exception:
            summary = ""

    meta = (f"视频: {os.path.basename(video_path)}\n"
            f"时长: {_fmt_sec(duration)} · 分辨率: {width}x{height} · FPS: {fps:.2f} · "
            f"总帧数: {total}\n关键帧: 已抽取 {len(frames)} 张 → {out_dir}")
    if sub_text:
        sub_section = (f"\n\n【字幕/对白】来源: {os.path.basename(sub_path)}\n"
                       f"{sub_text[:1500]}")
    elif asr_text:
        _lang = (asr_meta or {}).get("language") or "auto"
        sub_section = (f"\n\n【语音转写】本地 faster-whisper（模型 "
                       f"{(asr_meta or {}).get('model', '')} · 语言 {_lang}）\n"
                       f"{asr_text[:1500]}")
    else:
        sub_section = ("\n\n【字幕/对白】未找到旁挂字幕，语音转写也未得到文本"
                       + (f"：{asr_err}" if asr_err else "（视频可能无音轨）"))
    if summary:
        output = f"{meta}{sub_section}\n\n【视觉模型解读】\n{summary}"
    else:
        output = (f"{meta}{sub_section}\n\n【视觉模型不可用】已导出关键帧供人工查看；"
                  "如需自动解读，请先 ollama pull qwen3.5:4b 或 qwen3-vl:4b。")

    return SkillResult(
        success=True,
        output=output,
        data={
            "duration": round(duration, 2),
            "fps": round(fps, 2),
            "width": width, "height": height, "total_frames": total,
            "frames": frame_paths,
            "montage": montage_path if has_montage else "",
            "summary": summary,
            "subtitle_path": sub_path,
            "subtitle_text": sub_text,
            "audio_transcript": asr_text,
            "asr_model": (asr_meta or {}).get("model", ""),
            "asr_language": (asr_meta or {}).get("language", ""),
            "asr_error": asr_err,
        },
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="video_reader",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "video_path": {"type": "string", "description": "视频文件路径"},
                "prompt": {"type": "string",
                           "description": "要问视频的问题，如“画面里发生了什么”"},
                "max_frames": {"type": "integer",
                               "description": "抽取关键帧数量（1-8）", "default": 4},
                "interval_sec": {"type": "number",
                                 "description": "按固定秒间隔抽帧；0=均匀抽帧", "default": 0},
                "transcribe": {"type": "boolean",
                               "description": "无旁挂字幕时是否本地转写音频", "default": True},
                "language": {"type": "string",
                             "description": "语音语言：auto/zh/en 等", "default": "auto"},
                "asr_model": {"type": "string",
                              "description": "faster-whisper 模型：tiny/base/small/medium",
                              "default": "small"},
            },
            "required": ["video_path"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=240,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
