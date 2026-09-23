"""Glossary structure + validation (extracted from server.py)."""
from app.glossary import GLOSSARY_EXAMPLE, total_terms, validate_glossary


def test_example_is_valid():
    assert validate_glossary(GLOSSARY_EXAMPLE) is None


def test_valid_minimal_glossary():
    assert validate_glossary({"domains": []}) is None
    assert validate_glossary({"domains": [{"terms": {}, "triggers": []}]}) is None


def test_non_dict_rejected():
    assert validate_glossary([]) == "Top level must be an object"
    assert validate_glossary("x") == "Top level must be an object"


def test_domains_must_be_array():
    assert validate_glossary({"domains": {}}) == "'domains' must be an array"


def test_domain_entry_must_be_object():
    assert validate_glossary({"domains": ["nope"]}) == "domains[0] must be an object"


def test_terms_must_be_object():
    err = validate_glossary({"domains": [{"terms": [], "triggers": []}]})
    assert err == "domains[0].terms must be an object"


def test_triggers_must_be_array():
    err = validate_glossary({"domains": [{"terms": {}, "triggers": "x"}]})
    assert err == "domains[0].triggers must be an array"


def test_total_terms_counts_across_domains():
    data = {
        "domains": [
            {"terms": {"a": "1", "b": "2"}},
            {"terms": {"c": "3"}},
            {"nope": True},
        ]
    }
    assert total_terms(data) == 3


def test_total_terms_empty():
    assert total_terms({}) == 0