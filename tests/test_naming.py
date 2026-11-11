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


@pytest.mark.parametrize("preset,expected", [
    ("year_author_title", "2025_Smith_Deep_learning_for_crash_severity_prediction.pdf"),
    ("author_year_title", "Smith_2025_Deep_learning_for_crash_severity_prediction.pdf"),
    ("year_authors_title", "2025_Smith_et_al_Deep_learning_for_crash_severity_prediction.pdf"),
    ("authors_year_title", "Smith_et_al_2025_Deep_learning_for_crash_severity_prediction.pdf"),
    ("year_author_shorttitle", "2025_Smith_Deep_learning_for_crash_severity_prediction.pdf"),
    ("author_year_shorttitle", "Smith_2025_Deep_learning_for_crash_severity_prediction.pdf"),
    ("year_author_journal_title", "2025_Smith_Accid_Anal_Prev_Deep_learning_for_crash_severity_prediction.pdf"),
    ("author_year_journal", "Smith_2025_Accid_Anal_Prev.pdf"),
    ("title_author_year", "Deep_learning_for_crash_severity_prediction_Smith_2025.pdf"),
    ("title_only", "Deep_learning_for_crash_severity_prediction.pdf"),
    ("author_year", "Smith_2025.pdf"),
    ("citekey", "Smith2025DeepLearningForCrashSeverityPrediction.pdf"),
    ("author_year_title_spaces", "Smith (2025) Deep learning for crash severity prediction.pdf"),
    ("authors_year_title_spaces", "Smith et al (2025) Deep learning for crash severity prediction.pdf"),
    ("authors_year_title_zotero", "Smith et al - 2025 - Deep learning for crash severity prediction.pdf"),
])
def test_every_preset(preset, expected):
    meta = sample_meta()
    meta["authors"] = ["Smith", "Jones", "Lee"]
    assert len(naming.PRESETS) == 15
    assert naming.render_preset(preset, meta) == expected


def test_custom_template_keeps_fixed_text_and_warns_on_collisions():
    meta = sample_meta()
    assert naming.render_custom("{year}_{author}_{title}_MyLab", meta) == (
        "2025_Bermudez_Deep_learning_for_crash_severity_prediction_MyLab.pdf")
    assert naming.render_custom("[{journal}] {author} {year} - {shorttitle}", meta, " ") == (
        "[Accid Anal Prev] Bermudez 2025 - Deep learning for crash severity prediction.pdf")
    assert naming.validate_template("{author}_{year}") == [
        "Template has no title token; names may collide."]


@pytest.mark.parametrize("template,reason", [
    ("plain", "at least one token"), ("{unknown}", "unknown token"),
    ("{year", "unbalanced"), ("year}", "unbalanced"),
    ("{{year}}", "nested"), ("{year}{title}}", "unbalanced"),
    ("{year}/x", "invalid fixed"), ("{year}\\x", "invalid fixed"),
    ("{year}:x", "invalid fixed"), ("{year}?x", "invalid fixed"),
    ("{year}\nx", "invalid fixed"), (" {year}", "start or end"),
    ("{year}.", "start or end"), ("{year}" + "x" * 61, "at most 60"),
])
def test_custom_template_rejections(template, reason):
    with pytest.raises(naming.TemplateError, match=reason):
        naming.validate_template(template)
