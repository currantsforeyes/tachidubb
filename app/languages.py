"""Language sets shared by the quick-test, batch and showcase routes."""

# Default language picks for the Quick-Test feature. The frontend allows a
# per-run override; this is just the pre-selection.
QUICK_TEST_DEFAULT_LANGS = ("es", "fr", "de", "ja", "pt")

QUICK_TEST_KNOWN_LANGS = {
    "en", "ru", "es", "pt", "fr", "de", "it", "pl", "tr",
    "ja", "ko", "zh", "ar", "hi", "nl",
}