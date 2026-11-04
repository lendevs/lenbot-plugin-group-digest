"""Card rendering on its own: the bundled font, a configured static font, and sparse summaries."""

from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
import pytest


def summary(**values):
    from group_digest.daily import Line, Quote, Summary, Topic
    base = datetime(2026, 11, 3, 20).timestamp()
    fields = dict(after=base - 86400, before=base, timezone='Asia/Shanghai', total=9, speakers=2,
                  top=(('很长很长很长很长很长很长很长很长的群名片', 8), ('🌸', 1)),
                  hours=tuple((hour, hour % 5) for hour in range(24)), headline='周末桌游局基本敲定 🎲',
                  topics=(Topic('桌游', '六点开局。' * 40, ('小满',)),),
                  quotes=(Quote(Line(1, base - 60, '1', '🌸', '好耶', False, '1'), '定调了'),), batches=1)
    return Summary(**{**fields, **values})


def size(data: bytes) -> tuple[int, int]:
    return PILImage.open(BytesIO(data)).size


def test_empty_day_and_names_without_any_drawable_character_still_render():
    from group_digest import card
    quiet = summary(top=(), quotes=(), topics=(), hours=tuple((hour, 0) for hour in range(24)))
    assert size(card.render(quiet, card.find_font('')))[0] == 1200
    assert size(card.render(summary(), card.find_font('')))[0] == 1200


def test_a_configured_static_font_draws_heavy_text_with_a_stroke():
    from group_digest import card
    dejavu = next((path for path in (Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
                                     Path('/System/Library/Fonts/Hiragino Sans GB.ttc')) if path.is_file()), None)
    if dejavu is None:
        pytest.skip('no static font on this machine')
    assert size(card.render(summary(), dejavu))[0] == 1200


def test_a_missing_configured_font_is_reported():
    from group_digest import card
    with pytest.raises(ValueError, match='字体文件不存在'):
        card.find_font('/no/such/font.ttf')


def test_closing_punctuation_never_starts_a_line():
    from group_digest.card_kit import NO_LINE_START, Style, layout, load_fonts, Run
    from group_digest import card
    fonts = load_fonts(card.FONT)
    style = Style(16)
    width = fonts.get(16).getlength('字') * 10
    for length in range(5, 40):
        lines = layout(fonts, [Run('字' * length + '，' + '后' * 30)], style, round(width))
        assert all(line[0][1] not in NO_LINE_START for line in lines)
