import pytest

from papernym.core import naming


def sample_meta():
    return {"title": "Deep learning for crash severity prediction", "year": 2025,
            "year_online": 2024, "authors": ["Bermúdez", "Jones", "Lee"],
            "journal": "Accid Anal Prev"}


def test_field_cleaning_and_non_latin_fallback():
    assert naming.clean_field("<i>Bermúdez's</i> study: Part 2") == "Bermudezs_study_Part_2"
    assert naming.clean_field("東京 研究") == "東京_研究"
    assert naming.clean_field("  alpha   beta  ", "-") == "alpha-beta"
    assert naming.clean_field("alpha beta", "") == "alphabeta"


def test_six_token_values_and_missing_fields():
    values = naming.token_values(sample_meta(), "online")
    assert set(values) == naming.TOKENS
    assert values["year"] == "2024"
    assert values["author"] == "Bermudez"
    assert values["authors"] == "Bermudez_et_al"
    assert values["shorttitle"] == "Deep_learning_for_crash_severity_prediction"
    missing = naming.token_values({"title": "A study", "authors": []})
    assert missing["year"] == "nd"
    assert missing["author"] == "Unknown"
    assert missing["journal"] == ""


def test_two_authors_and_word_separator():
    meta = sample_meta()
    meta["authors"] = ["Smith", "Jones"]
    assert naming.token_values(meta, word_sep=" ")["authors"] == "Smith and Jones"
    with pytest.raises(ValueError):
        naming.clean_field("x", "/")
