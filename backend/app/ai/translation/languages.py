"""The supported languages. One registry, used by the API, the prompts and the checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native_name: str
    rtl: bool
    script: str  # "latin" | "arabic" (used by the wrong-script check)
    guidance: str  # writing rules given to the model


LANGUAGES: tuple[Language, ...] = (
    Language(
        "en", "English", "English", False, "latin",
        "Plain, clear English suitable for field respondents.",
    ),
    Language(
        "ha", "Hausa", "Hausa", False, "latin",
        "Standard Hausa in Latin (Boko) script. Use the hooked letters ɓ, ɗ, ƙ and ƴ where the spelling "
        "requires them (for example kuɗi, not kudi). Use a polite, formal register suitable for addressing "
        "adults. Use natural Hausa phrasing, not word-for-word English. Keep numbers as digits.",
    ),
    Language(
        "yo", "Yoruba", "Yorùbá", False, "latin",
        "Standard Yoruba with its full diacritics: tone marks and the under-dots (ẹ, ọ, ṣ). "
        "Use a respectful register for addressing adults. Keep numbers as digits.",
    ),
    Language(
        "ig", "Igbo", "Igbo", False, "latin",
        "Standard Igbo (Igbo Izugbe) with the dotted vowels ị, ọ, ụ and the nasal ṅ where the spelling "
        "requires them. Use a respectful register for addressing adults. Keep numbers as digits.",
    ),
    Language(
        "fr", "French", "Français", False, "latin",
        "Standard French. Address the respondent with the polite 'vous' form. Keep numbers as digits.",
    ),
    Language(
        "ar", "Arabic", "العربية", True, "arabic",
        "Modern Standard Arabic, written right to left. Use complete, natural sentences. Keep numbers as "
        "Western digits (0-9) exactly as in the source. Do not add vowel marks (tashkeel). Keep Latin "
        "placeholders such as {min} exactly as written.",
    ),
)

_BY_CODE = {lang.code: lang for lang in LANGUAGES}
LANGUAGE_CODES: tuple[str, ...] = tuple(_BY_CODE)


def get_language(code: Optional[str]) -> Optional[Language]:
    return _BY_CODE.get((code or "").strip().lower())


def is_supported(code: Optional[str]) -> bool:
    return get_language(code) is not None


def as_dict(lang: Language) -> dict:
    return {"code": lang.code, "name": lang.name, "native_name": lang.native_name, "rtl": lang.rtl}


def list_languages() -> list[dict]:
    return [as_dict(lang) for lang in LANGUAGES]
