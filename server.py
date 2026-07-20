"""
TikTok Video Creator - Web Server
==================================
Flask server that provides web interface and API endpoints
for video generation using FFmpeg, edge-tts, and PIL.
"""

import os
import sys
import subprocess
import tempfile
import shutil
import json
import asyncio
from pathlib import Path
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import edge_tts
from PIL import Image, ImageDraw, ImageFont

# ============================================================
#  FFmpeg Path Resolution
# ============================================================
def get_ffmpeg_path():
    """Get FFmpeg path, preferring bundled version for .exe distribution."""
    if getattr(sys, 'frozen', False):
        bundle_dir = sys._MEIPASS
        ffmpeg_exe = os.path.join(bundle_dir, 'ffmpeg', 'bin', 'ffmpeg.exe')
        if os.path.exists(ffmpeg_exe):
            return ffmpeg_exe
    return 'ffmpeg'

def get_ffprobe_path():
    """Get FFprobe path, preferring bundled version for .exe distribution."""
    if getattr(sys, 'frozen', False):
        bundle_dir = sys._MEIPASS
        ffprobe_exe = os.path.join(bundle_dir, 'ffmpeg', 'bin', 'ffprobe.exe')
        if os.path.exists(ffprobe_exe):
            return ffprobe_exe
    return 'ffprobe'

FFMPEG_PATH = get_ffmpeg_path()
FFPROBE_PATH = get_ffprobe_path()

# ============================================================
#  GPU Encoder Detection
# ============================================================
ENCODER_NAMES = {
    "h264_nvenc": "NVIDIA NVENC (Aceleração por Hardware)",
    "h264_amf": "AMD AMF (Aceleração por Hardware)",
    "h264_qsv": "Intel QSV (Aceleração por Hardware)",
    "h264_mf": "Windows Media Foundation (Aceleração por Hardware)",
    "libx264": "CPU / libx264 (Sem Aceleração)",
}

BEST_ENCODER = None

def get_best_h264_encoder():
    global BEST_ENCODER
    if BEST_ENCODER is not None:
        return BEST_ENCODER

    # Check if we're in a cloud environment (Render, etc.) - skip GPU detection
    # Cloud environments typically don't have GPU access
    cloud_indicators = ['RENDER', 'HEROKU', 'AWS', 'GCP', 'AZURE']
    for indicator in cloud_indicators:
        if indicator in os.environ:
            print(f"Cloud environment detected ({indicator}), using CPU encoder")
            BEST_ENCODER = "libx264"
            return BEST_ENCODER

    encoders = ["h264_nvenc", "h264_amf", "h264_qsv", "h264_mf", "libx264"]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for enc in encoders:
        if enc == "libx264":
            BEST_ENCODER = "libx264"
            return BEST_ENCODER
        try:
            cmd = [
                FFMPEG_PATH, "-y",
                "-f", "lavfi", "-i", "color=c=black:s=64x64",
                "-frames:v", "1",
                "-c:v", enc,
                "-f", "null", "-"
            ]
            proc = subprocess.run(cmd, capture_output=True, creationflags=flags, timeout=10)
            if proc.returncode == 0:
                BEST_ENCODER = enc
                return BEST_ENCODER
        except Exception:
            pass
    BEST_ENCODER = "libx264"
    return BEST_ENCODER

# ============================================================
#  Reddit Card Generator
# ============================================================
def wrap_text(text, font, max_width):
    """Helper to wrap text to fit within a specific pixel width."""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = font.getbbox(test_line)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def _get_assets_dir():
    """Get the assets directory, handling both development and PyInstaller bundle."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'BADGES')
    
    # Try multiple possible locations for BADGES folder
    possible_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'BADGES'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'BADGES'),
        'BADGES',
        './BADGES'
    ]
    
    for path in possible_paths:
        if os.path.isdir(path):
            return path
    
    # Fallback to original path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'BADGES')

def _load_badge_images(badge_size=36):
    """Load badge images from BADGES/ directory and resize them."""
    badges_dir = _get_assets_dir()
    
    # First check if directory exists
    if not os.path.isdir(badges_dir):
        print(f"Badges directory not found: {badges_dir}")
        return []
    
    badge_files = [
        'Captura_de_ecrã_2026-07-05_213146-removebg-preview.png',
        'Captura_de_ecrã_2026-07-05_213152-removebg-preview.png',
        'Captura_de_ecrã_2026-07-05_213201-removebg-preview.png',
        'Captura_de_ecrã_2026-07-05_213209-removebg-preview.png',
        'Captura_de_ecrã_2026-07-05_213221-removebg-preview.png',
    ]
    loaded = []
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS

    for fname in badge_files:
        fpath = os.path.join(badges_dir, fname)
        if os.path.isfile(fpath):
            try:
                badge = Image.open(fpath).convert("RGBA")
                badge = badge.resize((badge_size, badge_size), resample)
                loaded.append(badge)
                print(f"Loaded badge: {fname}")
            except Exception as e:
                print(f"Error loading badge {fname}: {e}")
        else:
            print(f"Badge file not found: {fpath}")
    
    if not loaded:
        print(f"No badges loaded from {badges_dir}")
    
    return loaded

def _draw_smooth_shadow(base_img, rect, radius, shadow_color=(0, 0, 0, 40), offset=(0, 6), blur_passes=5):
    """Draw a multi-pass soft shadow behind a rounded rectangle for a smooth look."""
    sx, sy, sw, sh = rect
    shadow = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i in range(blur_passes, 0, -1):
        expand = i * 3
        alpha = shadow_color[3] // (i + 1)
        sd.rounded_rectangle(
            [sx - expand + offset[0], sy - expand + offset[1],
             sw + expand + offset[0], sh + expand + offset[1]],
            radius=radius + expand,
            fill=(shadow_color[0], shadow_color[1], shadow_color[2], alpha)
        )
    base_img.paste(Image.alpha_composite(Image.new("RGBA", base_img.size, (0, 0, 0, 0)), shadow), (0, 0), shadow)

def create_reddit_card(author_name, intro_text, output_path, avatar_path=None):
    """Generate a Reddit post card PNG image."""
    SCALE = 1  # Reduced from 2 to 1 for faster processing

    # Try multiple font options for better compatibility
    font_author = None
    font_text = None
    font_small = None
    
    font_options = [
        "arialbd.ttf", "Arial Bold.ttf", "arialbd", "Arial",
        "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Windows/Fonts/arialbd.ttf"
    ]
    
    for font_name in font_options:
        try:
            font_author = ImageFont.truetype(font_name, 36 * SCALE)
            font_text = ImageFont.truetype(font_name, 38 * SCALE)
            break
        except (IOError, OSError):
            continue
    
    font_options_small = [
        "arial.ttf", "Arial.ttf", "arial", "Arial",
        "DejaVuSans.ttf", "LiberationSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Windows/Fonts/arial.ttf"
    ]
    
    for font_name in font_options_small:
        try:
            font_small = ImageFont.truetype(font_name, 24 * SCALE)
            break
        except (IOError, OSError):
            continue
    
    # Fallback to default font if none found
    if font_author is None:
        font_author = ImageFont.load_default()
    if font_text is None:
        font_text = ImageFont.load_default()
    if font_small is None:
        font_small = ImageFont.load_default()

    try:
        resample_filter = Image.Resampling.LANCZOS
    except AttributeError:
        resample_filter = Image.LANCZOS

    card_w = 960 * SCALE
    pad = 40 * SCALE
    max_text_w = card_w - pad * 2

    wrapped = wrap_text(intro_text, font_text, max_text_w)
    line_h = 44 * SCALE
    line_gap = 8 * SCALE
    text_block_h = len(wrapped) * line_h + max(0, len(wrapped) - 1) * line_gap

    avatar_size = 100 * SCALE
    top_pad = 36 * SCALE
    avatar_name_gap = 16 * SCALE
    badge_size = 54 * SCALE
    badge_text_gap = 36 * SCALE
    text_bottom_gap = 24 * SCALE
    bottom_bar_h = 50 * SCALE
    bot_pad = 28 * SCALE

    card_h = (top_pad + avatar_size + badge_text_gap + text_block_h + 
              text_bottom_gap + bottom_bar_h + bot_pad)

    shadow_m = 12 * SCALE
    canvas_w = card_w + shadow_m * 2
    canvas_h = card_h + shadow_m * 2

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    ox, oy = shadow_m, shadow_m

    _draw_smooth_shadow(img, (ox, oy, ox + card_w, oy + card_h),
                        radius=24 * SCALE,
                        shadow_color=(0, 0, 0, 35),
                        offset=(0, 4 * SCALE),
                        blur_passes=5)

    corner_r = 24 * SCALE
    draw.rounded_rectangle([ox, oy, ox + card_w, oy + card_h],
                           radius=corner_r, 
                           fill=(255, 255, 255, 255),
                           outline=(210, 210, 210, 255),
                           width=2 * SCALE)

    # Avatar
    avatar_x = ox + pad
    avatar_y = oy + top_pad

    avatar_loaded = False
    if avatar_path and os.path.isfile(avatar_path):
        try:
            av = Image.open(avatar_path).convert("RGBA")
            w, h = av.size
            mn = min(w, h)
            left = (w - mn) // 2
            top_ = (h - mn) // 2
            av = av.crop((left, top_, left + mn, top_ + mn))
            av = av.resize((avatar_size, avatar_size), resample_filter)

            mask = Image.new("L", (avatar_size, avatar_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
            img.paste(av, (avatar_x, avatar_y), mask)
            avatar_loaded = True
        except Exception as e:
            print(f"Error loading custom avatar: {e}")

    if not avatar_loaded:
        draw.ellipse([avatar_x, avatar_y,
                      avatar_x + avatar_size, avatar_y + avatar_size],
                     fill=(139, 92, 246, 255))
        cx_av = avatar_x + avatar_size // 2
        cy_av = avatar_y + avatar_size // 2
        s = SCALE
        fw, fh = 40 * s, 28 * s
        draw.rounded_rectangle([cx_av - fw // 2, cy_av,
                                cx_av + fw // 2, cy_av + fh],
                               radius=12 * s, fill=(255, 255, 255, 255))
        er = 5 * s
        draw.ellipse([cx_av - 14*s, cy_av + 8*s, cx_av - 14*s + er*2, cy_av + 8*s + er*2],
                     fill=(255, 87, 0, 255))
        draw.ellipse([cx_av + 4*s, cy_av + 8*s, cx_av + 4*s + er*2, cy_av + 8*s + er*2],
                     fill=(255, 87, 0, 255))
        draw.arc([cx_av - 6*s, cy_av + 16*s, cx_av + 6*s, cy_av + 24*s],
                 start=0, end=180, fill=(0, 0, 0, 255), width=2*s)
        draw.line([cx_av, cy_av, cx_av, cy_av - 16*s],
                  fill=(255, 255, 255, 255), width=3*s)
        draw.ellipse([cx_av - 5*s, cy_av - 22*s, cx_av + 5*s, cy_av - 12*s],
                     fill=(255, 255, 255, 255))

    draw = ImageDraw.Draw(img)

    # Username + Verified Badge
    name_x = avatar_x + avatar_size + avatar_name_gap
    name_y = avatar_y + 4 * SCALE
    draw.text((name_x, name_y), author_name, fill=(26, 26, 27, 255), font=font_author)

    name_bbox = font_author.getbbox(author_name)
    name_w = name_bbox[2] - name_bbox[0]

    vb_size = 32 * SCALE
    vb_x = name_x + name_w + 16 * SCALE
    vb_y = name_y + (36 * SCALE - vb_size) // 2
    draw.ellipse([vb_x, vb_y, vb_x + vb_size, vb_y + vb_size],
                 fill=(29, 155, 240, 255))
    ck = SCALE
    draw.line([vb_x + 8*ck, vb_y + 16*ck, vb_x + 13*ck, vb_y + 21*ck],
              fill=(255, 255, 255, 255), width=int(3.5 * ck))
    draw.line([vb_x + 13*ck, vb_y + 21*ck, vb_x + 23*ck, vb_y + 11*ck],
              fill=(255, 255, 255, 255), width=int(3.5 * ck))

    # Badge Row
    badge_row_y = avatar_y + 54 * SCALE
    badge_s = badge_size
    badges = _load_badge_images(badge_s)

    if badges:
        bx = name_x
        for badge_img in badges:
            img.paste(badge_img, (bx, badge_row_y), badge_img)
            bx += badge_s + 12 * SCALE
    else:
        colors = [(156, 163, 175), (245, 200, 60), (239, 68, 68), (59, 200, 246)]
        bx = name_x
        for c in colors:
            draw.ellipse([bx, badge_row_y, bx + badge_s, badge_row_y + badge_s], fill=c)
            bx += badge_s + 12 * SCALE

    draw = ImageDraw.Draw(img)

    # Post Text
    text_y = avatar_y + avatar_size + badge_text_gap
    for idx, line in enumerate(wrapped):
        ly = text_y + idx * (line_h + line_gap)
        draw.text((ox + pad, ly), line, fill=(26, 26, 27, 255), font=font_text)

    # Divider
    div_y = text_y + text_block_h + text_bottom_gap
    draw.line([(ox + pad, div_y), (ox + card_w - pad, div_y)],
              fill=(235, 235, 235, 255), width=1 * SCALE)

    # Bottom Action Bar
    bar_y = div_y + 10 * SCALE
    ic = 20 * SCALE
    gray = (135, 138, 140, 255)
    lw = 2 * SCALE

    bx = ox + pad

    # Heart
    hy = bar_y + (bottom_bar_h - ic) // 2
    draw.arc([bx, hy, bx + ic // 2, hy + ic // 2], start=135, end=315, fill=gray, width=lw)
    draw.arc([bx + ic // 2, hy, bx + ic, hy + ic // 2], start=225, end=405, fill=gray, width=lw)
    draw.line([bx + 1, hy + ic // 3, bx + ic // 2, hy + ic - 2], fill=gray, width=lw)
    draw.line([bx + ic - 1, hy + ic // 3, bx + ic // 2, hy + ic - 2], fill=gray, width=lw)
    bx += ic + 6 * SCALE
    draw.text((bx, bar_y + (bottom_bar_h - 24 * SCALE) // 2), "99+", fill=gray, font=font_small)
    bx += font_small.getbbox("99+")[2] + 32 * SCALE

    # Comment bubble
    cy_c = bar_y + (bottom_bar_h - ic) // 2
    draw.rounded_rectangle([bx, cy_c, bx + ic, cy_c + ic - 4*SCALE],
                           radius=4 * SCALE, outline=gray, width=lw)
    draw.polygon([(bx + 4*SCALE, cy_c + ic - 4*SCALE),
                  (bx + 4*SCALE, cy_c + ic),
                  (bx + 10*SCALE, cy_c + ic - 4*SCALE)], fill=gray)
    bx += ic + 6 * SCALE
    draw.text((bx, bar_y + (bottom_bar_h - 24 * SCALE) // 2), "99+", fill=gray, font=font_small)
    bx += font_small.getbbox("99+")[2] + 32 * SCALE

    # Share arrow
    sy_c = bar_y + (bottom_bar_h - ic) // 2
    mid = sy_c + ic // 2
    draw.line([bx + 2*SCALE, mid, bx + ic - 2*SCALE, mid], fill=gray, width=lw)
    draw.line([bx + ic // 2, sy_c + 2*SCALE, bx + ic - 2*SCALE, mid], fill=gray, width=lw)
    draw.line([bx + ic // 2, sy_c + ic - 2*SCALE, bx + ic - 2*SCALE, mid], fill=gray, width=lw)
    bx += ic + 6 * SCALE
    draw.text((bx, bar_y + (bottom_bar_h - 24 * SCALE) // 2), "Share", fill=gray, font=font_small)

    # Downscale
    final_w = canvas_w // SCALE
    final_h = canvas_h // SCALE
    img = img.resize((final_w, final_h), resample_filter)

    img.save(output_path, "PNG")

# ============================================================
#  TTS Engine
# ============================================================
class TTSEngine:
    """Generates TTS audio and synchronized ASS subtitles."""

    VOICES = {
        "male": "pt-BR-AntonioNeural",
        "female": "pt-BR-FranciscaNeural",
    }

    async def generate(self, text_intro, text_body, voice_type, output_dir, config, progress_cb=None):
        """Generate MP3 audio + ASS subtitle file."""
        voice = self.VOICES[voice_type]
        audio_path = os.path.join(output_dir, "tts_audio.mp3")
        ass_path = os.path.join(output_dir, "tts_subs.ass")

        if progress_cb:
            progress_cb("🎙️ A gerar áudio TTS...", 10)

        if text_intro and text_body:
            full_text = f"{text_intro}. {text_body}"
        elif text_intro:
            full_text = text_intro
        else:
            full_text = text_body

        voice_rate = config.get("voice_rate", "+60%")
        communicate = edge_tts.Communicate(full_text, voice, rate=voice_rate, boundary="WordBoundary")
        words = []

        with open(audio_path, "wb") as fp:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    fp.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append({
                        "text": chunk["text"],
                        "start": chunk["offset"] / 10_000_000,
                        "end": (chunk["offset"] + chunk["duration"]) / 10_000_000
                    })

        if progress_cb:
            progress_cb("📝 A gerar legendas sincronizadas...", 25)

        intro_word_count = len(text_intro.split()) if text_intro else 0
        
        if intro_word_count > 0 and intro_word_count < len(words):
            intro_duration = words[intro_word_count]["start"]
        elif intro_word_count > 0 and len(words) >= intro_word_count:
            intro_duration = words[intro_word_count - 1]["end"]
        else:
            intro_duration = 0.0

        body_words = words[intro_word_count:] if intro_word_count < len(words) else []

        words_per_cue = config.get("words_per_cue", 3)
        font_size = config.get("font_size", 75)
        active_color = config.get("active_color", "&H0000F2FF")
        position_y = config.get("position_y", 960)

        ass_content = self._build_ass(
            body_words,
            words_per_cue=words_per_cue,
            font_size=font_size,
            active_color=active_color,
            position_y=position_y
        )
        with open(ass_path, "w", encoding="utf-8") as fp:
            fp.write(ass_content)

        return audio_path, ass_path, intro_duration

    @staticmethod
    def _format_ass_ts(seconds):
        """Convert seconds → ASS timestamp H:MM:SS.cs"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int(round((seconds % 1) * 100))
        if cs == 100:
            s += 1
            cs = 0
            if s == 60:
                m += 1
                s = 0
                if m == 60:
                    h += 1
                    m = 0
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def _build_ass(self, words, words_per_cue=3, font_name="Arial Black", font_size=75, active_color="&H0000F2FF", default_color="&H00FFFFFF", outline_color="&H00000000", position_y=960):
        """Build ASS subtitle file content with active word highlighting and scale animation."""
        if not words:
            return ""

        ass_lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{font_name},{font_size},{default_color},&H0000FFFF,{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,5,0,5,10,10,10,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        groups = []
        for i in range(0, len(words), words_per_cue):
            groups.append(words[i : i + words_per_cue])

        for group in groups:
            g_start = group[0]["start"]
            g_end = group[-1]["end"]

            for idx, active_word in enumerate(group):
                start_time = active_word["start"]
                if idx == len(group) - 1:
                    end_time = g_end
                else:
                    end_time = group[idx + 1]["start"]

                start_str = self._format_ass_ts(start_time)
                end_str = self._format_ass_ts(end_time)

                text_parts = []
                for w_idx, w in enumerate(group):
                    w_text = w["text"].upper()
                    if w_idx == idx:
                        if active_color:
                            text_parts.append(f"{{\\c{active_color}\\fscx125\\fscy125\\t(0,120,\\fscx100\\fscy100)}}{w_text}{{\\r}}")
                        else:
                            text_parts.append(f"{{\\fscx125\\fscy125\\t(0,120,\\fscx100\\fscy100)}}{w_text}{{\\r}}")
                    else:
                        text_parts.append(w_text)

                line_text = " ".join(text_parts)
                dialogue_line = f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\an5\\pos(540,{position_y})}}{line_text}"
                ass_lines.append(dialogue_line)

        return "\n".join(ass_lines)

# ============================================================
#  Video Processor
# ============================================================
class VideoProcessor:
    """Builds a 1080×1920 vertical video with burned-in ASS subtitles and card overlays."""

    W, H = 1080, 1920

    def __init__(self):
        self._assert_ffmpeg()

    def process(self, video_path, audio_path, ass_path, card_path, intro_duration, output_path, config, progress_cb=None):
        """Render final vertical video."""
        if progress_cb:
            progress_cb("📐 A preparar vídeo...", 35)

        duration = self._probe_duration(audio_path)
        fps_str = self._probe_video_fps(video_path)
        
        # Very aggressive duration limit for cloud environments
        max_duration = 90  # 1.5 minutes max
        if duration > max_duration:
            duration = max_duration
            if progress_cb:
                progress_cb(f"⚠️ Duração limitada a {max_duration}s para processamento", 40)

        ass_dir = os.path.dirname(ass_path)
        ass_filename = os.path.basename(ass_path)

        if card_path and os.path.isfile(card_path) and intro_duration > 0:
            anim_type = config.get("anim_type", "Deslizar para Baixo")
            d_trans = min(0.5, intro_duration / 2.0)
            t_start = intro_duration - d_trans

            t1 = 0
            t2 = 0.2
            t3 = 0.25

            x_val = f"(t*5)"
            scale1 = f"1.05*(1-(1-{x_val})*(1-{x_val}))"

            y_val = f"((t-0.2)*20)"
            scale2 = f"(1.05-0.05*(3*{y_val}*{y_val}-2*{y_val}*{y_val}*{y_val}))"

            expr = f"if(lt(t,0),0.01,if(lt(t,0.2),{scale1},if(lt(t,0.25),{scale2},1)))"
            pop_scale = f"scale='iw*{expr}':'ih*{expr}':eval=frame"

            x_expr = "(W-w)/2"
            y_expr = "(H-h)/2"
            pre_filters = f"[2:v]{pop_scale}[card_popped];"
            card_input = "[card_popped]"

            if anim_type == "Deslizar para Baixo":
                y_expr = f"if(gte(t,{t_start}), (H-h)/2 + (H - (H-h)/2) * ((t-{t_start})/{d_trans}) * ((t-{t_start})/{d_trans}), (H-h)/2)"
            elif anim_type == "Deslizar para Cima":
                y_expr = f"if(gte(t,{t_start}), (H-h)/2 - ((H-h)/2 + h) * ((t-{t_start})/{d_trans}) * ((t-{t_start})/{d_trans}), (H-h)/2)"
            elif anim_type == "Deslizar para a Esquerda":
                x_expr = f"if(gte(t,{t_start}), (W-w)/2 - ((W-w)/2 + h) * ((t-{t_start})/{d_trans}) * ((t-{t_start})/{d_trans}), (W-w)/2)"
            elif anim_type == "Deslizar para a Direita":
                x_expr = f"if(gte(t,{t_start}), (W-w)/2 + (W - (W-w)/2) * ((t-{t_start})/{d_trans}) * ((t-{t_start})/{d_trans}), (W-w)/2)"
            elif anim_type == "Desaparecer (Fade Out)":
                pre_filters += f"[card_popped]fade=t=out:st={t_start}:d={d_trans}:alpha=1[card_faded];"
                card_input = "[card_faded]"

            vf = (
                f"[0:v]scale={self.W}:{self.H}:force_original_aspect_ratio=increase,"
                f"crop={self.W}:{self.H}[bg];"
                f"{pre_filters}"
                f"[bg]{card_input}overlay=x='{x_expr}':y='{y_expr}':enable='between(t,0,{intro_duration})'[over];"
                f"[over]subtitles='{ass_filename}'[outv]"
            )
            inputs = [
                "-i", video_path,
                "-i", audio_path,
                "-framerate", fps_str,
                "-loop", "1",
                "-i", card_path,
            ]
            filter_args = ["-filter_complex", vf, "-map", "[outv]", "-map", "1:a:0"]
        else:
            vf = (
                f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase,"
                f"crop={self.W}:{self.H},"
                f"subtitles='{ass_filename}'"
            )
            inputs = [
                "-i", video_path,
                "-i", audio_path,
            ]
            filter_args = ["-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]

        encoder = "libx264"
        # Maximum speed settings for cloud
        enc_args = ["-preset", "ultrafast", "-crf", "40", "-tune", "fastdecode", "-threads", "4"]

        # Disable GPU on cloud environments for stability
        if config.get("use_gpu", True):
            detected = get_best_h264_encoder()
            if detected != "libx264":
                encoder = detected
                if encoder == "h264_nvenc":
                    enc_args = ["-rc", "vbr", "-cq", "40", "-preset", "p1", "-threads", "4"]
                elif encoder == "h264_amf":
                    enc_args = ["-rc", "cqp", "-qp_i", "40", "-qp_p", "40", "-threads", "4"]
                elif encoder == "h264_qsv":
                    enc_args = ["-global_quality", "40", "-threads", "4"]
                elif encoder == "h264_mf":
                    enc_args = ["-threads", "4"]

        cmd = [
            FFMPEG_PATH, "-y",
            "-stream_loop", "-1",
        ] + inputs + filter_args + [
            "-t", str(duration),
            "-c:v", encoder,
        ] + enc_args + [
            "-c:a", "aac",
            "-b:a", "128k",  # Reduced audio bitrate for speed
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        if progress_cb:
            progress_cb(f"🎬 A renderizar vídeo final ({encoder.replace('h264_', '').upper()})...", 55)

        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=flags,
            cwd=ass_dir
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg falhou (código {proc.returncode}):\n{proc.stderr[-1500:]}"
            )

        if progress_cb:
            progress_cb("✅ Vídeo criado com sucesso!", 100)

        return output_path

    @staticmethod
    def _assert_ffmpeg():
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            subprocess.run(
                [FFMPEG_PATH, "-version"],
                capture_output=True,
                creationflags=flags,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Erro interno: FFmpeg não foi encontrado.\n\n"
                "O programa pode estar corrompido.\n"
                "Tenta descarregar novamente."
            )

    @staticmethod
    def _probe_duration(path):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            [
                FFPROBE_PATH, "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                path,
            ],
            capture_output=True, text=True, creationflags=flags,
        )
        return float(json.loads(result.stdout)["format"]["duration"])

    @staticmethod
    def _probe_video_fps(path):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                [
                    FFPROBE_PATH, "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams",
                    path,
                ],
                capture_output=True, text=True, creationflags=flags,
            )
            data = json.loads(result.stdout)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    r_frame_rate = stream.get("r_frame_rate")
                    if r_frame_rate and r_frame_rate != "0/0":
                        return r_frame_rate
        except Exception:
            pass
        return "30"

# ============================================================
#  Flask Application
# ============================================================
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

@app.route('/api/detect-gpu', methods=['GET'])
def detect_gpu():
    """Detect the best available GPU encoder."""
    try:
        encoder = get_best_h264_encoder()
        return jsonify({'encoder': encoder})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate', methods=['POST'])
def generate_video():
    """Generate TikTok video with TTS, subtitles, and overlays."""
    import time
    start_time = time.time()
    
    try:
        # Check for required files
        if 'video' not in request.files:
            return jsonify({'error': 'Nenhum vídeo enviado'}), 400
        
        video_file = request.files['video']
        if video_file.filename == '':
            return jsonify({'error': 'Nenhum vídeo selecionado'}), 400
        
        # Get form data
        author = request.form.get('author', 'Respira Reddit')
        intro = request.form.get('intro', '')
        body = request.form.get('body', '')
        voice_type = request.form.get('voice_type', 'male')
        words_per_cue = int(request.form.get('words_per_cue', 2))
        active_color = request.form.get('active_color', '&H0000F2FF')
        font_size = int(request.form.get('font_size', 116))
        position_y = int(request.form.get('position_y', 960))
        use_gpu = request.form.get('use_gpu', 'true').lower() == 'true'
        anim_type = request.form.get('anim_type', 'Deslizar para Baixo')
        voice_rate = request.form.get('voice_rate', '+60%')
        
        print(f"[DEBUG] Starting video generation - Intro: {len(intro)} chars, Body: {len(body)} chars")
        
        # Handle avatar file
        avatar_path = None
        if 'avatar' in request.files and request.files['avatar'].filename:
            avatar_file = request.files['avatar']
            avatar_path = os.path.join(tempfile.gettempdir(), secure_filename(avatar_file.filename))
            avatar_file.save(avatar_path)
            print(f"[DEBUG] Avatar saved to: {avatar_path}")
        
        # Create temporary directory for processing
        tmp_dir = tempfile.mkdtemp(prefix="tiktok_creator_")
        print(f"[DEBUG] Temp directory: {tmp_dir}")
        
        # Save video file
        video_path = os.path.join(tmp_dir, secure_filename(video_file.filename))
        video_file.save(video_path)
        print(f"[DEBUG] Video saved to: {video_path}")
        
        # Progress callback (we'll use a simple list to track progress)
        progress = [0]
        
        def progress_cb(msg, val):
            progress[0] = val
            print(f"[DEBUG] Progress: {msg} ({val}%)")
        
        # Generate card if intro text exists
        card_path = None
        if intro:
            card_start = time.time()
            card_path = os.path.join(tmp_dir, "reddit_card.png")
            create_reddit_card(author, intro, card_path, avatar_path=avatar_path)
            print(f"[DEBUG] Card generated in {time.time() - card_start:.2f}s")
        
        # Generate TTS and subtitles
        tts_start = time.time()
        tts = TTSEngine()
        audio_path, ass_path, intro_duration = asyncio.run(
            tts.generate(intro, body, voice_type, tmp_dir, {
                'voice_rate': voice_rate,
                'words_per_cue': words_per_cue,
                'font_size': font_size,
                'active_color': active_color if active_color else None,
                'position_y': position_y
            }, progress_cb)
        )
        print(f"[DEBUG] TTS generated in {time.time() - tts_start:.2f}s, intro_duration: {intro_duration}")
        
        # Process video
        video_start = time.time()
        output_path = os.path.join(tmp_dir, "output.mp4")
        proc = VideoProcessor()
        proc.process(video_path, audio_path, ass_path, card_path, intro_duration, output_path, {
            'use_gpu': use_gpu,
            'anim_type': anim_type
        }, progress_cb)
        print(f"[DEBUG] Video processed in {time.time() - video_start:.2f}s")
        
        total_time = time.time() - start_time
        print(f"[DEBUG] Total generation time: {total_time:.2f}s")
        
        # Send the file
        return send_file(output_path, as_attachment=True, download_name='tiktok_video.mp4')
        
    except Exception as e:
        print(f"[ERROR] Generation failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        # Cleanup temporary directory
        if 'tmp_dir' in locals():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if avatar_path and os.path.exists(avatar_path):
            os.remove(avatar_path)

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/styles.css')
def styles():
    return send_file('styles.css')

@app.route('/script.js')
def script():
    return send_file('script.js')

@app.route('/BADGES/<path:filename>')
def serve_badges(filename):
    return send_file(os.path.join('BADGES', filename))

if __name__ == '__main__':
    # Pre-flight check: verify FFmpeg is accessible
    try:
        VideoProcessor()
    except RuntimeError as e:
        print(f"Erro: {e}")
        sys.exit(1)
    
    # Get port from environment variable (Render uses PORT)
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    app.run(host='0.0.0.0', port=port, debug=debug)
