"""Embedding text cleaning — one transform per test, plus the invariants callers rely on."""

from app.features.embed.cleaning import clean_for_embedding, clean_texts


def test_ascii_text_passes_through_unchanged():
    assert clean_for_embedding("Carrefour, groceries, 250.00 EGP, 2026-01-15") == (
        "Carrefour, groceries, 250.00 EGP, 2026-01-15"
    )


def test_nfkc_folds_arabic_presentation_forms():
    # U+FEFB, the isolated lam-alef ligature OCR emits for a plain lam + alef pair.
    assert clean_for_embedding("ﻻ") == "لا"


def test_strips_bidi_marks():
    assert clean_for_embedding("كارفور‏ القاهرة") == "كارفور القاهرة"


def test_strips_bidi_embedding_controls():
    assert clean_for_embedding("‫كارفور‬") == "كارفور"


def test_strips_zero_width_and_bom():
    assert clean_for_embedding("كار​فور﻿") == "كارفور"


def test_strips_soft_hyphen():
    assert clean_for_embedding("Carre­four") == "Carrefour"


def test_strips_tatweel():
    assert clean_for_embedding("الـــقاهرة") == "القاهرة"


def test_strips_tashkeel():
    assert clean_for_embedding("مُحَمَّد") == "محمد"


def test_folds_arabic_indic_digits():
    assert clean_for_embedding("٢٥٠") == "250"


def test_folds_extended_arabic_indic_digits():
    assert clean_for_embedding("۲۵۰") == "250"


def test_preserves_latin_diacritics():
    # Guards against stripping combining marks by category, which would fold
    # distinct Latin-script words together.
    assert clean_for_embedding("Café") == "Café"


def test_collapses_whitespace_runs():
    assert clean_for_embedding("Carrefour \t Cairo\n\n250") == "Carrefour Cairo 250"


def test_collapses_nbsp():
    assert clean_for_embedding("Carrefour Cairo") == "Carrefour Cairo"


def test_trims_surrounding_whitespace():
    assert clean_for_embedding("  Carrefour  ") == "Carrefour"


def test_noisy_and_clean_variants_converge():
    assert clean_for_embedding("كارفور‏  الـــقاهرة  ٢٥٠") == "كارفور القاهرة 250"


def test_is_idempotent():
    noisy = "‫كارفور‏  الـــقاهرة ٢٥٠\n"
    once = clean_for_embedding(noisy)
    assert clean_for_embedding(once) == once


def test_all_invisible_input_falls_back_to_original():
    # Must not return "" — the caller aligns returned vectors with input positions.
    assert clean_for_embedding("‏​") == "‏​"


def test_truncation_disabled_by_default():
    assert len(clean_for_embedding("x" * 500)) == 500


def test_truncates_to_max_chars():
    assert clean_for_embedding("x" * 500, max_chars=100) == "x" * 100


def test_zero_max_chars_disables_truncation():
    assert len(clean_for_embedding("x" * 500, max_chars=0)) == 500


def test_truncation_applies_after_cleaning():
    # Cleaning shrinks the string first, so the noise doesn't eat into the budget.
    assert clean_for_embedding("ا‏" * 10, max_chars=10) == "ا" * 10


def test_clean_texts_preserves_order_and_length():
    assert clean_texts(["  a  ", "٢", "b"]) == ["a", "2", "b"]
