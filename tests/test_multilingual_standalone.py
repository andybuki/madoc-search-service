#!/usr/bin/env python3
"""
Standalone test for multilingual metadata handling.
This doesn't require Django - just tests the core logic.
"""

# Copy the necessary functions directly for testing

LANGBASE = [
    ('eng', 'en', 'English'),
    ('zho', 'zh', 'Chinese'),
    ('fra', 'fr', 'French'),
    ('deu', 'de', 'German'),
    ('spa', 'es', 'Spanish'),
]

pg_languages = ["english", "french", "german", "spanish"]


def get_language_data(lang_code=None, langbase=None):
    if lang_code:
        if "-" in lang_code:
            lang_code = lang_code.split("-")[0]
        if len(lang_code) == 2:
            language_data = [x for x in langbase if x[1] == lang_code]
            if language_data:
                if language_data[0][-1].lower() in pg_languages:
                    pg_lang = language_data[0][-1].lower()
                else:
                    pg_lang = None
                return {
                    "language_iso639_2": language_data[0][0],
                    "language_iso639_1": language_data[0][1],
                    "language_display": language_data[0][-1].lower(),
                    "language_pg": pg_lang,
                }
        elif len(lang_code) == 3:
            language_data = [x for x in langbase if x[0] == lang_code]
            if language_data:
                if language_data[0][-1].lower() in pg_languages:
                    pg_lang = language_data[0][-1].lower()
                else:
                    pg_lang = None
                return {
                    "language_iso639_2": language_data[0][0],
                    "language_iso639_1": language_data[0][1],
                    "language_display": language_data[0][-1].lower(),
                    "language_pg": pg_lang,
                }
    return {
        "language_iso639_2": None,
        "language_iso639_1": None,
        "language_display": None,
        "language_pg": None,
    }


def process_field_fixed(
    field_instance,
    key,
    default_language,
    lang_base,
    field_type="descriptive",
):
    """
    Fixed version of process_field that determines canonical subtype BEFORE
    processing values to ensure consistency across languages.
    """
    val = None
    lang = default_language
    subtype = key
    field_data = []

    if field_instance:
        if not field_instance.get("label"):
            # Process without label (simple fields like label, summary)
            for val_lang, val in field_instance.items():
                if val_lang in ["@none", "none"]:
                    lang = default_language
                else:
                    lang = val_lang
                if val:
                    for v in val:
                        v = str(v)
                        field_data.append({
                            "type": field_type,
                            "subtype": subtype.lower(),
                            "indexable": v,
                            **get_language_data(lang_code=lang, langbase=lang_base),
                        })
        else:
            # Process metadata with label
            label_values = field_instance.get("label", {})

            # Determine canonical subtype from labels BEFORE processing values
            # Priority: English > default language > any available > key
            canonical_subtype = None
            if label_values:
                # Try English first
                if "en" in label_values and label_values["en"]:
                    canonical_subtype = label_values["en"][0]
                # Then try default language
                elif default_language in label_values and label_values[default_language]:
                    canonical_subtype = label_values[default_language][0]
                # Then try any available label
                else:
                    for label_lang, label_list in label_values.items():
                        if label_list and label_lang not in ["@none", "none"]:
                            canonical_subtype = label_list[0]
                            break
                    # Finally try @none or none
                    if not canonical_subtype:
                        for label_lang in ["@none", "none"]:
                            if label_lang in label_values and label_values[label_lang]:
                                canonical_subtype = label_values[label_lang][0]
                                break

            # Use canonical subtype if found
            if canonical_subtype:
                subtype = canonical_subtype

            if field_values := field_instance.get("value"):
                for lang, vals in field_values.items():
                    if lang in ["@none", "none"]:
                        lang = default_language
                    language_data = get_language_data(lang_code=lang, langbase=lang_base)
                    for v in vals:
                        field_data.append({
                            "type": field_type,
                            "subtype": subtype.lower(),
                            "indexable": v,
                            **language_data,
                        })

    return field_data


def process_field_buggy(
    field_instance,
    key,
    default_language,
    lang_base,
    field_type="descriptive",
):
    """
    Original buggy version that updates subtype per-language iteration.
    """
    val = None
    lang = default_language
    subtype = key
    field_data = []

    if field_instance:
        if not field_instance.get("label"):
            for val_lang, val in field_instance.items():
                if val_lang in ["@none", "none"]:
                    lang = default_language
                else:
                    lang = val_lang
                if val:
                    for v in val:
                        v = str(v)
                        field_data.append({
                            "type": field_type,
                            "subtype": subtype.lower(),
                            "indexable": v,
                            **get_language_data(lang_code=lang, langbase=lang_base),
                        })
        else:
            label_values = field_instance.get("label", {})
            if field_values := field_instance.get("value"):
                for lang, vals in field_values.items():
                    # BUG: Only updates subtype if label exists in SAME language
                    if labels := label_values.get(lang):
                        subtype = labels[0]
                    if lang in ["@none", "none"]:
                        lang = default_language
                    language_data = get_language_data(lang_code=lang, langbase=lang_base)
                    for v in vals:
                        field_data.append({
                            "type": field_type,
                            "subtype": subtype.lower(),
                            "indexable": v,
                            **language_data,
                        })

    return field_data


def test_consistent_subtype():
    """Test that both languages get the same subtype with the fix."""
    print("\n=== Test: Consistent subtype across languages ===")

    # Metadata with label only in English, values in both EN and ZH
    field_instance = {
        "label": {"en": ["dcterms:subject"]},
        "value": {"en": ["student life"], "zh": ["學生生活"]}
    }

    # Test fixed version
    result = process_field_fixed(
        field_instance=field_instance,
        key="metadata",
        default_language="en",
        lang_base=LANGBASE,
        field_type="metadata",
    )

    print(f"Fixed version results:")
    for r in result:
        print(f"  - subtype: {r['subtype']}, value: {r['indexable']}, lang: {r.get('language_iso639_1')}")

    subtypes = [r["subtype"] for r in result]
    assert len(set(subtypes)) == 1, f"FAIL: Expected single subtype, got {subtypes}"
    assert subtypes[0] == "dcterms:subject", f"FAIL: Expected 'dcterms:subject', got {subtypes[0]}"
    print("PASS: All values have consistent subtype 'dcterms:subject'\n")

    return True


def test_buggy_version_inconsistency():
    """Demonstrate the bug in the original version."""
    print("=== Test: Demonstrate original bug (for reference) ===")

    field_instance = {
        "label": {"en": ["dcterms:subject"]},
        "value": {"zh": ["學生生活"], "en": ["student life"]}  # ZH first!
    }

    result = process_field_buggy(
        field_instance=field_instance,
        key="metadata",
        default_language="en",
        lang_base=LANGBASE,
        field_type="metadata",
    )

    print(f"Buggy version results (ZH processed first):")
    for r in result:
        print(f"  - subtype: {r['subtype']}, value: {r['indexable']}, lang: {r.get('language_iso639_1')}")

    subtypes = [r["subtype"] for r in result]
    # With ZH first and no ZH label, first item gets "metadata" as subtype
    print(f"Subtypes: {subtypes}")
    print("(Bug: First item may have wrong subtype if processed before EN)\n")


def test_english_label_priority():
    """Test that English label takes priority when multiple labels exist."""
    print("=== Test: English label priority ===")

    field_instance = {
        "label": {"en": ["Subject"], "zh": ["主題"], "fr": ["Sujet"]},
        "value": {"en": ["student life"], "zh": ["學生生活"], "fr": ["vie étudiante"]}
    }

    result = process_field_fixed(
        field_instance=field_instance,
        key="metadata",
        default_language="en",
        lang_base=LANGBASE,
        field_type="metadata",
    )

    print(f"Results with multiple labels:")
    for r in result:
        print(f"  - subtype: {r['subtype']}, value: {r['indexable']}, lang: {r.get('language_iso639_1')}")

    subtypes = [r["subtype"] for r in result]
    assert all(s == "subject" for s in subtypes), f"FAIL: Expected all 'subject', got {subtypes}"
    print("PASS: All values use English label 'subject'\n")

    return True


def test_fallback_to_any_label():
    """Test that if no English label, uses any available label."""
    print("=== Test: Fallback to available label ===")

    field_instance = {
        "label": {"zh": ["主題"]},  # Only Chinese label
        "value": {"en": ["student life"], "zh": ["學生生活"]}
    }

    result = process_field_fixed(
        field_instance=field_instance,
        key="metadata",
        default_language="en",
        lang_base=LANGBASE,
        field_type="metadata",
    )

    print(f"Results with only Chinese label:")
    for r in result:
        print(f"  - subtype: {r['subtype']}, value: {r['indexable']}, lang: {r.get('language_iso639_1')}")

    subtypes = [r["subtype"] for r in result]
    assert all(s == "主題" for s in subtypes), f"FAIL: Expected all '主題', got {subtypes}"
    print("PASS: All values use Chinese label '主題'\n")

    return True


def test_count_simulation():
    """Simulate facet counting to show fix works for count consistency."""
    print("=== Test: Simulated facet count consistency ===")

    # Simulate 5 manifests all having the same metadata structure
    manifests_metadata = [
        {"label": {"en": ["Subject"]}, "value": {"en": ["History"], "zh": ["歷史"]}},
        {"label": {"en": ["Subject"]}, "value": {"en": ["History"], "zh": ["歷史"]}},
        {"label": {"en": ["Subject"]}, "value": {"en": ["History"], "zh": ["歷史"]}},
        {"label": {"en": ["Subject"]}, "value": {"en": ["History"], "zh": ["歷史"]}},
        {"label": {"en": ["Subject"]}, "value": {"en": ["History"], "zh": ["歷史"]}},
    ]

    all_indexables = []
    for i, metadata in enumerate(manifests_metadata):
        result = process_field_fixed(
            field_instance=metadata,
            key="metadata",
            default_language="en",
            lang_base=LANGBASE,
            field_type="metadata",
        )
        for r in result:
            r["manifest_id"] = i  # Track which manifest
        all_indexables.extend(result)

    # Count distinct manifests per (subtype, value)
    from collections import defaultdict
    counts = defaultdict(set)
    for i in all_indexables:
        key = (i["subtype"], i["indexable"])
        counts[key].add(i["manifest_id"])

    print("Facet counts (simulated):")
    for (subtype, value), manifest_ids in sorted(counts.items()):
        print(f"  - {subtype}/{value}: {len(manifest_ids)} manifests")

    # Verify counts are equal
    en_count = len(counts[("subject", "History")])
    zh_count = len(counts[("subject", "歷史")])

    assert en_count == zh_count == 5, f"FAIL: Expected 5 for both, got EN={en_count}, ZH={zh_count}"
    print(f"PASS: Both 'History' and '歷史' have count {en_count} (same as expected)\n")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("MULTILINGUAL METADATA FIX VERIFICATION")
    print("=" * 60)

    all_passed = True

    try:
        test_buggy_version_inconsistency()  # Just for demo, no assertion
        all_passed &= test_consistent_subtype()
        all_passed &= test_english_label_priority()
        all_passed &= test_fallback_to_any_label()
        all_passed &= test_count_simulation()
    except AssertionError as e:
        print(f"FAILED: {e}")
        all_passed = False

    print("=" * 60)
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED!")
    print("=" * 60)
