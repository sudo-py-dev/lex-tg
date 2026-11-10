from __future__ import annotations

import emoji

from src.core.context import AppContext

LANG_DATA = {
    "af": {"name": "Afrikaans", "emoji": ":South_Africa:"},
    "ar": {"name": "العربية", "emoji": ":Saudi_Arabia:"},
    "bg": {"name": "Български", "emoji": ":Bulgaria:"},
    "bn": {"name": "বাংলা", "emoji": ":Bangladesh:"},
    "ca": {"name": "Català", "emoji": ":Spain:"},
    "cs": {"name": "Čeština", "emoji": ":Czechia:"},
    "cy": {"name": "Cymraeg", "emoji": ":Wales:"},
    "da": {"name": "Dansk", "emoji": ":Denmark:"},
    "de": {"name": "Deutsch", "emoji": ":Germany:"},
    "el": {"name": "Ελληνικά", "emoji": ":Greece:"},
    "en": {"name": "English", "emoji": ":United_States:"},
    "es": {"name": "Español", "emoji": ":Spain:"},
    "et": {"name": "Eesti", "emoji": ":Estonia:"},
    "fa": {"name": "فارسی", "emoji": ":Iran:"},
    "fi": {"name": "Suomi", "emoji": ":Finland:"},
    "fr": {"name": "Français", "emoji": ":France:"},
    "gu": {"name": "ગુજરાતી", "emoji": ":India:"},
    "he": {"name": "עברית", "emoji": ":Israel:"},
    "hi": {"name": "हिन्दी", "emoji": ":India:"},
    "hr": {"name": "Hrvatski", "emoji": ":Croatia:"},
    "hu": {"name": "Magyar", "emoji": ":Hungary:"},
    "id": {"name": "Bahasa Indonesia", "emoji": ":Indonesia:"},
    "it": {"name": "Italiano", "emoji": ":Italy:"},
    "ja": {"name": "日本語", "emoji": ":Japan:"},
    "kn": {"name": "ಕನ್ನಡ", "emoji": ":India:"},
    "ko": {"name": "한국어", "emoji": ":South_Korea:"},
    "lt": {"name": "Lietuvių", "emoji": ":Lithuania:"},
    "lv": {"name": "Latviešu", "emoji": ":Latvia:"},
    "mk": {"name": "Македонски", "emoji": ":North_Macedonia:"},
    "ml": {"name": "മലയാളം", "emoji": ":India:"},
    "mr": {"name": "मराठी", "emoji": ":India:"},
    "ne": {"name": "नेपाली", "emoji": ":Nepal:"},
    "nl": {"name": "Nederlands", "emoji": ":Netherlands:"},
    "no": {"name": "Norsk", "emoji": ":Norway:"},
    "pa": {"name": "ਪੰਜਾਬੀ", "emoji": ":India:"},
    "pl": {"name": "Polski", "emoji": ":Poland:"},
    "pt": {"name": "Português", "emoji": ":Portugal:"},
    "ro": {"name": "Română", "emoji": ":Romania:"},
    "ru": {"name": "Русский", "emoji": ":Russia:"},
    "sk": {"name": "Slovenčina", "emoji": ":Slovakia:"},
    "sl": {"name": "Slovenščina", "emoji": ":Slovenia:"},
    "so": {"name": "Soomaali", "emoji": ":Somalia:"},
    "sq": {"name": "Shqip", "emoji": ":Albania:"},
    "sv": {"name": "Svenska", "emoji": ":Sweden:"},
    "sw": {"name": "Kiswahili", "emoji": ":Tanzania:"},
    "ta": {"name": "தமிழ்", "emoji": ":India:"},
    "te": {"name": "తెలుగు", "emoji": ":India:"},
    "th": {"name": "ไทย", "emoji": ":Thailand:"},
    "tl": {"name": "Tagalog", "emoji": ":Philippines:"},
    "tr": {"name": "Türkçe", "emoji": ":Turkey:"},
    "uk": {"name": "Українська", "emoji": ":Ukraine:"},
    "ur": {"name": "اردו", "emoji": ":Pakistan:"},
    "vi": {"name": "Tiếng Việt", "emoji": ":Vietnam:"},
    "zh": {"name": "中文", "emoji": ":China:"},
    "zh-cn": {"name": "简体中文", "emoji": ":China:"},
    "zh-tw": {"name": "繁體中文", "emoji": ":Taiwan:"},
}


async def get_lang_info(
    ctx: AppContext,
    code: str,
) -> tuple[str, str]:
    """
    Get native language name and emoji for a given language code.

    Args:
        ctx: App context.
        code: The language code to get info for (e.g., 'en', 'zh-cn').

    Returns:
        tuple[str, str]: (native_name, emoji_character)
    """
    data = LANG_DATA.get(code)
    if not data:
        emoji_char = emoji.emojize(":globe_with_meridians:", language="alias")
        return code.upper(), emoji_char

    emoji_char = emoji.emojize(data["emoji"], language="alias")
    return data["name"], emoji_char


async def get_all_langs_info(
    ctx: AppContext,
    codes: list[str] | None = None,
) -> dict[str, tuple[str, str]]:
    """Batch version of get_lang_info."""
    if codes is None:
        codes = list(LANG_DATA.keys())

    results = {}
    for code in codes:
        results[code] = await get_lang_info(ctx, code)

    return results
