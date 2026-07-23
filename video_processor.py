import ffmpeg
import random
import textwrap
import os
import re
import glob
from PIL import Image, ImageDraw, ImageFont
from config import logger


def _find_font(name):
    """Search for a font file everywhere reasonable."""
    import shutil
    import subprocess

    # 0. Check local cache first (from a previous run)
    cache_dir = "/tmp/_font_cache"
    cached = os.path.join(cache_dir, name)
    if os.path.exists(cached):
        logger.info(f"Found font in cache: {cached}")
        return cached

    # 1. Check common known locations
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = os.getcwd()
    candidates = [
        os.path.join(script_dir, "assets", "fonts", name),
        os.path.join(cwd, "assets", "fonts", name),
        f"/home/site/wwwroot/assets/fonts/{name}",
        f"/tmp/assets/fonts/{name}",
    ]
    for c in candidates:
        if os.path.exists(c):
            logger.info(f"Found font at: {c}")
            # Cache it
            os.makedirs(cache_dir, exist_ok=True)
            shutil.copy2(c, cached)
            return cached

    # 2. Use 'find' command to search the entire /home and /tmp trees
    try:
        result = subprocess.run(
            ["find", "/home", "/tmp", "-name", name, "-type", "f"],
            capture_output=True, text=True, timeout=10
        )
        paths = result.stdout.strip().split("\n")
        for p in paths:
            p = p.strip()
            if p and os.path.exists(p):
                logger.info(f"Found font via find command: {p}")
                os.makedirs(cache_dir, exist_ok=True)
                shutil.copy2(p, cached)
                return cached
    except Exception as e:
        logger.warning(f"find command failed: {e}")

    # 3. Search system fonts
    system_paths = glob.glob(f"/usr/share/fonts/**/{name}", recursive=True)
    if system_paths:
        logger.info(f"Found font in system: {system_paths[0]}")
        return system_paths[0]

    logger.warning(f"Font '{name}' not found anywhere")
    return None


def _create_text_overlay(quote, width, height, font_path):
    """
    Create a transparent PNG with the quote text centered.
    Uses Bebas Neue for a classy, modern look.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Scale font size relative to video height — Bebas Neue looks great large
    font_size = max(32, int(height / 14))
    try:
        font = ImageFont.truetype(font_path, font_size)
        logger.info(f"Loaded font '{font_path}' at size {font_size}")
    except Exception as e:
        logger.warning(f"Failed to load font '{font_path}': {e}, using default")
        font = ImageFont.load_default()

    # Wrap text to fit within ~75% of video width
    max_text_width = int(width * 0.75)
    words = quote.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        test_width = bbox[2] - bbox[0]
        if test_width <= max_text_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    wrapped_text = "\n".join(lines)
    line_spacing = int(font_size * 0.35)

    # Calculate text bounding box for centering
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=line_spacing)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (width - text_w) // 2
    y = (height - text_h) // 2

    # Draw soft shadow for depth
    shadow_offset = max(3, int(font_size * 0.05))
    draw.multiline_text(
        (x + shadow_offset, y + shadow_offset),
        wrapped_text, font=font,
        fill=(0, 0, 0, 160),
        align="center",
        spacing=line_spacing
    )

    # Thin outline for crispness
    outline_width = 2
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.multiline_text(
                (x + dx, y + dy),
                wrapped_text, font=font,
                fill=(0, 0, 0, 100),
                align="center",
                spacing=line_spacing
            )

    # Main text — clean white
    draw.multiline_text(
        (x, y),
        wrapped_text, font=font,
        fill=(255, 255, 255, 255),
        align="center",
        spacing=line_spacing
    )

    return img


def process_video(input_path, output_path, quote):
    """
    Takes a raw video, extracts a random 15-second clip,
    applies a subtle dark blur, and overlays styled text.
    """
    overlay_path = None
    try:
        # Log working directory and script location for debugging
        logger.info(f"CWD: {os.getcwd()}")
        logger.info(f"Script dir: {os.path.dirname(os.path.abspath(__file__))}")

        # Get video duration and dimensions
        probe = ffmpeg.probe(input_path)
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        duration = float(video_info.get('duration', probe['format'].get('duration', 0)))
        vid_width = int(video_info['width'])
        vid_height = int(video_info['height'])

        # Check if the video has an audio stream
        has_audio = any(s['codec_type'] == 'audio' for s in probe['streams'])

        # 15 seconds clip
        clip_duration = min(15, duration)
        start_time = random.uniform(0, max(0, duration - clip_duration))

        # --- Find Bebas Neue font ---
        font_path = _find_font("BebasNeue-Regular.ttf")
        if not font_path:
            # Try Montserrat as second choice
            font_path = _find_font("Montserrat-Bold.ttf")
        if not font_path:
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            logger.warning(f"Falling back to system font: {font_path}")

        logger.info(f"Final font choice: {font_path}")

        # List what's in the assets directory for debugging
        for search_dir in [os.getcwd(), os.path.dirname(os.path.abspath(__file__)), "/home/site/wwwroot"]:
            assets_path = os.path.join(search_dir, "assets", "fonts")
            if os.path.isdir(assets_path):
                logger.info(f"Contents of {assets_path}: {os.listdir(assets_path)}")
            else:
                logger.info(f"Directory not found: {assets_path}")

        # --- Create text overlay image with Pillow ---
        overlay_img = _create_text_overlay(quote, vid_width, vid_height, font_path)
        overlay_path = output_path.replace(".mp4", "_overlay.png")
        overlay_img.save(overlay_path)
        logger.info(f"Created text overlay: {overlay_path} ({vid_width}x{vid_height})")

        # --- Build FFmpeg pipeline ---
        stream = ffmpeg.input(input_path, ss=start_time, t=clip_duration)
        overlay_input = ffmpeg.input(overlay_path)

        # Process video stream
        v = stream.video

        # Subtle darken and gentle blur
        v = v.filter('eq', brightness=-0.15)
        v = v.filter('gblur', sigma=4)

        # Overlay the text PNG on top of the blurred video
        v = ffmpeg.overlay(v, overlay_input, x=0, y=0)

        # Handle audio
        if has_audio:
            audio = stream.audio
            out = ffmpeg.output(
                v, audio, output_path,
                vcodec='libx264', preset='fast', crf=23,
                acodec='aac', strict='experimental'
            )
        else:
            silent_audio = ffmpeg.input(
                'anullsrc=r=44100:cl=stereo', f='lavfi', t=clip_duration
            )
            out = ffmpeg.output(
                v, silent_audio, output_path,
                vcodec='libx264', preset='fast', crf=23,
                acodec='aac', strict='experimental', shortest=None
            )

        logger.info(f"Starting ffmpeg processing for {output_path} (has_audio={has_audio})")
        ffmpeg.run(out, overwrite_output=True, capture_stdout=True, capture_stderr=True)
        logger.info(f"Finished processing {output_path}")
        return True

    except ffmpeg.Error as e:
        logger.error(f"FFmpeg error: {e.stderr.decode('utf8')}")
        return False
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    finally:
        # Clean up the temporary overlay image
        if overlay_path and os.path.exists(overlay_path):
            try:
                os.remove(overlay_path)
            except OSError:
                pass
