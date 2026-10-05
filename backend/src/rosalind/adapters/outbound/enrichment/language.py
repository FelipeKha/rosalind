"""lingua language-detection adapter for the enrich stage.

The detector is heavy to build (it ships ~160 MB of language models), so it is
built lazily on first use. In the enrich service it is constructed once per
worker process via a pool initializer, never per call.
"""

from __future__ import annotations

from lingua import Language, LanguageDetectorBuilder

VERSION = "lingua/2"

# Default languages to load. Restricting the set keeps per-worker memory bounded
# (multiplied by the pool size). Overridable via configuration.
DEFAULT_LANGUAGES = (
    "en",
    "fr",
    "es",
    "de",
    "pt",
    "it",
    "nl",
    "zh",
    "ja",
    "ko",
    "ru",
    "ar",
)

_LANGUAGE_BY_ISO = {
    lang.iso_code_639_1.name.lower(): lang
    for name in dir(Language)
    if name.isupper()
    if isinstance(getattr(Language, name), Language)
    for lang in [getattr(Language, name)]
}


class LinguaLanguageDetector:
    version = VERSION

    def __init__(
        self,
        *,
        languages: tuple[str, ...] = DEFAULT_LANGUAGES,
        min_confidence: float = 0.0,
    ):
        self._languages = languages
        self._min_confidence = min_confidence
        self._detector = None

    def _ensure_detector(self):
        if self._detector is None:
            selected = [_LANGUAGE_BY_ISO[iso] for iso in self._languages]
            self._detector = LanguageDetectorBuilder.from_languages(*selected).build()
        return self._detector

    def detect(self, text: str) -> tuple[str | None, float | None]:
        values = self._ensure_detector().compute_language_confidence_values(text)
        if not values:
            return None, None
        top = values[0]
        if top.value < self._min_confidence:
            return None, None
        return top.language.iso_code_639_1.name.lower(), top.value
