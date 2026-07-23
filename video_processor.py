import ffmpeg
import random
import os
import glob
from PIL import Image, ImageDraw, ImageFont
from config import logger

try:
    import emoji as emoji_lib
except ImportError:
    emoji_lib = None


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


# ---------------------------------------------------------------------------
# Emoji rendering (Noto Color Emoji is a bitmap font: it only rasterizes at
# specific strike sizes, so we render big once, cache, and resize down).
# ---------------------------------------------------------------------------

_EMOJI_BITMAP_CACHE = {}


def _render_emoji_image(char, target_size, emoji_font_path):
    """Render a single emoji as an RGBA image of target_size height. Returns None on failure."""
    if not emoji_font_path:
        return None

    key = (char, target_size)
    if key in _EMOJI_BITMAP_CACHE:
        return _EMOJI_BITMAP_CACHE[key]

    rendered = None
    # Noto Color Emoji strikes: 109 is the classic CBDT size; try alternates too.
    for strike in (109, 128, 136, 160, 96, 64, 32):
        try:
            f = ImageFont.truetype(emoji_font_path, strike)
            canvas_size = strike * 2
            tmp = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
            d = ImageDraw.Draw(tmp)
            d.text((strike // 2, strike // 2), char, font=f, embedded_color=True)
            bbox = tmp.getbbox()
            if bbox and (bbox[2] - bbox[0]) > 2 and (bbox[3] - bbox[1]) > 2:
                cropped = tmp.crop(bbox)
                # Scale to target height, preserve aspect ratio
                w, h = cropped.size
                new_h = target_size
                new_w = max(1, int(w * (new_h / h)))
                rendered = cropped.resize((new_w, new_h), Image.LANCZOS)
                break
        except Exception:
            continue

    _EMOJI_BITMAP_CACHE[key] = rendered
    if rendered is None:
        logger.warning(f"Could not render emoji: {char!r}")
    return rendered


def _split_segments(text):
    """Split a string into [('text', str) | ('emoji', str)] segments."""
    if not emoji_lib:
        return [("text", text)] if text else []
    segments = []
    last = 0
    for match in emoji_lib.emoji_list(text):
        start, end = match["match_start"], match["match_end"]
        if start > last:
            segments.append(("text", text[last:start]))
        segments.append(("emoji", match["emoji"]))
        last = end
    if last < len(text):
        segments.append(("text", text[last:]))
    return segments


def _segments_width(draw, font, segments, emoji_size, emoji_pad):
    """Measure the pixel width of a list of segments."""
    total = 0
    for kind, content in segments:
        if kind == "text":
            total += draw.textlength(content, font=font)
        else:
            total += emoji_size + emoji_pad * 2
    return total


def _wrap_words(draw, font, words, max_width, emoji_size, emoji_pad):
    """Greedy word wrap. Each word is a list of segments. Returns list of lines (list of segments)."""
    space_w = draw.textlength(" ", font=font)
    lines = []
    current = []
    current_w = 0

    for word_segs in words:
        word_w = _segments_width(draw, font, word_segs, emoji_size, emoji_pad)
        add_w = word_w + (space_w if current else 0)
        if current and current_w + add_w > max_width:
            lines.append(current)
            current = list(word_segs)
            current_w = word_w
        else:
            if current:
                current = current + [("text", " ")] + list(word_segs)
                current_w += add_w
            else:
                current = list(word_segs)
                current_w = word_w
    if current:
        lines.append(current)
    return lines


def _layout_text(draw, quote, width, height, font_path):
    """
    Smart layout: auto-shrinks the font until the whole quote fits nicely
    inside a safe zone (centered, away from edges).
    Returns (font, font_size, lines, line_height, emoji_size, emoji_pad).
    """
    max_text_width = int(width * 0.80)   # safe horizontal zone
    max_text_height = int(height * 0.55)  # safe vertical zone

    # Words as segment lists (preserving user line breaks)
    paragraphs = []
    for para in quote.split("\n"):
        words = [w for w in para.split(" ") if w]
        paragraphs.append([_split_segments(w) for w in words])

    # Length-aware starting size: short quotes get a moderate, clean size
    # (never huge), longer quotes start smaller. The shrink loop below still
    # guarantees everything fits in the safe zone.
    n_chars = len(quote.replace("\n", " ").strip())
    if n_chars <= 30:
        font_size = int(height * 0.048)   # ~92px on 1920
    elif n_chars <= 70:
        font_size = int(height * 0.042)   # ~80px
    elif n_chars <= 130:
        font_size = int(height * 0.036)   # ~69px
    else:
        font_size = int(height * 0.030)   # ~57px
    min_font_size = 26

    while True:
        try:
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            font = ImageFont.load_default()
        emoji_size = int(font_size * 1.0)
        emoji_pad = max(2, int(font_size * 0.06))

        lines = []
        for words in paragraphs:
            if not words:
                continue
            lines.extend(_wrap_words(draw, font, words, max_text_width, emoji_size, emoji_pad))

        line_height = int(font_size * 1.35)
        block_height = len(lines) * line_height
        widest = max(
            (_segments_width(draw, font, ln, emoji_size, emoji_pad) for ln in lines),
            default=0,
        )

        if (block_height <= max_text_height and widest <= max_text_width) or font_size <= min_font_size:
            return font, font_size, lines, line_height, emoji_size, emoji_pad

        font_size = max(min_font_size, int(font_size * 0.9))


def _create_text_overlay(quote, width, height, font_path, emoji_font_path):
    """
    Create a transparent PNG with the quote perfectly centered.
    - Each line is measured (text + emoji) and centered individually.
    - Emojis are rendered in full color from Noto Color Emoji.
    - Font auto-shrinks so long quotes never spill to the edges.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    quote = quote.strip()
    if not quote:
        return img

    font, font_size, lines, line_height, emoji_size, emoji_pad = _layout_text(
        draw, quote, width, height, font_path
    )
    logger.info(f"Text layout: font_size={font_size}, lines={len(lines)}")

    block_height = len(lines) * line_height
    y = (height - block_height) // 2

    shadow_offset = max(2, int(font_size * 0.04))
    stroke_w = max(1, int(font_size * 0.03))

    for line_segs in lines:
        line_w = _segments_width(draw, font, line_segs, emoji_size, emoji_pad)
        x = (width - line_w) / 2
        cy = y + line_height // 2  # vertical center of this line

        for kind, content in line_segs:
            if kind == "text":
                seg_w = draw.textlength(content, font=font)
                # Soft shadow
                draw.text(
                    (x + shadow_offset, cy + shadow_offset),
                    content, font=font, fill=(0, 0, 0, 150), anchor="lm",
                )
                # Main text with a thin dark stroke for crispness
                draw.text(
                    (x, cy),
                    content, font=font, fill=(255, 255, 255, 255), anchor="lm",
                    stroke_width=stroke_w, stroke_fill=(0, 0, 0, 120),
                )
                x += seg_w
            else:
                emoji_img = _render_emoji_image(content, emoji_size, emoji_font_path)
                x += emoji_pad
                if emoji_img is not None:
                    ex = int(x)
                    ey = int(cy - emoji_img.height / 2)
                    img.paste(emoji_img, (ex, ey), emoji_img)
                    x += emoji_img.width
                else:
                    # Fallback: draw as plain text (may show as box, but keeps spacing)
                    draw.text((x, cy), content, font=font, fill=(255, 255, 255, 255), anchor="lm")
                    x += draw.textlength(content, font=font)
                x += emoji_pad

        y += line_height

    return img


# Fixed reel canvas: guarantees the overlay and video always line up,
# regardless of source resolution or rotation metadata from phone videos.
REEL_WIDTH = 1080
REEL_HEIGHT = 1920


def process_video(input_path, output_path, quote):
    """
    Takes a raw video, extracts a random 15-second clip, normalizes it to a
    1080x1920 reel canvas (scale-to-cover + center crop), applies a subtle
    dark blur, and overlays styled text perfectly centered.
    Output is muted (no audio) for faster processing.
    """
    overlay_path = None
    try:
        # Get video duration
        probe = ffmpeg.probe(input_path)
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        duration = float(video_info.get('duration', probe['format'].get('duration', 0)))

        # 15 seconds clip
        clip_duration = min(15, duration)
        start_time = random.uniform(0, max(0, duration - clip_duration))

        # --- Find fonts: Bebas Neue (clean, condensed) for text, Noto Color Emoji for emojis ---
        font_path = _find_font("BebasNeue-Regular.ttf")
        if not font_path:
            font_path = _find_font("Montserrat-Bold.ttf")
        if not font_path:
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            logger.warning(f"Falling back to system font: {font_path}")

        emoji_font_path = _find_font("NotoColorEmoji.ttf")
        logger.info(f"Text font: {font_path} | Emoji font: {emoji_font_path}")

        # --- Create text overlay image with Pillow (always at reel size) ---
        overlay_img = _create_text_overlay(quote, REEL_WIDTH, REEL_HEIGHT, font_path, emoji_font_path)
        overlay_path = output_path.replace(".mp4", "_overlay.png")
        overlay_img.save(overlay_path)
        logger.info(f"Created text overlay: {overlay_path} ({REEL_WIDTH}x{REEL_HEIGHT})")

        # --- Build FFmpeg pipeline (video only, audio stripped) ---
        stream = ffmpeg.input(input_path, ss=start_time, t=clip_duration)
        overlay_input = ffmpeg.input(overlay_path)

        v = stream.video

        # Normalize to the reel canvas: scale to cover, then center-crop.
        # FFmpeg applies rotation metadata before filters, so this is
        # correct even for rotated phone videos.
        v = v.filter('scale', w=REEL_WIDTH, h=REEL_HEIGHT,
                     force_original_aspect_ratio='increase')
        v = v.filter('crop', REEL_WIDTH, REEL_HEIGHT,
                     f'(iw-{REEL_WIDTH})/2', f'(ih-{REEL_HEIGHT})/2')
        v = v.filter('setsar', 1)

        # Subtle darken and gentle blur
        v = v.filter('eq', brightness=-0.15)
        v = v.filter('gblur', sigma=4)

        # Overlay the text PNG, centered on the canvas (exact match in size)
        v = ffmpeg.overlay(v, overlay_input, x='(W-w)/2', y='(H-h)/2')

        # No audio: faster encode, smaller file
        out = ffmpeg.output(
            v, output_path,
            vcodec='libx264', preset='fast', crf=23,
            pix_fmt='yuv420p', movflags='+faststart',
            an=None,
        )

        logger.info(f"Starting ffmpeg processing for {output_path} (muted)")
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
