"""Card primitives and the one design all LenBot plugin cards share.

The design is the Bilibili card of astrbot_plugin_asoul: white paper with a thin pink strip along the top,
a faint pink glow in the top right corner and a warm fade at the bottom. Pink is an accent for names, pills
and thin marks, never a large fill; PINK_TEXT is its darker form for text under 18. Corners come in three
sizes: the card, RADIUS for blocks and pictures, and full pills. Only avatars and dots are round.

lenbot-plugin-asoul, lenbot-plugin-bilibili and lenbot-plugin-group-digest ship this file unchanged; edit
all three together. All sizes are logical pixels at 2x, half the CSS pixels of the original 1200-wide
template. Text goes through the font chain, so a symbol the main font lacks comes from the next font, and
one no font has is left out.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
import math
from pathlib import Path
from typing import Sequence
import unicodedata

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import regex

PINK = "#ff5f91"
PINK_TEXT = "#d6336c"
PINK_SOFT = "#fff0f5"
PINK_PALE = "#fff5f8"
PINK_LINE = "#ffe1eb"
PINK_DASH = "#f0d5df"
STRIP = ("#ff75a5", "#ff9fbd", "#ffd9e6")
QUOTE_BAR = ("#ff79a8", "#ffc1d5")
GLOW = (255, 105, 150)
PAPER_END = "#fff8fb"
INK = "#23232b"
INK_2 = "#50505a"
MUTED = "#6e6e78"
LABEL = "#8a6a76"
SIGNATURE = "#c4adb6"
LINE = "#eeeef2"
QUOTE_FILL = "#f8f7fa"
QUOTE_LINE = "#eceaf0"
PICTURE_FILL = "#f3f3f5"
LINK = "#1285bd"
SURFACE = "#ffffff"

S = 2
WIDTH = 600
PAD_X = 36
PAD_TOP = 34
PAD_BOTTOM = 26
STRIP_HEIGHT = 7
RADIUS_CARD = 34
RADIUS = 14
MAX_PNG_BYTES = 3_000_000
SUPERSAMPLE = 4

# Symbols and kaomoji the bundled font lacks; only fonts present on this machine are used.
FALLBACK_FONTS = ("/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                  "/System/Library/Fonts/Apple Symbols.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


def px(value: float) -> int:
    return round(value * S)


# ---------- color ----------

def rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def to_hex(value) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(round(channel) for channel in value))


def mix(color: str, other: str, amount: float) -> str:
    return to_hex(a + (b - a) * amount for a, b in zip(rgb(color), rgb(other)))


def tint(color: str, amount: float) -> str:
    return mix(color, SURFACE, amount)


def luminance(color: str) -> float:
    channels = [c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb(color)]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(color: str, other: str) -> float:
    high, low = sorted((luminance(color), luminance(other)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable(color: str, ratio: float = 4.5, on: str = SURFACE) -> str:
    """The color darkened in its own hue until it reaches the contrast ratio on the given background."""
    hue, light, saturation = colorsys.rgb_to_hls(*(c / 255 for c in rgb(color)))
    while light > 0.05 and contrast(color, on) < ratio:
        light -= 0.015
        color = to_hex(c * 255 for c in colorsys.hls_to_rgb(hue, light, saturation))
    return color


# ---------- fonts ----------

_NOTDEF_PROBE = "\U000F0000"   # Supplementary private use; no CJK font maps it.


@lru_cache(maxsize=None)
def _signature(font: ImageFont.FreeTypeFont, text: str) -> tuple:
    mask = font.getmask(text)
    return mask.size, bytes(mask)


@lru_cache(maxsize=65536)
def has_glyph(font: ImageFont.FreeTypeFont, char: str) -> bool:
    if char.isspace():
        return True
    return _signature(font, char) != _signature(font, _NOTDEF_PROBE)


@dataclass(frozen=True)
class Fonts:
    """A variable-weight main font followed by fallbacks for symbols it lacks.

    A static main font keeps its only weight and draws heavy text with a thin same-color stroke.
    """
    main: Path
    fallbacks: tuple[Path, ...] = ()
    index: int = 0

    @lru_cache(maxsize=256)
    def get(self, size: float, weight: int = 400) -> ImageFont.FreeTypeFont:
        font = ImageFont.truetype(str(self.main), px(size), index=self.index)
        try:
            font.set_variation_by_axes([weight])
        except OSError:
            pass
        return font

    @lru_cache(maxsize=1)
    def variable(self) -> bool:
        try:
            return bool(ImageFont.truetype(str(self.main), 12, index=self.index).get_variation_axes())
        except OSError:
            return False

    def stroke(self, style: Style) -> int:
        return 0 if self.variable() or style.wght < 600 else max(1, round(style.size * S * 0.03))

    @lru_cache(maxsize=256)
    def chain(self, size: float, weight: int = 400) -> tuple[ImageFont.FreeTypeFont, ...]:
        return (self.get(size, weight), *(ImageFont.truetype(str(path), px(size)) for path in self.fallbacks))

    def pick(self, cluster: str, size: float, weight: int = 400) -> ImageFont.FreeTypeFont | None:
        chain = self.chain(size, weight)
        base = next((c for c in cluster if not unicodedata.combining(c) and c not in "︎️‍"), cluster[:1])
        return next((font for font in chain if has_glyph(font, base)), None)


def load_fonts(main: Path, index: int = 0) -> Fonts:
    return Fonts(main, tuple(Path(path) for path in FALLBACK_FONTS if Path(path).is_file()), index)


def clusters(text: str) -> list[str]:
    return regex.findall(r"\X", text)


@dataclass(frozen=True)
class Style:
    size: float
    weight: int = 400
    color: str = INK

    @property
    def wght(self) -> int:
        return self.weight


def segments(fonts: Fonts, text: str, style: Style) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    out: list[tuple[str, ImageFont.FreeTypeFont]] = []
    for cluster in clusters(text):
        font = fonts.pick(cluster, style.size, style.wght)
        if font is None:
            continue
        if out and out[-1][1] is font:
            out[-1] = (out[-1][0] + cluster, font)
        else:
            out.append((cluster, font))
    return out


def measure(fonts: Fonts, text: str, style: Style) -> int:
    return round(sum(font.getlength(part) for part, font in segments(fonts, text, style)))


def draw_text(canvas: Image.Image, fonts: Fonts, x: float, y: float, text: str, style: Style,
              anchor: str = "lt", color: str | None = None) -> int:
    """Draw one line; anchor is horizontal l/m/r plus vertical t/m. Returns the right edge.

    Vertical placement uses the cap height of the main font, so "t" puts the top of the
    glyphs at y and "m" centres them on y, independent of the font's line gap.
    """
    cap = cap_height(fonts.get(style.size, style.wght))
    width = measure(fonts, text, style)
    left = x - width if anchor[0] == "r" else x - width / 2 if anchor[0] == "m" else x
    baseline = y + cap if anchor[1] == "t" else y + cap / 2
    draw = ImageDraw.Draw(canvas)
    fill = color or style.color
    stroke = fonts.stroke(style)
    cursor = left
    for part, font in segments(fonts, text, style):
        draw.text((cursor, baseline), part, font=font, fill=fill, anchor="ls", stroke_width=stroke, stroke_fill=fill)
        cursor += font.getlength(part)
    return round(left + width)


@lru_cache(maxsize=256)
def cap_height(font: ImageFont.FreeTypeFont) -> int:
    # Top of a CJK ideograph above the baseline; Latin capitals sit slightly lower.
    return -font.getbbox("国", anchor="ls")[1]


def wrap(fonts: Fonts, text: str, style: Style, width: int, max_lines: int | None = None) -> list[str]:
    lines = ["".join(unit[1] for unit in line) for line in layout(fonts, [Run(text)], style, width)]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and measure(fonts, last + "…", style) > width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def fit(fonts: Fonts, text: str, style: Style, width: int) -> str:
    return (wrap(fonts, text.replace("\n", " "), style, width, max_lines=1) or [""])[0]


# ---------- rich text with inline images (Bilibili emoji) ----------

@dataclass
class Run:
    text: str = ""
    image: Image.Image | None = None


class Line(list):
    """One laid-out line; soft means the text wrapped here rather than at a line break."""
    soft = False


NO_LINE_START = set("，。、；：？！）》」』】〉”’…～,.;:?!)]}")


def emoji_size(style: Style) -> int:
    return px(style.size * 1.35)


def layout(fonts: Fonts, runs: Sequence[Run], style: Style, width: int) -> list[Line]:
    """Lines of ('text', cluster, advance, font) and ('image', image, advance, None); CJK may break anywhere."""
    lines = [Line()]
    used = 0
    icon = emoji_size(style)
    for run in runs:
        if run.image is not None:
            units = [("image", run.image, icon + px(2), None)]
        else:
            units = []
            for cluster in clusters(run.text):
                if cluster in ("\n", "\r\n"):
                    units.append(("break", None, 0, None))
                    continue
                font = fonts.pick(cluster, style.size, style.wght)
                if font is not None:
                    units.append(("text", cluster, font.getlength(cluster), font))
        for unit in units:
            if unit[0] == "break":
                lines.append(Line())
                used = 0
                continue
            if used + unit[2] > width and lines[-1]:
                # Closing punctuation may not start a line; it takes the previous character down with it.
                carried = []
                if unit[0] == "text" and unit[1] in NO_LINE_START and len(lines[-1]) > 1 and lines[-1][-1][0] == "text":
                    carried = [lines[-1].pop()]
                lines[-1].soft = True
                lines.append(Line(carried))
                used = sum(item[2] for item in carried)
                if unit[0] == "text" and unit[1].isspace():
                    continue
            lines[-1].append(unit)
            used += unit[2]
    while len(lines) > 1 and not lines[-1]:
        lines.pop()
    return lines


def clip(fonts: Fonts, lines: list, style: Style, width: int, limit: int) -> list:
    """Keep at most ``limit`` lines; the last kept line ends with an ellipsis."""
    if len(lines) <= limit:
        return lines
    lines = [list(line) for line in lines[:limit]]
    ellipsis = measure(fonts, "…", style)
    last = lines[-1]
    while last and sum(unit[2] for unit in last) + ellipsis > width:
        last.pop()
    font = fonts.pick("…", style.size, style.wght)
    last.append(("text", "…", font.getlength("…"), font))
    return lines


def paragraph(fonts: Fonts, text: str, style: Style, width: int, limit: int) -> list:
    return clip(fonts, layout(fonts, [Run(text)], style, width), style, width, limit) if text.strip() else []


def line_height(style: Style, ratio: float = 1.7) -> int:
    return px(style.size * ratio)


def draw_lines(canvas: Image.Image, fonts: Fonts, lines, x: int, y: int, style: Style, ratio: float = 1.7,
               color: str | None = None) -> int:
    height = line_height(style, ratio)
    cap = cap_height(fonts.get(style.size, style.wght))
    icon = emoji_size(style)
    draw = ImageDraw.Draw(canvas)
    fill = color or style.color
    stroke = fonts.stroke(style)
    for line in lines:
        baseline = y + (height + cap) // 2
        cursor = x
        index = 0
        while index < len(line):
            kind, value, advance, font = line[index]
            if kind == "image":
                picture = value.convert("RGBA").resize((icon, icon), Image.Resampling.LANCZOS)
                canvas.alpha_composite(picture, (round(cursor + px(1)), y + (height - icon) // 2))
                cursor += advance
                index += 1
                continue
            text, start = "", cursor
            while index < len(line) and line[index][0] == "text" and line[index][3] is font:
                text += line[index][1]
                cursor += line[index][2]
                index += 1
            draw.text((start, baseline), text, font=font, fill=fill, anchor="ls", stroke_width=stroke, stroke_fill=fill)
        y += height
    return y


# ---------- surfaces ----------

@lru_cache(maxsize=256)
def round_mask(width: int, height: int, radius: int) -> Image.Image:
    """Antialiased rounded-rectangle mask; only the four corners need supersampling."""
    radius = min(radius, width // 2, height // 2)
    mask = Image.new("L", (width, height), 255)
    if radius < 1:
        return mask
    corner = Image.new("L", (radius * SUPERSAMPLE, radius * SUPERSAMPLE), 0)
    ImageDraw.Draw(corner).ellipse((0, 0, 2 * radius * SUPERSAMPLE - 1, 2 * radius * SUPERSAMPLE - 1), fill=255)
    corner = corner.resize((radius, radius), Image.Resampling.LANCZOS)
    mask.paste(corner, (0, 0))
    mask.paste(ImageOps.mirror(corner), (width - radius, 0))
    mask.paste(ImageOps.flip(corner), (0, height - radius))
    mask.paste(ImageOps.flip(ImageOps.mirror(corner)), (width - radius, height - radius))
    return mask


def fill(canvas: Image.Image, box: tuple[int, int, int, int], radius: int, paint: str | Image.Image) -> None:
    """A rounded rectangle filled with a color or an opaque picture of the box's size."""
    left, top, right, bottom = box
    mask = round_mask(right - left, bottom - top, radius)
    canvas.paste(paint, box, mask)


def ring(canvas: Image.Image, box: tuple[int, int, int, int], radius: int, color: str, width: int) -> None:
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    inner = Image.new("L", (w, h), 0)
    inner.paste(round_mask(w - 2 * width, h - 2 * width, max(1, radius - width)), (width, width))
    canvas.paste(color, box, ImageChops.subtract(round_mask(w, h, radius), inner))


def ramp(size: tuple[int, int], stops: Sequence[str], *, vertical: bool = False) -> Image.Image:
    """A gradient across evenly spaced stops, for the thin marks of the design."""
    steps = 96
    line = Image.new("RGB", (1, steps) if vertical else (steps, 1))
    last = len(stops) - 1
    values = []
    for index in range(steps):
        place = index / (steps - 1) * last
        low = min(int(place), last - 1)
        values.append(tuple(round(a + (b - a) * (place - low)) for a, b in zip(rgb(stops[low]), rgb(stops[low + 1]))))
    line.putdata(values)
    return line.resize(size, Image.Resampling.BICUBIC)


def shadow(canvas: Image.Image, box: tuple[int, int, int, int], radius: int, color: str = "#37262c", *,
           blur: float = 9, offset: float = 2.5, opacity: float = 0.07) -> None:
    """A soft drop shadow, blurred at low resolution to stay fast."""
    left, top, right, bottom = box
    scale = 4
    reach = px(blur) * 2
    w, h = right - left + 2 * reach, bottom - top + 2 * reach
    small = Image.new("L", (w // scale, h // scale), 0)
    ImageDraw.Draw(small).rounded_rectangle(
        (reach // scale, reach // scale, (w - reach) // scale, (h - reach) // scale),
        radius=radius // scale, fill=round(255 * opacity))
    mask = small.filter(ImageFilter.GaussianBlur(px(blur) / scale / 2)).resize((w, h), Image.Resampling.BILINEAR)
    origin = (left - reach, top - reach + px(offset))
    canvas.paste(color, (*origin, origin[0] + w, origin[1] + h), mask)


def paper(size: tuple[int, int], strip: float = STRIP_HEIGHT) -> Image.Image:
    """The card itself: white, a warm fade at the bottom, a pink glow at the top right, the strip on top."""
    width, height = size
    canvas = Image.new("RGBA", size, SURFACE)
    start = round(height * 0.74)
    canvas.paste(ramp((width, height - start), (SURFACE, PAPER_END), vertical=True), (0, start))
    radius = px(120)
    middle_x, middle_y = round(width * 0.92), min(round(height * 0.07), px(60))
    # The source reaches 181 at the middle of each edge, so fading to zero there leaves no square outline.
    glow = Image.radial_gradient("L").point(lambda value: round(max(0, 181 - value) / 181 * 255 * 0.15))
    glow = glow.resize((2 * radius, 2 * radius), Image.Resampling.BICUBIC)
    canvas.paste(GLOW, (middle_x - radius, middle_y - radius, middle_x + radius, middle_y + radius), glow)
    canvas.paste(ramp((width, px(strip)), STRIP), (0, 0))
    return canvas


def rounded(image: Image.Image, radius: float = RADIUS) -> Image.Image:
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(image.convert("RGBA"), (0, 0), round_mask(*image.size, px(radius)))
    return out


def cover(image: Image.Image, width: int, height: int) -> Image.Image:
    return ImageOps.fit(ImageOps.exif_transpose(image).convert("RGB"), (width, height), Image.Resampling.LANCZOS)


def flatten(image: Image.Image) -> Image.Image:
    """Transparent pictures sit on the card surface instead of turning black."""
    surface = Image.new("RGBA", image.size, SURFACE)
    surface.alpha_composite(image.convert("RGBA"))
    return surface.convert("RGB")


def circle(image: Image.Image, size: int) -> Image.Image:
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(cover(flatten(image), size, size), (0, 0), round_mask(size, size, size // 2))
    return out


def rule(canvas: Image.Image, x: int, y: int, width: int, *, dashed: bool = False) -> None:
    draw = ImageDraw.Draw(canvas)
    if not dashed:
        draw.line((x, y, x + width, y), fill=LINE, width=max(1, px(0.5)))
        return
    for left in range(x, x + width, px(5)):
        draw.line((left, y, min(left + px(2.5), x + width), y), fill=PINK_DASH, width=max(1, px(0.5)))


# ---------- shapes ----------

def _supersampled(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw, float]:
    mask = Image.new("L", (size * SUPERSAMPLE, size * SUPERSAMPLE), 0)
    return mask, ImageDraw.Draw(mask), size * SUPERSAMPLE / 24


def draw_icon(canvas: Image.Image, name: str, x: int, y: int, size: int, color: str) -> None:
    """The small heart, comment, forward and play glyphs on a 24-unit grid."""
    mask, draw, unit = _supersampled(size)
    at = lambda *points: [(px_ * unit, py_ * unit) for px_, py_ in points]
    if name == "heart":
        draw.polygon([(12 * unit + 0.62 * unit * 16 * math.sin(t) ** 3,
                       11 * unit - 0.62 * unit * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
                      for t in (i * math.pi / 60 for i in range(120))], fill=255)
    elif name == "comment":
        draw.rounded_rectangle((2 * unit, 3 * unit, 22 * unit, 18 * unit), radius=5 * unit, fill=255)
        draw.polygon(at((7, 16), (7, 22.5), (14, 16)), fill=255)
    elif name == "forward":
        width = round(2.6 * unit)
        draw.line(at((3, 8), (18, 8)), fill=255, width=width)
        draw.polygon(at((16, 3), (22, 8), (16, 13)), fill=255)
        draw.line(at((21, 16), (6, 16)), fill=255, width=width)
        draw.polygon(at((8, 11), (2, 16), (8, 21)), fill=255)
    else:
        draw.rounded_rectangle((2 * unit, 4 * unit, 22 * unit, 20 * unit), radius=4.5 * unit, fill=255)
        draw.polygon(at((9.5, 8), (9.5, 16), (16, 12)), fill=0)
    canvas.paste(color, (x, y, x + size, y + size), mask.resize((size, size), Image.Resampling.LANCZOS))


# ---------- small pieces ----------

CHIP = Style(13, weight=700)
CHIP_HEIGHT = 26


def chip_width(fonts: Fonts, text: str, style: Style = CHIP, pad_x: float = 11, dot: bool = False) -> int:
    return measure(fonts, text, style) + px(pad_x) * 2 + (px(11) if dot else 0)


def draw_chip(canvas: Image.Image, fonts: Fonts, x: int, y: int, text: str, fg: str = PINK_TEXT, bg: str = PINK_SOFT, *,
              style: Style = CHIP, pad_x: float = 11, height: float = CHIP_HEIGHT, dot: str | None = None,
              edge: str | None = None) -> int:
    """A full pill; ``dot`` adds a status dot and ``edge`` a hairline border."""
    w = chip_width(fonts, text, style, pad_x, bool(dot))
    h = px(height)
    box = (x, y, x + w, y + h)
    fill(canvas, box, h // 2, bg)
    if edge:
        ring(canvas, box, h // 2, edge, max(1, px(0.5)))
    tx = x + px(pad_x)
    if dot:
        r = px(3)
        fill(canvas, (tx, y + h // 2 - r, tx + 2 * r, y + h // 2 + r), r, dot)
        tx += px(11)
    draw_text(canvas, fonts, tx, y + h / 2, text, style, anchor="lm", color=fg)
    return x + w


def flow(fonts: Fonts, chips: Sequence[tuple[str, str, str]], width: int, gap: float = 6,
         row_gap: float = 6) -> tuple[list[tuple[int, int, str, str, str]], int]:
    """Place (label, fg, bg) chips left to right, wrapping at width. Returns positions and total height."""
    positions, cx, cy = [], 0, 0
    for label, fg, bg in chips:
        w = chip_width(fonts, label)
        if cx and cx + w > width:
            cx, cy = 0, cy + px(CHIP_HEIGHT + row_gap)
        positions.append((cx, cy, label, fg, bg))
        cx += w + px(gap)
    return positions, (cy + px(CHIP_HEIGHT) if chips else 0)


def compact(number: int | None) -> str:
    if number is None:
        return "--"
    if number >= 10000:
        return f"{number / 10000:.1f}".rstrip("0").rstrip(".") + "万"
    return str(number)


# ---------- layout ----------

@dataclass
class Card:
    """A measure-then-draw vertical list of blocks; ``paint(canvas, x, y, width)`` draws each one."""
    fonts: Fonts
    blocks: list = field(default_factory=list)
    strip: float = STRIP_HEIGHT

    @property
    def inner(self) -> int:
        return px(WIDTH - 2 * PAD_X)

    def add(self, height: int, paint, gap: float = 14) -> None:
        self.blocks.append((height, paint, px(gap)))

    @property
    def height(self) -> int:
        return sum(h for h, _, _ in self.blocks) + sum(g for _, _, g in self.blocks[1:])

    def render(self) -> bytes:
        size = (px(WIDTH), self.height + px(PAD_TOP + PAD_BOTTOM))
        canvas = paper(size, self.strip)
        y = px(PAD_TOP)
        for index, (height, paint, gap) in enumerate(self.blocks):
            if index:
                y += gap
            paint(canvas, px(PAD_X), y, self.inner)
            y += height
        # Corners are transparent and stay white underneath, so a flattened copy still looks right.
        canvas.putalpha(round_mask(*size, px(RADIUS_CARD)))
        buffer = BytesIO()
        canvas.save(buffer, format="PNG", optimize=True)
        if buffer.tell() > MAX_PNG_BYTES:
            # Photo-heavy cards stay sharp enough as JPEG and much smaller for the chat platform.
            buffer = BytesIO()
            canvas.convert("RGB").save(buffer, format="JPEG", quality=92, optimize=True)
        return buffer.getvalue()


AVATAR_WRAP = 72


def title_header(card: Card, label: str, title: str, subtitle: str = "") -> None:
    """The header of a card with no author: a small pink label, a large title and a muted line."""
    fonts = card.fonts
    title_style = Style(31, weight=800)
    line = Style(14.5, color=MUTED)

    def paint(canvas, x, y, width):
        draw_text(canvas, fonts, x, y + px(7), label, Style(13.5, weight=800, color=PINK_TEXT), anchor="lm")
        draw_text(canvas, fonts, x, y + px(26), fit(fonts, title, title_style, width), title_style)
        if subtitle:
            draw_text(canvas, fonts, x, y + px(76), fit(fonts, subtitle, line, width), line, anchor="lm")

    card.add(px(84 if subtitle else 62), paint, gap=0)


def author_header(card: Card, name: str, subtitle: str = "", *, avatar: Image.Image | None = None,
                  pendant: Image.Image | None = None, kind: str = "", kind_dot: bool = False) -> None:
    """The header of a post: the avatar with its pendant, a pink name and a muted line, the kind of post on the right."""
    fonts = card.fonts
    wrap_size = px(AVATAR_WRAP)
    size = px(59)

    def paint(canvas, x, y, width):
        left, top = x + (wrap_size - size) // 2, y + (wrap_size - size) // 2
        box = (left, top, left + size, top + size)
        edge = px(2.5)
        shadow(canvas, box, size // 2, "#ff6394", blur=12, offset=4, opacity=0.2)
        fill(canvas, (left - edge, top - edge, left + size + edge, top + size + edge), size, SURFACE)
        if avatar is not None:
            canvas.alpha_composite(circle(avatar, size), (left, top))
        else:
            fill(canvas, box, size // 2, PINK_LINE)
            draw_text(canvas, fonts, left + size // 2, top + size // 2, name[:1], Style(25, weight=800, color=PINK_TEXT), anchor="mm")
        if pendant is not None:
            canvas.alpha_composite(pendant.convert("RGBA").resize((wrap_size, wrap_size), Image.Resampling.LANCZOS), (x, y))

        chip_w = chip_width(fonts, kind, dot=kind_dot) if kind else 0
        if kind:
            draw_chip(canvas, fonts, x + width - chip_w, y + (wrap_size - px(CHIP_HEIGHT)) // 2, kind, PINK_TEXT, SURFACE,
                      dot=PINK_TEXT if kind_dot else None, edge=PINK_LINE)
        tx = x + wrap_size + px(11)
        room = x + width - tx - (chip_w + px(12) if kind else 0)
        name_style = Style(23, weight=800, color=PINK)
        draw_text(canvas, fonts, tx, y + px(14), fit(fonts, name, name_style, room), name_style)
        if subtitle:
            line = Style(13.5, color=MUTED)
            draw_text(canvas, fonts, tx, y + px(52), fit(fonts, subtitle, line, room), line, anchor="lm")

    card.add(wrap_size, paint, gap=0)


def heading(card: Card, text: str, gap: float = 22) -> None:
    """A small section label, the "本条内容" of the original card."""
    style = Style(13, weight=800, color=LABEL)
    card.add(px(14), lambda canvas, x, y, width: draw_text(canvas, card.fonts, x, y + px(7), text, style, anchor="lm"),
             gap=gap)


def divider(card: Card, gap: float = 18, *, dashed: bool = False) -> None:
    card.add(1, lambda canvas, x, y, width: rule(canvas, x, y, width, dashed=dashed), gap=gap)


def signature(card: Card) -> None:
    style = Style(10.5, weight=500, color=SIGNATURE)
    card.add(px(12), lambda canvas, x, y, width: draw_text(canvas, card.fonts, x + width, y + px(6),
                                                           "LenBot / Generated by LEN", style, anchor="rm"), gap=14)


def qr_block(card: Card, left_paint, height: int, qr: Image.Image, *, gap: float = 20) -> None:
    """The dashed footer: whatever ``left_paint`` draws, and a QR code on a raised plate at the right."""
    plate = px(92)
    inner = px(84)
    block = max(height, plate)

    def paint(canvas, x, y, width):
        rule(canvas, x, y, width, dashed=True)
        top = y + px(20)
        left_paint(canvas, x, top, width - plate - px(16), block)
        left = x + width - plate
        box = (left, top, left + plate, top + plate)
        shadow(canvas, box, px(RADIUS), opacity=0.08, blur=10, offset=3)
        fill(canvas, box, px(RADIUS), SURFACE)
        canvas.paste(qr.convert("RGB").resize((inner, inner), Image.Resampling.NEAREST),
                     (left + (plate - inner) // 2, top + (plate - inner) // 2))

    card.add(block + px(20), paint, gap=gap)
