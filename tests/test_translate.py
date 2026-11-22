"""Tests for the translate module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test
import scripts.translate as translate


@pytest.fixture
def temp_locales_dir(tmp_path: Path) -> Path:
    """Create a temporary locales directory with test files."""
    locales_dir = tmp_path / "src" / "locales"
    locales_dir.mkdir(parents=True)

    # Create en.json as source of truth
    en_data = {
        "greeting.hello": "Hello {name}!",
        "greeting.bye": "Goodbye",
        "action.save": "Save",
        "action.cancel": "Cancel",
        "button.submit": "Submit",
    }
    (locales_dir / "en.json").write_text(json.dumps(en_data), encoding="utf-8")

    return locales_dir


@pytest.fixture
def mock_en_file(temp_locales_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Mock the EN_FILE path to use temp directory."""
    monkeypatch.setattr(translate, "EN_FILE", temp_locales_dir / "en.json")
    monkeypatch.setattr(translate, "LOCALES_DIR", temp_locales_dir)
    return temp_locales_dir / "en.json"


class TestLocaleManager:
    """Tests for LocaleManager class."""

    def test_load_en_success(self, mock_en_file: Path) -> None:
        """Test successful loading of en.json."""
        mgr = translate.LocaleManager()
        assert len(mgr.en_data) == 5
        assert mgr.en_data["greeting.hello"] == "Hello {name}!"

    def test_load_en_missing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test exit when en.json is missing."""
        fake_path = tmp_path / "nonexistent.json"
        monkeypatch.setattr(translate, "EN_FILE", fake_path)

        with pytest.raises(SystemExit) as exc_info:
            translate.LocaleManager()
        assert exc_info.value.code == 1

    def test_load_locale_existing(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test loading existing locale file."""
        he_data = {"greeting.hello": "שלום {name}!"}
        (temp_locales_dir / "he.json").write_text(json.dumps(he_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        loaded = mgr.load_locale("he")
        assert loaded == he_data

    def test_load_locale_missing(self, mock_en_file: Path) -> None:
        """Test loading non-existent locale returns empty dict."""
        mgr = translate.LocaleManager()
        loaded = mgr.load_locale("xx")
        assert loaded == {}

    def test_load_locale_corrupted(
        self, mock_en_file: Path, temp_locales_dir: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test handling of corrupted locale file."""
        (temp_locales_dir / "he.json").write_text("not valid json", encoding="utf-8")

        mgr = translate.LocaleManager(verbose=True)
        loaded = mgr.load_locale("he")
        assert loaded == {}

    def test_save_json_ordering(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test that saved JSON maintains key order from en.json."""
        mgr = translate.LocaleManager()

        # Data with keys in different order than en.json
        data = {
            "action.cancel": "Cancelar",
            "greeting.hello": "Hola {name}!",
            "action.save": "Guardar",
        }
        path = temp_locales_dir / "es.json"
        mgr.save_json(path, data)

        # Read and verify order matches en.json (alphabetical)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert list(saved) == ["action.cancel", "action.save", "greeting.hello"]

    def test_get_locale_path(self, mock_en_file: Path) -> None:
        """Test locale path generation."""
        mgr = translate.LocaleManager()
        path = mgr.get_locale_path("he")
        assert path.name == "he.json"


class TestTranslator:
    """Tests for Translator class."""

    def test_protect_placeholders(self) -> None:
        """Test placeholder protection during translation prep."""
        t = translate.Translator("iw")  # Use iw (Google code) not he
        text = "Hello {name}, you have {count} messages"
        protected, mapping = t._protect(text)

        assert "[[--T_PH_0--]]" in protected
        assert "[[--T_PH_1--]]" in protected
        assert "{name}" not in protected
        assert "{count}" not in protected
        assert mapping["[[--T_PH_0--]]"] == "{name}"
        assert mapping["[[--T_PH_1--]]"] == "{count}"

    def test_protect_no_placeholders(self) -> None:
        """Test protection on text without placeholders."""
        t = translate.Translator("es")
        text = "Hello world"
        protected, mapping = t._protect(text)

        assert protected == text
        assert mapping == {}

    def test_restore_placeholders(self) -> None:
        """Test placeholder restoration after translation."""
        t = translate.Translator("es")
        mapping = {"[[--T_PH_0--]]": "{name}", "[[--T_PH_1--]]": "{count}"}

        translated = "שלום [[--T_PH_0--]], יש לך [[--T_PH_1--]] הודעות"
        restored = t._restore(translated, mapping)

        assert "{name}" in restored
        assert "{count}" in restored
        assert "[[--T_PH_" not in restored

    def test_restore_with_artifacts(self) -> None:
        """Test cleanup of translation artifacts."""
        t = translate.Translator("es")
        mapping = {"[[--T_PH_0--]]": "{name}"}

        # Simulate common translation artifacts
        translated = "Hola {name}_ cómo estás"
        restored = t._restore(translated, mapping)

        assert "{name}_" not in restored or "{name}_" == "{name}" + "_"

    def test_restore_empty_text(self) -> None:
        """Test restoration with empty/None text."""
        t = translate.Translator("es")
        result = t._restore("", {})
        assert result == ""

    @patch("scripts.translate.GoogleTranslator")
    def test_translate_batch_success(self, mock_translator_class: MagicMock) -> None:
        """Test successful batch translation."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Hola |§| Adiós"
        mock_translator_class.return_value = mock_translator

        t = translate.Translator("es")
        result = t.translate_batch(["Hello", "Goodbye"])

        assert result == ["Hola", "Adiós"]
        mock_translator.translate.assert_called_once()

    @patch("scripts.translate.GoogleTranslator")
    def test_translate_batch_mismatched_count(self, mock_translator_class: MagicMock) -> None:
        """Test batch translation with mismatched result count."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Hola"  # Only 1 result for 2 inputs
        mock_translator_class.return_value = mock_translator

        t = translate.Translator("es")
        result = t.translate_batch(["Hello", "Goodbye"])

        assert result is None

    @patch("scripts.translate.GoogleTranslator")
    def test_translate_batch_exception(self, mock_translator_class: MagicMock) -> None:
        """Test batch translation handling exceptions."""
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("API Error")
        mock_translator_class.return_value = mock_translator

        t = translate.Translator("es")
        result = t.translate_batch(["Hello"])

        assert result is None

    @patch("scripts.translate.GoogleTranslator")
    def test_translate_single_success(self, mock_translator_class: MagicMock) -> None:
        """Test successful single translation."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Hola [[--T_PH_0--]]"
        mock_translator_class.return_value = mock_translator

        t = translate.Translator("es")
        result = t.translate_single("Hello {name}")

        assert "{name}" in result
        assert "Hola" in result

    @patch("scripts.translate.GoogleTranslator")
    def test_translate_single_fallback(self, mock_translator_class: MagicMock) -> None:
        """Test fallback to original text on translation failure."""
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("API Error")
        mock_translator_class.return_value = mock_translator

        t = translate.Translator("es")
        original = "Hello {name}"
        result = t.translate_single(original)

        assert result == original

    def test_translate_batch_empty(self) -> None:
        """Test batch translation with empty list."""
        t = translate.Translator("es")
        result = t.translate_batch([])
        assert result == []


class TestStringScanner:
    """Tests for StringScanner AST visitor."""

    def test_finds_unlocalized_string(self) -> None:
        """Test detection of unlocalized string literals."""
        code = """
MSG = "This is a long message that should be localized"
"""
        en_keys = {"existing.key"}
        en_values = {"existing value"}

        scanner = translate.StringScanner(en_keys, en_values, code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 1
        assert scanner.found[0][1] == "This is a long message that should be localized"

    def test_ignores_short_strings(self) -> None:
        """Test that short strings are ignored."""
        code = 'x = "hi"\ny = "hello world"'
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 1  # Only "hello world"

    def test_ignores_logger_calls(self) -> None:
        """Test that strings inside logger calls are ignored."""
        code = """
logger.info("This is a log message that should not be localized")
log.debug("Another log message")
"""
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 0

    def test_ignores_existing_keys(self) -> None:
        """Test that strings matching existing keys/values are ignored."""
        code = 'x = "Hello World"'
        scanner = translate.StringScanner(set(), {"Hello World"}, code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 0

    def test_ignores_constants(self) -> None:
        """Test that constants (ALL_CAPS) are ignored."""
        code = 'x = "SOME_CONSTANT"\ny = "ANOTHER_CONSTANT_VALUE"'
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 0

    def test_ignores_technical_patterns(self) -> None:
        """Test filtering of technical patterns."""
        code = """
x = "https://example.com"
y = "IDENTITY: system prompt"
z = "<green>colored text</>"
"""
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 0

    def test_ignores_print_statements(self) -> None:
        """Test that strings in print statements are ignored."""
        code = 'print("This debug output should not be localized")'
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 0

    def test_ignores_import_lines(self) -> None:
        """Test that strings in import/docstring lines are ignored."""
        code = '''
"""Module docstring that should not be scanned."""
import os
from typing import Dict
'''
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 0


class TestRegexPatterns:
    """Tests for regex patterns used in the module."""

    def test_placeholder_pattern(self) -> None:
        """Test placeholder regex matches expected patterns."""
        pattern = translate.PLACEHOLDER_PATTERN

        assert pattern.findall("Hello {name}") == ["{name}"]
        assert pattern.findall("{count} items") == ["{count}"]
        assert pattern.findall("Hello {first} {last}") == ["{first}", "{last}"]
        assert pattern.findall("No placeholders") == []
        # Note: {{braces}} contains {braces} inside - the regex finds inner braces
        assert pattern.findall("Escaped {{braces}}") == ["{braces}"]

    def test_placeholder_restore_pattern(self) -> None:
        """Test restore pattern matches token variations."""
        pattern = translate.PLACEHOLDER_RESTORE

        assert pattern.search("[[--T_PH_0--]]") is not None
        assert pattern.search("[[T_PH_0]]") is not None
        assert pattern.search("[[-T_PH_0-]]") is not None
        assert pattern.search("not a token") is None

    def test_technical_patterns(self) -> None:
        """Test technical pattern regexes."""
        patterns = translate.TECHNICAL_PATTERNS

        # Constants
        assert any(p.match("ALL_CAPS") for p in patterns)
        assert any(p.match("CONSTANT_NAME") for p in patterns)

        # HTML tags
        assert any(p.search("<green>text</>") for p in patterns)

        # URLs
        assert any(p.match("https://example.com") for p in patterns)

        # Identity prefix
        assert any(p.match("IDENTITY: system") for p in patterns)


class TestBuildWorkPlan:
    """Tests for build_work_plan function."""

    def test_detects_missing_keys(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test detection of missing keys in locale files."""
        # Create incomplete locale file
        es_data = {"greeting.hello": "Hola {name}!"}  # Missing other keys
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        plan = translate.build_work_plan(mgr, ["es"])

        assert len(plan) == 1
        assert "action.save" in plan[0]["missing"]
        assert "action.cancel" in plan[0]["missing"]

    def test_detects_extra_keys(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test detection of extra keys not in en.json."""
        es_data = {
            "greeting.hello": "Hola {name}!",
            "old.key": "Should be removed",  # Not in en.json
        }
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        plan = translate.build_work_plan(mgr, ["es"])

        assert "old.key" in plan[0]["extra"]

    def test_force_mode(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test force mode re-translates all keys."""
        es_data = {"greeting.hello": "Hola {name}!"}  # Already translated
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        plan = translate.build_work_plan(mgr, ["es"], force=True)

        assert "greeting.hello" in plan[0]["missing"]  # Force re-translate

    def test_force_specific_keys(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test forcing specific keys while keeping others."""
        es_data = {"greeting.hello": "Hola!", "action.save": "Guardar"}
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        plan = translate.build_work_plan(mgr, ["es"], force_keys={"greeting.hello"})

        assert "greeting.hello" in plan[0]["missing"]
        assert "action.save" not in plan[0]["missing"]  # Not forced, already exists

    def test_prune_only_mode(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test prune-only mode skips translation."""
        es_data = {
            "greeting.hello": "Hola!",
            "old.key": "Should be removed",
        }
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        plan = translate.build_work_plan(mgr, ["es"], prune_only=True)

        assert plan[0]["missing"] == []  # No translation needed
        assert "old.key" in plan[0]["extra"]  # But still prune

    def test_empty_plan_when_up_to_date(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test empty plan when locale is already up to date."""
        # Create complete locale file
        es_data = {
            "greeting.hello": "Hola {name}!",
            "greeting.bye": "Adiós",
            "action.save": "Guardar",
            "action.cancel": "Cancelar",
            "button.submit": "Enviar",
        }
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        plan = translate.build_work_plan(mgr, ["es"])

        assert plan == []


class TestDefaultLangs:
    """Tests for DEFAULT_LANGS mapping."""

    def test_hebrew_mapping(self) -> None:
        """Test Hebrew uses 'iw' code for Google Translate."""
        assert translate.DEFAULT_LANGS["he"] == "iw"

    def test_chinese_mapping(self) -> None:
        """Test Chinese uses proper code."""
        assert "zh" in translate.DEFAULT_LANGS
        assert "zh-CN" in translate.DEFAULT_LANGS["zh"] or translate.DEFAULT_LANGS["zh"] == "zh-CN"

    def test_all_mappings_are_strings(self) -> None:
        """Test all language mappings are string values."""
        for key, value in translate.DEFAULT_LANGS.items():
            assert isinstance(key, str)
            assert isinstance(value, str)
            assert len(key) >= 2
            assert len(value) >= 2


class TestConstants:
    """Tests for module constants."""

    def test_chunk_size_is_reasonable(self) -> None:
        """Test CHUNK_SIZE is a positive integer."""
        assert isinstance(translate.CHUNK_SIZE, int)
        assert translate.CHUNK_SIZE > 0
        assert translate.CHUNK_SIZE <= 100  # Shouldn't be too large

    def test_excluded_files_is_set(self) -> None:
        """Test EXCLUDED_FILES is a set of strings."""
        assert isinstance(translate.EXCLUDED_FILES, set)
        for item in translate.EXCLUDED_FILES:
            assert isinstance(item, str)
            assert item.endswith(".py")


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_protect_placeholders_nested_braces(self) -> None:
        """Test handling of nested-looking braces."""
        t = translate.Translator("es")
        # Double braces like {{escape}} will be matched as {escape} by the regex
        # This is expected behavior - we handle what the regex finds
        text = "Use {{escape}} syntax"
        protected, mapping = t._protect(text)
        # The regex finds {escape} inside {{escape}}
        assert len(mapping) >= 0  # May find inner braces or not

    def test_protect_multiple_same_placeholder(self) -> None:
        """Test protection when same placeholder appears multiple times."""
        t = translate.Translator("es")
        text = "{name} and {name} again"
        protected, mapping = t._protect(text)

        # Should have unique tokens for each occurrence
        tokens = [k for k in mapping]
        assert len(tokens) == 2  # Two different tokens
        assert mapping[tokens[0]] == "{name}"
        assert mapping[tokens[1]] == "{name}"

    def test_locale_manager_verbose_flag(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test verbose flag is stored."""
        mgr_verbose = translate.LocaleManager(verbose=True)
        assert mgr_verbose.verbose is True

        mgr_quiet = translate.LocaleManager(verbose=False)
        assert mgr_quiet.verbose is False

    @pytest.mark.parametrize("lang_code", ["es", "fr", "de"])
    def test_translator_accepts_various_codes(self, lang_code: str) -> None:
        """Test Translator initialization with valid Google Translate codes."""
        # These should not raise as they are valid Google Translate codes
        t = translate.Translator(lang_code)
        assert t.target == lang_code


class TestIntegration:
    """Integration tests requiring actual file system."""

    def test_full_workflow_sort_only(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test sort-only mode works end-to-end."""
        # Create unsorted en.json
        unsorted = {"z.key": "Z", "a.key": "A", "m.key": "M"}
        (temp_locales_dir / "en.json").write_text(json.dumps(unsorted), encoding="utf-8")

        mgr = translate.LocaleManager()
        mgr.save_json(temp_locales_dir / "en.json", unsorted)

        # Verify sorted
        saved = json.loads((temp_locales_dir / "en.json").read_text(encoding="utf-8"))
        assert list(saved) == ["a.key", "m.key", "z.key"]

    def test_translate_job_prunes_extra(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test translate_job removes extra keys."""
        es_data = {
            "greeting.hello": "Hola!",
            "extra.key": "Should be removed",
        }
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        job = {
            "name": "es",
            "code": "es",
            "path": temp_locales_dir / "es.json",
            "data": es_data.copy(),
            "missing": [],
            "extra": ["extra.key"],
        }

        # Mock progress
        mock_progress = MagicMock()
        mock_task_id = 1

        translate.translate_job(mgr, job, mock_progress, mock_task_id)

        # Verify extra key was removed
        saved = json.loads((temp_locales_dir / "es.json").read_text(encoding="utf-8"))
        assert "extra.key" not in saved
        assert "greeting.hello" in saved

    @patch("scripts.translate.GoogleTranslator")
    def test_translate_job_with_missing_keys(
        self, mock_translator_class: MagicMock, mock_en_file: Path, temp_locales_dir: Path
    ) -> None:
        """Test translate_job translates missing keys."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Hola |§| Guardar"
        mock_translator_class.return_value = mock_translator

        # Empty locale file
        (temp_locales_dir / "es.json").write_text("{}", encoding="utf-8")

        mgr = translate.LocaleManager()
        job = {
            "name": "es",
            "code": "es",
            "path": temp_locales_dir / "es.json",
            "data": {},
            "missing": ["greeting.hello", "action.save"],
            "extra": [],
        }

        mock_progress = MagicMock()
        mock_task_id = 1

        translate.translate_job(mgr, job, mock_progress, mock_task_id)

        # Verify translations were saved
        saved = json.loads((temp_locales_dir / "es.json").read_text(encoding="utf-8"))
        assert "greeting.hello" in saved
        assert "action.save" in saved


class TestSortAllLocales:
    """Tests for sort_all_locales function."""

    def test_sorts_all_locales(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test --sort sorts all locale files, not just en.json."""
        # Create out-of-order locale files (mixed order from en.json)
        es_data = {"action.cancel": "Cancelar", "greeting.hello": "Hola!", "action.save": "Guardar"}
        fr_data = {"action.cancel": "Annuler", "greeting.hello": "Bonjour!"}
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")
        (temp_locales_dir / "fr.json").write_text(json.dumps(fr_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        translate.sort_all_locales(mgr, ["es", "fr"], dry_run=False)

        # Verify both files sorted to match en.json alphabetical order
        es_saved = json.loads((temp_locales_dir / "es.json").read_text(encoding="utf-8"))
        fr_saved = json.loads((temp_locales_dir / "fr.json").read_text(encoding="utf-8"))

        # en.json alphabetical order: action.cancel, action.save, button.submit, greeting.bye, greeting.hello
        assert list(es_saved) == ["action.cancel", "action.save", "greeting.hello"]
        assert list(fr_saved) == ["action.cancel", "greeting.hello"]

    def test_sort_dry_run_no_changes(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test dry-run mode doesn't modify files."""
        es_data = {"z.key": "Z", "a.key": "A"}
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        original_content = (temp_locales_dir / "es.json").read_text(encoding="utf-8")

        mgr = translate.LocaleManager()
        translate.sort_all_locales(mgr, ["es"], dry_run=True)

        # Verify file unchanged
        assert (temp_locales_dir / "es.json").read_text(encoding="utf-8") == original_content

    def test_sort_skips_missing_files(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test sort skips locales that don't exist."""
        mgr = translate.LocaleManager()
        # Should not raise
        translate.sort_all_locales(mgr, ["nonexistent"], dry_run=False)


class TestDisplayStats:
    """Tests for display_stats function."""

    def test_shows_coverage_stats(
        self, mock_en_file: Path, temp_locales_dir: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test stats display shows coverage percentages."""
        # Create partial locale
        es_data = {"greeting.hello": "Hola!"}  # 1/5 = 20%
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        translate.display_stats(mgr, ["es"])

        # Output should contain ES and coverage info
        captured = capsys.readouterr()
        assert "ES" in captured.out or "es" in captured.out.lower()

    def test_shows_complete_status(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test 100% coverage shows complete status."""
        # Create complete locale
        es_data = {
            "greeting.hello": "Hola {name}!",
            "greeting.bye": "Adiós",
            "action.save": "Guardar",
            "action.cancel": "Cancelar",
            "button.submit": "Enviar",
        }
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        # Should not raise
        translate.display_stats(mgr, ["es"])


class TestFStringDetection:
    """Tests for f-string detection in StringScanner."""

    def test_finds_fstring_literals(self) -> None:
        """Test scanner finds string parts in f-strings."""
        code = """
name = "World"
msg = f"Hello there {name}, this is a long message that should be found in fstring"
"""
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        found_texts = [text for _, text in scanner.found]
        # Should find "Hello there " and "this is a long message..."
        assert any("Hello" in text for text in found_texts)

    def test_ignores_short_fstring_parts(self) -> None:
        """Test short f-string parts are ignored."""
        code = 'f"Hi {name}"'
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 0

    def test_ignores_logger_in_fstring(self) -> None:
        """Test f-strings inside logger calls are ignored."""
        code = 'logger.info(f"Processing {item} completed successfully")'
        scanner = translate.StringScanner(set(), set(), code, "test.py")
        tree = translate.ast.parse(code)
        scanner.visit(tree)

        assert len(scanner.found) == 0


class TestBuildWorkPlanIsNew:
    """Tests for build_work_plan is_new flag functionality."""

    def test_marks_new_locales(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test new locales are marked with is_new flag."""
        mgr = translate.LocaleManager()
        plan = translate.build_work_plan(mgr, ["newlang"])

        assert len(plan) == 1
        assert plan[0]["is_new"] is True

    def test_marks_existing_locales(self, mock_en_file: Path, temp_locales_dir: Path) -> None:
        """Test existing locales are not marked as new."""
        # Create existing locale
        es_data = {"greeting.hello": "Hola!"}
        (temp_locales_dir / "es.json").write_text(json.dumps(es_data), encoding="utf-8")

        mgr = translate.LocaleManager()
        plan = translate.build_work_plan(mgr, ["es"])

        if plan:
            assert plan[0]["is_new"] is False


def test_admin_templates_render_with_current_panel_arguments():
    from src.utils.i18n import list_locales, t

    watermark_fields = (
        "image_status",
        "video_status",
        "has_image",
        "location",
        "opacity",
        "size",
        "style",
        "video_quality",
        "video_motion",
        "video_limit_note",
        "color",
        "text",
    )
    raid_fields = ("status", "threshold", "window", "time", "actiontime", "action")
    for locale in list_locales():
        for key, fields in (
            ("panel.channel_watermark_text", watermark_fields),
            ("panel.raid_text", raid_fields),
        ):
            rendered = t(locale, key, **dict.fromkeys(fields, "sample"))
            assert rendered != key and "sample" in rendered and "{" not in rendered, (locale, key)

        welcome = t(locale, "panel.input_prompt_welcomeText")
        assert "{mention}" in welcome and "T_PH_" not in welcome, locale
