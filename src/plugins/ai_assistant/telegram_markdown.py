"""Render provider Markdown/legacy HTML as a safe Telegram HTML subset."""

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark", {"html": True}).enable("strikethrough")
_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "code",
    "pre",
    "a",
    "blockquote",
    "tg-spoiler",
}


def _safe_url(value: str) -> bool:
    try:
        parsed = urlsplit(html.unescape(value))
        return parsed.scheme.lower() in {"http", "https", "tg", "mailto"} and not any(
            ord(char) < 32 for char in value
        )
    except ValueError:
        return False


class _SafeHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in _TAGS or (self.stack and self.stack[-1] == "code"):
            self.output.append(html.escape(self.get_starttag_text()))
            return
        attrs = dict(attrs)
        if tag == "a":
            href = attrs.get("href") or ""
            if not _safe_url(href):
                self.output.append(html.escape(self.get_starttag_text()))
                return
            opening = f'<a href="{html.escape(href, quote=True)}">'
        elif tag == "code" and re.fullmatch(r"language-[\w+-]+", attrs.get("class") or ""):
            opening = f'<code class="{attrs["class"]}">'
        else:
            opening = f"<{tag}>"
        self.output.append(opening)
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.output.append(f"</{self.stack.pop()}>")
        else:
            self.output.append(html.escape(f"</{tag}>"))

    def handle_data(self, data):
        self.output.append(html.escape(data))

    def finish(self):
        self.close()
        while self.stack:
            self.output.append(f"</{self.stack.pop()}>")
        return "".join(self.output)


def render_pyrogram_html(text: str) -> str:
    if not text:
        return ""
    output = []
    legacy = _SafeHTML()
    list_numbers = []
    links = []

    def inline(tokens):
        for token in tokens:
            kind = token.type
            if kind == "text":
                output.append(html.escape(token.content))
            elif kind == "code_inline":
                output.append(f"<code>{html.escape(token.content)}</code>")
            elif kind in {"softbreak", "hardbreak"}:
                output.append("\n")
            elif kind in {
                "strong_open",
                "strong_close",
                "em_open",
                "em_close",
                "s_open",
                "s_close",
            }:
                tag = {"strong": "b", "em": "i", "s": "s"}[kind.rsplit("_", 1)[0]]
                output.append(f"<{tag}>" if kind.endswith("_open") else f"</{tag}>")
            elif kind == "link_open":
                href = token.attrGet("href") or ""
                safe = _safe_url(href)
                links.append(safe)
                if safe:
                    output.append(f'<a href="{html.escape(href, quote=True)}">')
            elif kind == "link_close":
                if links.pop():
                    output.append("</a>")
            elif kind == "image":
                output.append(html.escape(token.content))
            elif kind == "html_inline":
                legacy.feed(token.content)
                output.extend(legacy.output)
                legacy.output.clear()
            elif token.children:
                inline(token.children)

    for token in _MARKDOWN.parse(text.strip()):
        kind = token.type
        if kind == "inline":
            inline(token.children or [])
        elif kind in {"fence", "code_block"}:
            language = token.info.split()[0] if token.info else "text"
            language = re.sub(r"[^\w+-]", "", language)[:32] or "text"
            output.append(
                f'<pre><code class="language-{language}">{html.escape(token.content.rstrip())}</code></pre>\n\n'
            )
        elif kind in {"paragraph_close", "heading_close"}:
            if kind == "heading_close":
                output.append("</b>")
            output.append("\n\n")
        elif kind == "heading_open":
            output.append("<b>")
        elif kind == "blockquote_open":
            output.append("<blockquote>")
        elif kind == "blockquote_close":
            output.append("</blockquote>\n")
        elif kind in {"bullet_list_open", "ordered_list_open"}:
            list_numbers.append(
                int(token.attrGet("start") or 1) if kind == "ordered_list_open" else None
            )
        elif kind == "list_item_open":
            number = list_numbers[-1]
            output.append("  " * (len(list_numbers) - 1) + (f"{number}. " if number else "• "))
            if number is not None:
                list_numbers[-1] += 1
        elif kind in {"bullet_list_close", "ordered_list_close"}:
            list_numbers.pop()
        elif kind == "hr":
            output.append("\n—\n")
        elif kind == "html_block":
            legacy.feed(token.content)
            output.extend(legacy.output)
            legacy.output.clear()
    output.append(legacy.finish())
    return "".join(output).strip()
