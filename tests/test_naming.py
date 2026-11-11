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
    assert naming.token_values({"title": "<i>Deep learning</i> for crash severity prediction today"})[
        "shorttitle"] == "Deep_learning_for_crash_severity_prediction"


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


def test_budget_cuts_title_on_whole_words(tmp_path):
    meta = sample_meta()
    meta["title"] = " ".join(["Research"] * 80)
    name = naming.build_name(meta, "year_author_title", tmp_path, windows=False)
    assert len(name.encode("utf-8")) <= 255
    assert name.endswith("Research.pdf")
    assert "Research_Research" in name
    limited = naming.build_name(meta, "year_author_title", tmp_path, title_limit=17, windows=False)
    assert limited == "2025_Bermudez_Research_Research.pdf"


def test_windows_full_path_and_suffix_budget(tmp_path):
    folder = tmp_path / ("deep" * 25)
    meta = sample_meta()
    meta["title"] = " ".join(["Analysis"] * 40)
    name = naming.build_name(meta, "year_author_title", folder, suffix="_CHECK", windows=True)
    assert len(str(folder.resolve())) + 1 + len(name) <= 259
    assert len(name) <= 255
    assert name.endswith("_CHECK.pdf")
    with pytest.raises(naming.NameBudgetError):
        naming.build_name(meta, "year_author_title", tmp_path / ("x" * 300), windows=True)


def test_non_latin_linux_bytes_and_two_title_tokens(tmp_path):
    meta = sample_meta()
    meta["title"] = "東京 " * 70
    name = naming.build_name(meta, "{title}_{shorttitle}", tmp_path, windows=False)
    assert len(name.encode("utf-8")) <= 255
    assert "東京" in name
    assert not name.endswith("_東京東.pdf")


def test_long_non_title_fields_have_final_guard(tmp_path):
    meta = sample_meta()
    meta["authors"] = ["A" * 300]
    name = naming.build_name(meta, "author_year", tmp_path, windows=False)
    assert len(name.encode("utf-8")) <= 255
    assert name.endswith(".pdf")


def test_same_paper_collision_uses_dup_suffix_without_overwrite(tmp_path):
    meta = sample_meta()
    base = naming.build_name(meta, "year_author_title", tmp_path)
    existing = tmp_path / base
    existing.write_bytes(b"original")
    known = {str(existing): ("doi:one", "fingerprint-one")}
    second = naming.unique_path(tmp_path, meta, "year_author_title", paper_id="doi:one",
                                fingerprint="fingerprint-two", known=known)
    assert second.name.endswith("_dup2.pdf")
    second.write_bytes(b"second")
    third = naming.unique_path(tmp_path, meta, "year_author_title", paper_id="doi:one",
                               fingerprint="fingerprint-three", known=known)
    assert third.name.endswith("_dup3.pdf")
    assert existing.read_bytes() == b"original"


def test_different_paper_collision_extends_title(tmp_path):
    first = {"title": "Shared beginning one", "year": 2025, "authors": ["Smith"]}
    second = {"title": "Shared beginning two", "year": 2025, "authors": ["Smith"]}
    base = naming.build_name(first, "year_author_title", tmp_path, title_limit=16)
    (tmp_path / base).write_bytes(b"original")
    candidate = naming.unique_path(tmp_path, second, "year_author_title", paper_id="doi:two",
                                   fingerprint="second", title_limit=16,
                                   known={str(tmp_path / base): ("doi:one", "first")})
    assert candidate.name == "2025_Smith_Shared_beginning_two.pdf"
    assert (tmp_path / base).read_bytes() == b"original"


def test_different_paper_without_title_uses_letters(tmp_path):
    meta = sample_meta()
    base = tmp_path / "Bermudez_2025.pdf"
    base.write_bytes(b"one")
    (tmp_path / "Bermudez_2025_b.pdf").write_bytes(b"two")
    candidate = naming.unique_path(tmp_path, meta, "author_year", paper_id="doi:three",
                                   fingerprint="three")
    assert candidate.name == "Bermudez_2025_c.pdf"
    assert base.read_bytes() == b"one"
