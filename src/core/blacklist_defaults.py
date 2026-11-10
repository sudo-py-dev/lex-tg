"""Cumulative English/Hebrew moderation presets with bounded whole-word matching."""

import re
import unicodedata

PRESET_PREFIX = "(?#lex-preset-v2:"

# Keep explicit inflections instead of matching arbitrary substrings.
WORD_PACKAGES = {
    "low": (
        "stupid",
        "idiot",
        "idiots",
        "idiotic",
        "shut up",
        "dumb",
        "dumbass",
        "weirdo",
        "moron",
        "morons",
        "jerk",
        "loser",
        "losers",
        "scumbag",
        "bastard",
        "bastards",
        "damn",
        "dammit",
        "crap",
        "טיפש",
        "טיפשה",
        "טיפשים",
        "טיפשות",
        "מטומטם",
        "מטומטמת",
        "מטומטמים",
        "מטומטמות",
        "אידיוט",
        "אידיוטית",
        "אידיוטים",
        "דביל",
        "דבילית",
        "דבילים",
        "מפגר",
        "מפגרת",
        "מפגרים",
        "סתום",
        "סתמי",
        "סתמו",
    ),
    "medium": (
        "fuck",
        "fucking",
        "fucked",
        "fucker",
        "fuckers",
        "fuck off",
        "fuck you",
        "motherfucker",
        "motherfuckers",
        "shit",
        "shitty",
        "bullshit",
        "asshole",
        "assholes",
        "bitch",
        "bitches",
        "son of a bitch",
        "dick",
        "dickhead",
        "pussy",
        "cunt",
        "cunts",
        "cock",
        "wanker",
        "prick",
        "stfu",
        "חרא",
        "זבל",
        "זין",
        "זונה",
        "זונות",
        "בן זונה",
        "בת זונה",
        "בני זונות",
        "כוסאמק",
        "כוסעמק",
        "כוסאמאק",
        "כוס אמא שלך",
        "לך תזדיין",
        "לכי תזדייני",
        "תזדיין",
        "תזדייני",
        "תזדיינו",
        "מזדיין",
        "מזדיינת",
        "מניאק",
        "מניאקית",
        "מניאקים",
        "שרמוטה",
        "שרמוטות",
    ),
    "hard": (
        "nigger",
        "niggers",
        "nigga",
        "niggas",
        "faggot",
        "faggots",
        "kike",
        "kikes",
        "chink",
        "chinks",
        "retard",
        "retards",
        "retarded",
        "kill yourself",
        "go kill yourself",
        "porn",
        "porno",
        "pornography",
        "xxx videos",
        "nude photos",
        "sex chat",
        "free porn",
        "online casino",
        "casino bonus",
        "betting bonus",
        "guaranteed profit",
        "guaranteed returns",
        "double your money",
        "get rich quick",
        "earn money fast",
        "risk free investment",
        "פורנו",
        "פורנוגרפיה",
        "סרטי סקס",
        "תמונות עירום",
        "צאט סקס",
        "קזינו אונליין",
        "בונוס קזינו",
        "כסף קל",
        "רווח מובטח",
        "תשואה מובטחת",
        "השקעה ללא סיכון",
        "תכפיל את הכסף",
        "לך תמות",
        "לכי תמותי",
    ),
}

_LEET = {"a": "[a@4]", "e": "[e3]", "i": "[i1!]", "o": "[o0]", "s": "[s$5]", "t": "[t7]"}
_SEPARATOR = r"[\W_]{0,2}"


def normalize_preset_text(text: str) -> str:
    """Fold compatibility forms, accents/niqqud, and invisible formatting for presets only."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) not in {"Mn", "Cf"})


# Pointed Hebrew sometimes omits vowel letters present in ordinary spelling.
_TERM_VARIANTS = {
    "מטומטם": ("מטמטם",),
    "מטומטמת": ("מטמטמת",),
    "מטומטמים": ("מטמטמים",),
    "מטומטמות": ("מטמטמות",),
    "רווח מובטח": ("רוח מבטח", "רווח מבטח", "רוח מובטח"),
}


def _phrase_pattern(term: str) -> str:
    words = []
    for word in normalize_preset_text(term).split():
        letters = [_LEET.get(char, re.escape(char)) + "{1,3}" for char in word]
        body = _SEPARATOR.join(letters)
        if all("\u05d0" <= char <= "\u05ea" for char in word):
            body = r"[ובכלמשה]{0,2}" + body
        words.append(body)
    return r"[\W_]*".join(words)


def preset_pattern(term: str) -> str:
    alternatives = [_phrase_pattern(variant) for variant in (term, *_TERM_VARIANTS.get(term, ()))]
    body = "|".join(alternatives)
    return f"{PRESET_PREFIX}{term})" + rf"(?<!\w)(?:{body})(?!\w)"


def describe_block_pattern(pattern: str) -> str:
    if pattern.startswith(PRESET_PREFIX):
        return pattern[len(PRESET_PREFIX) :].split(")", 1)[0]
    return pattern


BAD_WORDS_BLOCKS: dict[str, list[str]] = {}
_terms: list[str] = []
for _level, _words in WORD_PACKAGES.items():
    _terms.extend(_words)
    BAD_WORDS_BLOCKS[_level] = [preset_pattern(term) for term in dict.fromkeys(_terms)]
