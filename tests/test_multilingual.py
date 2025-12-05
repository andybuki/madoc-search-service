"""
Unit tests for multilingual metadata handling.

Tests the fix for:
1. Consistent subtype assignment across languages
2. Language-aware facet handling
"""
import pytest
from search_service.search.serializer_utils import process_field, get_language_data
from search_service.search.langbase import LANGBASE


class TestProcessField:
    """Tests for the process_field function's multilingual handling."""

    def test_consistent_subtype_across_languages(self):
        """
        Test that a metadata field with values in multiple languages
        but label only in English produces consistent subtype for all values.

        This is the core fix for Issue 2 (count discrepancy).
        """
        # Metadata like: {"label": {"en": ["dcterms:subject"]}, "value": {"en": ["student life"], "zh": ["學生生活"]}}
        field_instance = {
            "label": {"en": ["dcterms:subject"]},
            "value": {"en": ["student life"], "zh": ["學生生活"]}
        }

        result = process_field(
            field_instance=field_instance,
            key="metadata",
            default_language="en",
            lang_base=LANGBASE,
            field_type="metadata",
            field_indexable_type="text",
        )

        # Should have 2 indexables
        assert len(result) == 2

        # Both should have the same subtype (from English label)
        subtypes = [r["subtype"] for r in result]
        assert all(s == "dcterms:subject" for s in subtypes), f"Expected all subtypes to be 'dcterms:subject', got {subtypes}"

        # Verify correct values and languages
        en_item = next((r for r in result if r.get("language_iso639_1") == "en"), None)
        zh_item = next((r for r in result if r.get("language_iso639_1") == "zh"), None)

        assert en_item is not None, "Should have English indexable"
        assert zh_item is not None, "Should have Chinese indexable"
        assert en_item["indexable"] == "student life"
        assert zh_item["indexable"] == "學生生活"

    def test_subtype_from_any_available_language(self):
        """
        Test that if label is only in Chinese, it's used as subtype for all values.
        """
        field_instance = {
            "label": {"zh": ["主題"]},
            "value": {"en": ["student life"], "zh": ["學生生活"]}
        }

        result = process_field(
            field_instance=field_instance,
            key="metadata",
            default_language="en",
            lang_base=LANGBASE,
            field_type="metadata",
            field_indexable_type="text",
        )

        # Both should have the same subtype (from Chinese label since no English)
        subtypes = [r["subtype"] for r in result]
        assert all(s == "主題" for s in subtypes), f"Expected all subtypes to be '主題', got {subtypes}"

    def test_subtype_english_priority(self):
        """
        Test that English label takes priority when multiple labels exist.
        """
        field_instance = {
            "label": {"en": ["Subject"], "zh": ["主題"], "fr": ["Sujet"]},
            "value": {"en": ["student life"], "zh": ["學生生活"], "fr": ["vie étudiante"]}
        }

        result = process_field(
            field_instance=field_instance,
            key="metadata",
            default_language="en",
            lang_base=LANGBASE,
            field_type="metadata",
            field_indexable_type="text",
        )

        # All should use English label as subtype
        subtypes = [r["subtype"] for r in result]
        assert all(s == "subject" for s in subtypes), f"Expected all subtypes to be 'subject', got {subtypes}"

    def test_subtype_fallback_to_key(self):
        """
        Test that if no label exists, the key is used as subtype.
        """
        field_instance = {
            "label": {},
            "value": {"en": ["student life"]}
        }

        result = process_field(
            field_instance=field_instance,
            key="metadata",
            default_language="en",
            lang_base=LANGBASE,
            field_type="metadata",
            field_indexable_type="text",
        )

        assert len(result) == 1
        assert result[0]["subtype"] == "metadata"

    def test_field_without_label_key(self):
        """
        Test processing a field that doesn't have a label key (like simple label fields).
        """
        field_instance = {
            "en": ["Document Title"],
            "zh": ["文檔標題"]
        }

        result = process_field(
            field_instance=field_instance,
            key="label",
            default_language="en",
            lang_base=LANGBASE,
            field_type="descriptive",
            field_indexable_type="text",
        )

        assert len(result) == 2
        # Both should use the key as subtype
        subtypes = [r["subtype"] for r in result]
        assert all(s == "label" for s in subtypes)


class TestGetLanguageData:
    """Tests for language code resolution."""

    def test_iso639_1_code(self):
        """Test 2-letter language code resolution."""
        result = get_language_data(lang_code="en", langbase=LANGBASE)
        assert result["language_iso639_1"] == "en"
        assert result["language_iso639_2"] == "eng"
        assert result["language_display"] == "english"
        assert result["language_pg"] == "english"

    def test_iso639_2_code(self):
        """Test 3-letter language code resolution."""
        result = get_language_data(lang_code="eng", langbase=LANGBASE)
        assert result["language_iso639_1"] == "en"
        assert result["language_iso639_2"] == "eng"

    def test_chinese_code(self):
        """Test Chinese language code resolution."""
        result = get_language_data(lang_code="zh", langbase=LANGBASE)
        assert result["language_iso639_1"] == "zh"
        # Chinese doesn't have a PostgreSQL text search config
        assert result["language_pg"] is None

    def test_language_with_region(self):
        """Test language code with region (e.g., en-US)."""
        result = get_language_data(lang_code="en-US", langbase=LANGBASE)
        assert result["language_iso639_1"] == "en"

    def test_unknown_language(self):
        """Test unknown language code returns None values."""
        result = get_language_data(lang_code="xyz", langbase=LANGBASE)
        assert result["language_iso639_1"] is None
        assert result["language_iso639_2"] is None


class TestMultilingualFacetScenarios:
    """
    Integration-style tests for facet scenarios.
    These test the expected behavior after indexing multilingual metadata.
    """

    def test_same_count_expected_for_equivalent_concepts(self):
        """
        Verify that when metadata is consistently in both languages,
        the subtype is the same, allowing for accurate facet counting.

        This simulates 3 manifests all having the same metadata in both EN and ZH.
        """
        manifests_metadata = [
            {"label": {"en": ["Subject"]}, "value": {"en": ["History"], "zh": ["歷史"]}},
            {"label": {"en": ["Subject"]}, "value": {"en": ["History"], "zh": ["歷史"]}},
            {"label": {"en": ["Subject"]}, "value": {"en": ["History"], "zh": ["歷史"]}},
        ]

        all_indexables = []
        for metadata in manifests_metadata:
            result = process_field(
                field_instance=metadata,
                key="metadata",
                default_language="en",
                lang_base=LANGBASE,
                field_type="metadata",
                field_indexable_type="text",
            )
            all_indexables.extend(result)

        # Count by (subtype, value)
        en_history_count = sum(1 for i in all_indexables if i["indexable"] == "History")
        zh_history_count = sum(1 for i in all_indexables if i["indexable"] == "歷史")

        # Both should have count 3 (one per manifest)
        assert en_history_count == 3
        assert zh_history_count == 3

        # All should have the same subtype
        subtypes = set(i["subtype"] for i in all_indexables)
        assert len(subtypes) == 1, f"Expected single subtype, got {subtypes}"
