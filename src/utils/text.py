import re

_TOKEN = re.compile(r"<[^>]*>|&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);|[^<&]+|[<&]")
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)\b[^>]*>")


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def smart_split(text: str, limit: int = 4096) -> list[str]:
    """Split Telegram HTML without cutting tags, entities, or UTF-16 characters."""
    if limit < 32:
        raise ValueError("limit must be at least 32")
    if _units(text) <= limit:
        return [text]
    chunks, stack = [], []
    current, size, has_text = "", 0, False

    def closing():
        return "".join(f"</{name}>" for name, _ in reversed(stack))

    def flush():
        nonlocal current, size, has_text
        if not has_text:
            raise ValueError("HTML markup exceeds the Telegram chunk limit")
        chunks.append(current + closing())
        current = "".join(opening for _, opening in stack)
        size = _units(current)
        has_text = False

    for match in _TOKEN.finditer(text):
        token = match.group()
        tag = _TAG.fullmatch(token)
        if tag:
            is_closing, name = tag.groups()
            if is_closing:
                if stack and stack[-1][0] == name:
                    stack.pop()
                current += token
                size += _units(token)
            else:
                reserve = _units(closing() + f"</{name}>")
                if size + _units(token) + reserve > limit:
                    flush()
                if size + _units(token) + reserve > limit:
                    raise ValueError("HTML markup exceeds the Telegram chunk limit")
                current += token
                size += _units(token)
                stack.append((name, token))
            continue
        # Escaped entities are indivisible; ordinary text is split on code points.
        pieces = [token] if token.startswith("&") and token.endswith(";") else token
        for piece in pieces:
            width = _units(piece)
            if size + width + _units(closing()) > limit:
                flush()
            if size + width + _units(closing()) > limit:
                raise ValueError("HTML markup exceeds the Telegram chunk limit")
            current += piece
            size += width
            has_text = True
    if has_text:
        chunks.append(current + closing())
    return chunks
