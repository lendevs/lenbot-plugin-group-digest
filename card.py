"""The daily summary card in the shared card design: a title header, the headline, then labelled sections.

Sizes are logical pixels drawn at 2x. Text falls back through the font chain per character, and a
character no font has (most emoji) is left out rather than drawn as a box.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import ImageFont

from .card_kit import (Card, INK, INK_2, LABEL, MUTED, PINK, PINK_LINE, PINK_PALE, PINK_SOFT, PINK_TEXT, QUOTE_BAR, QUOTE_FILL,
                       QUOTE_LINE, RADIUS, Style, SURFACE, chip_width, divider, draw_chip, draw_lines, draw_text, fill, fit,
                       heading, line_height, load_fonts, paragraph, px, ramp, ring, shadow, signature, title_header)
from .daily import Summary

FONT = Path(__file__).with_name("assets") / "NotoSansSC.ttf"
BODY = Style(16.5, color=INK_2)
BAR = "#ffc1d5"


def find_font(configured: str) -> Path:
    if not configured:
        return FONT
    path = Path(configured)
    if not path.is_file():
        raise ValueError(f"字体文件不存在：{configured}")
    return path


def face_index(path: Path) -> int:
    """In a collection prefer the Simplified Chinese regular face, e.g. Noto Sans CJK SC or PingFang SC."""
    if path.suffix.lower() != ".ttc":
        return 0
    for index in range(32):
        try:
            family, style = ImageFont.truetype(str(path), 12, index=index).getname()
        except OSError:
            break
        if "SC" in family.split() and style in ("Regular", "Normal"):
            return index
    return 0


def headline(card: Card, summary: Summary) -> None:
    """The one-line summary in the pink block of the original card."""
    fonts = card.fonts
    style = Style(19, weight=800)
    pad = px(14)
    lines = paragraph(fonts, summary.headline, style, card.inner - 2 * pad, 3)
    height = len(lines) * line_height(style, 1.45) + 2 * px(12)

    def paint(canvas, x, y, width):
        box = (x, y, x + width, y + height)
        fill(canvas, box, px(RADIUS), PINK_PALE)
        ring(canvas, box, px(RADIUS), PINK_LINE, max(1, px(0.5)))
        draw_lines(canvas, fonts, lines, x + pad, y + px(12), style, 1.45)

    card.add(height, paint, gap=24)


def numbers(card: Card, summary: Summary) -> None:
    fonts = card.fonts
    peak = summary.peak()
    tiles = [("消息", str(summary.total)), ("发言", f"{summary.speakers} 人"),
             ("最热闹", f"{peak[0]:02d}:00" if peak else "—")]
    height = px(66)

    def paint(canvas, x, y, width):
        gap = px(10)
        cell = (width - 2 * gap) // 3
        for index, (label, value) in enumerate(tiles):
            left = x + index * (cell + gap)
            box = (left, y, left + cell, y + height)
            shadow(canvas, box, px(RADIUS))
            fill(canvas, box, px(RADIUS), SURFACE)
            draw_text(canvas, fonts, left + px(14), y + px(19), label, Style(13, color=MUTED), anchor="lm")
            draw_text(canvas, fonts, left + px(14), y + px(45), value, Style(22, weight=800), anchor="lm")

    card.add(height, paint, gap=14)


def activity(card: Card, summary: Summary) -> None:
    fonts = card.fonts
    hours = summary.hours
    peak = summary.peak()
    chart = px(86)
    height = px(30) + chart + px(24)
    most = max((count for _, count in hours), default=0) or 1

    def paint(canvas, x, y, width):
        slot = width / max(len(hours), 1)
        floor = y + px(30) + chart
        for step, (hour, count) in enumerate(hours):
            left, right = round(x + step * slot + px(2)), round(x + (step + 1) * slot - px(2))
            rise = max(px(4), round(chart * count / most)) if count else px(4)
            busiest = peak is not None and hour == peak[0]
            fill(canvas, (left, floor - rise, right, floor), px(4), PINK if busiest else BAR if count else PINK_SOFT)
            if step % 6 == 0:
                draw_text(canvas, fonts, left, floor + px(13), f"{hour:02d}时", Style(13, color=MUTED), anchor="lm")
        if peak is not None:
            step = next(index for index, (hour, _) in enumerate(hours) if hour == peak[0])
            label = f"{peak[0]:02d}:00 · {peak[1]} 条"
            w = chip_width(fonts, label)
            left = max(x, min(round(x + (step + 0.5) * slot) - w // 2, x + width - w))
            top = floor - max(px(4), round(chart * peak[1] / most)) - px(31)
            draw_chip(canvas, fonts, left, max(y, top), label)

    card.add(height, paint, gap=8)


def people(card: Card, summary: Summary) -> None:
    fonts = card.fonts
    step = px(34)
    most = max((count for _, count in summary.top), default=1) or 1
    height = step * len(summary.top)

    def paint(canvas, x, y, width):
        name_x = x + px(26)
        name_w = px(150)
        bar_x = name_x + name_w + px(10)
        bar_w = width - (bar_x - x) - px(52)
        for index, (name, count) in enumerate(summary.top):
            mid = y + index * step + step // 2
            draw_text(canvas, fonts, x, mid, str(index + 1), Style(17, weight=800, color=PINK if index < 3 else LABEL), anchor="lm")
            draw_text(canvas, fonts, name_x, mid, fit(fonts, name, Style(16), name_w), Style(16, color=INK), anchor="lm")
            top, bottom = mid - px(4), mid + px(4)
            fill(canvas, (bar_x, top, bar_x + bar_w, bottom), px(4), PINK_SOFT)
            fill(canvas, (bar_x, top, bar_x + max(px(8), round(bar_w * count / most)), bottom), px(4), PINK if index == 0 else BAR)
            draw_text(canvas, fonts, x + width, mid, str(count), Style(15.5, weight=700), anchor="rm")

    card.add(height, paint, gap=6)


def topic_block(card: Card, index: int, topic) -> None:
    fonts = card.fonts
    number_w = px(26)
    width = card.inner - number_w
    title_style = Style(18, weight=800)
    people_style = Style(14, color=MUTED)
    title = paragraph(fonts, topic.title, title_style, width, 2)
    body = paragraph(fonts, topic.summary, BODY, width, 6)
    names = paragraph(fonts, "参与：" + "、".join(topic.people), people_style, width, 2) if topic.people else []
    title_h = len(title) * line_height(title_style, 1.45)
    body_h = len(body) * line_height(BODY, 1.66)
    height = title_h + px(3) + body_h + (px(5) + len(names) * line_height(people_style, 1.5) if names else 0)

    def paint(canvas, x, y, _):
        draw_text(canvas, fonts, x, y + line_height(title_style, 1.45) // 2 - px(1), str(index + 1),
                  Style(18, weight=800, color=PINK), anchor="lm")
        cy = draw_lines(canvas, fonts, title, x + number_w, y - px(1), title_style, 1.45)
        cy = draw_lines(canvas, fonts, body, x + number_w, cy + px(3), BODY, 1.66)
        draw_lines(canvas, fonts, names, x + number_w, cy + px(5), people_style, 1.5)

    card.add(height, paint, gap=18 if index else 8)


def quote_block(card: Card, index: int, quote, zone: ZoneInfo) -> None:
    """A message in the gray block with a pink bar that a repost uses on the Bilibili card."""
    fonts = card.fonts
    pad_left, pad = px(19), px(14)
    inner = card.inner - pad_left - pad
    style = Style(16.5, color=INK)
    remark_style = Style(14.5, weight=600, color=PINK_TEXT)
    lines = paragraph(fonts, quote.line.text, style, inner, 5)
    remark = paragraph(fonts, quote.comment, remark_style, inner, 2)
    body_h = len(lines) * line_height(style, 1.6)
    remark_h = len(remark) * line_height(remark_style, 1.5)
    height = pad + px(18) + px(7) + body_h + (px(4) + remark_h if remark else 0) + pad
    stamp = datetime.fromtimestamp(quote.line.time, zone)
    name_style = Style(14.5, weight=800, color=PINK_TEXT)

    def paint(canvas, x, y, width):
        box = (x, y, x + width, y + height)
        fill(canvas, box, px(RADIUS), QUOTE_FILL)
        ring(canvas, box, px(RADIUS), QUOTE_LINE, max(1, px(0.5)))
        canvas.paste(ramp((px(3.5), height - 2 * px(RADIUS)), QUOTE_BAR, vertical=True), (x, y + px(RADIUS)))
        middle = y + pad + px(9)
        right = draw_text(canvas, fonts, x + pad_left, middle, "@" + fit(fonts, quote.line.name, name_style, inner * 2 // 3),
                          name_style, anchor="lm")
        draw_text(canvas, fonts, right + px(8), middle, f"{stamp:%H:%M}", Style(13, color=MUTED), anchor="lm")
        cy = draw_lines(canvas, fonts, lines, x + pad_left, y + pad + px(25), style, 1.6)
        if remark:
            draw_lines(canvas, fonts, remark, x + pad_left, cy + px(4), remark_style, 1.5)

    card.add(height, paint, gap=12 if index else 8)


def render(summary: Summary, font: Path, title: str = "群聊总结") -> bytes:
    card = Card(load_fonts(font, face_index(font)))
    title_header(card, "LenBot 聊天日报", title, summary.window_text())
    headline(card, summary)
    numbers(card, summary)
    heading(card, "什么时候最热闹", 26)
    activity(card, summary)
    if summary.top:
        heading(card, "说话最多的人", 24)
        people(card, summary)
    divider(card, 20)
    heading(card, "聊了什么", 20)
    for index, topic in enumerate(summary.topics):
        topic_block(card, index, topic)
    if summary.quotes:
        zone = ZoneInfo(summary.timezone)
        divider(card, 22)
        heading(card, "原话", 20)
        for index, quote in enumerate(summary.quotes):
            quote_block(card, index, quote, zone)
    signature(card)
    return card.render()
