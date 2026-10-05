from rosalind.adapters.outbound.enrichment.language import LinguaLanguageDetector


def test_detects_language_and_confidence() -> None:
    detector = LinguaLanguageDetector(languages=("en", "fr"))
    language, confidence = detector.detect("Hello there, how are you doing today?")
    assert language == "en"
    assert confidence is not None and confidence > 0.5


def test_returns_none_below_confidence_threshold() -> None:
    detector = LinguaLanguageDetector(languages=("en", "fr"), min_confidence=0.99)
    # A short, ambiguous string rarely reaches 0.99 confidence.
    language, confidence = detector.detect("Hi")
    if language is not None:
        assert confidence is not None and confidence >= 0.99
