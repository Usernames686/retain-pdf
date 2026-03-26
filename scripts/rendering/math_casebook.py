from __future__ import annotations


MATH_NORMALIZATION_CASES = [
    {
        "name": "spaced_mathrm_unit",
        "source": r"\lambda = 1 2 2 \mathrm { n m }",
        "expected_normalized": r"\lambda = 122 \mathrm{nm}",
    },
    {
        "name": "nested_spaced_mathrm_unit",
        "source": r"\lambda = 9 1 \mathrm { { n m } }",
        "expected_normalized": r"\lambda = 91 \mathrm{nm}",
    },
    {
        "name": "legacy_bf_letter_group",
        "source": r"{ \bf R }",
        "expected_normalized": r"R",
    },
    {
        "name": "legacy_bf_symbol_group",
        "source": r"{ \bf \omega }",
        "expected_normalized": r"\omega",
    },
    {
        "name": "trailing_dot_ocr_noise",
        "source": r"1 / n ^ { \prime 2 } \approx 0 \dot )",
        "expected_normalized": r"1 / n ^ { \prime 2 } \approx 0.)",
    },
]

