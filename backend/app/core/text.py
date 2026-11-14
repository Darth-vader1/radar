"""Turning HTML from external sources into safe, readable plain text."""
import html
import re
from typing import Optional

_DROP_BLOCKS = re.compile(r"<(script|style|noscript|iframe)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_LINE_BREAKS = re.compile(r"<\s*br\s*/?\s*>|</\s*(p|div|h[1-6]|ul|ol|tr|section|article|blockquote)\s*>", re.IGNORECASE)
_LIST_ITEM = re.compile(r"<\s*li\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\f\v ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def looks_like_html(value: Optional[str]) -> bool:
    text = value or ""
    return bool(re.search(r"</?[a-zA-Z][^>]*>|&lt;/?[a-zA-Z]", text))


def html_to_text(value: Optional[str]) -> str:
    """
    HTML (including entity-escaped HTML such as Greenhouse's "&lt;p&gt;...") to plain text with
    paragraph breaks and "•" bullets. Script/style contents are dropped. Safe to render as text.
    """
    text = value or ""
    if "&lt;" in text or "&gt;" in text:
        text = html.unescape(text)  # escaped markup -> real markup, then strip it below
    text = _DROP_BLOCKS.sub(" ", text)
    text = _LIST_ITEM.sub("\n• ", text)
    text = _LINE_BREAKS.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)  # &amp; &nbsp; etc. left after stripping tags
    lines = [_SPACES.sub(" ", line).strip() for line in text.replace("\r", "").split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
