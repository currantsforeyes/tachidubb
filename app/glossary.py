"""User-editable glossary structure + validation.

The translator ships with a built-in glossary; users add their own domain
terms via ``presets/user_glossary.json`` (loaded lazily by translator.py).
Extracted from ``server.py`` so the validation is unit-testable and the route
handler stays thin.

Format::

    { "domains": [
        { "name": "Cooking EN→RU",
          "triggers": ["cooking", "recipe"],
          "target_lang": "ru",
          "terms": { "sear": "запекать" } },
    ] }
"""
from typing import Optional

GLOSSARY_EXAMPLE = {
    "domains": [
        {
            "name": "Example: Cooking EN→RU",
            "triggers": ["cooking", "recipe", "food"],
            "target_lang": "ru",
            "terms": {
                "sear": "обжарить до корочки",
                "simmer": "томить",
                "al dente": "аль денте",
            },
        },
    ],
}


def validate_glossary(data) -> Optional[str]:
    """Return an error message if ``data`` is malformed, else None."""
    if not isinstance(data, dict):
        return "Top level must be an object"
    domains = data.get("domains", [])
    if not isinstance(domains, list):
        return "'domains' must be an array"
    for i, d in enumerate(domains):
        if not isinstance(d, dict):
            return f"domains[{i}] must be an object"
        if not isinstance(d.get("terms", {}), dict):
            return f"domains[{i}].terms must be an object"
        if not isinstance(d.get("triggers", []), list):
            return f"domains[{i}].triggers must be an array"
    return None


def total_terms(data: dict) -> int:
    """Count user-defined terms across all domains."""
    return sum(len(d.get("terms", {})) for d in data.get("domains", []) if isinstance(d, dict))