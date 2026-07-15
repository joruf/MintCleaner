import importlib.util
import os
import tempfile
import unittest
from unittest import mock


SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "mint-cleaner.py")
)

SPEC = importlib.util.spec_from_file_location("mint_cleaner", SCRIPT_PATH)
MINT_CLEANER = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MINT_CLEANER)


class DummyVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class BuildPlanConfigCacheTests(unittest.TestCase):
    def test_build_plan_includes_config_cache_patterns(self):
        app = type("DummyApp", (), {})()
        app.var_user_cache = DummyVar(False)
        app.var_thumbnails = DummyVar(False)
        app.var_trash = DummyVar(False)
        app.var_firefox = DummyVar(False)
        app.var_chrome = DummyVar(False)
        app.var_flatpak_app_cache = DummyVar(False)
        app.var_config_app_caches = DummyVar(True)
        app.var_dev_tool_caches = DummyVar(False)
        app.var_user_lang_tool_caches = DummyVar(False)
        app.var_flatpak_user = DummyVar(False)
        app.var_flatpak_repair_user = DummyVar(False)
        app.var_tmp = DummyVar(False)
        app.var_flatpak_syscache = DummyVar(False)
        app.var_apt_cache = DummyVar(False)
        app.var_system_misc_caches = DummyVar(False)
        app.var_system_extra_caches = DummyVar(False)
        app.var_flatpak_repair_system = DummyVar(False)
        app.var_apt = DummyVar(False)
        app.var_journal = DummyVar(False)
        app.var_old_kernels = DummyVar(False)
        app.journal_retention = DummyVar("3d")
        app.patterns = {
            "config_app_caches": MINT_CLEANER.CONFIG_CACHE_PATTERNS,
            "dev_tool_caches": MINT_CLEANER.DEV_TOOL_CACHE_PATTERNS,
            "user_lang_tool_caches": MINT_CLEANER.USER_LANG_TOOL_CACHE_PATTERNS,
            "system_misc_caches": MINT_CLEANER.SYSTEM_MISC_CACHE_PATTERNS,
            "system_extra_caches": MINT_CLEANER.SYSTEM_EXTRA_CACHE_PATTERNS,
        }
        app.log = None

        plan = MINT_CLEANER.MintCleanerApp.build_plan(app)

        self.assertEqual(plan["user_cmds"], [])
        self.assertEqual(plan["root_rm_patterns"], [])
        self.assertEqual(plan["root_cmds"], [])
        for pattern in MINT_CLEANER.CONFIG_CACHE_PATTERNS:
            self.assertIn(pattern, plan["user_py_delete"])

    def test_build_plan_includes_general_linux_cache_patterns(self):
        app = type("DummyApp", (), {})()
        app.var_user_cache = DummyVar(False)
        app.var_thumbnails = DummyVar(False)
        app.var_trash = DummyVar(False)
        app.var_firefox = DummyVar(False)
        app.var_chrome = DummyVar(False)
        app.var_flatpak_app_cache = DummyVar(False)
        app.var_config_app_caches = DummyVar(False)
        app.var_dev_tool_caches = DummyVar(True)
        app.var_user_lang_tool_caches = DummyVar(False)
        app.var_flatpak_user = DummyVar(False)
        app.var_flatpak_repair_user = DummyVar(False)
        app.var_tmp = DummyVar(False)
        app.var_flatpak_syscache = DummyVar(False)
        app.var_apt_cache = DummyVar(False)
        app.var_system_misc_caches = DummyVar(True)
        app.var_system_extra_caches = DummyVar(False)
        app.var_flatpak_repair_system = DummyVar(False)
        app.var_apt = DummyVar(False)
        app.var_journal = DummyVar(False)
        app.var_old_kernels = DummyVar(False)
        app.journal_retention = DummyVar("3d")
        app.patterns = {
            "config_app_caches": MINT_CLEANER.CONFIG_CACHE_PATTERNS,
            "dev_tool_caches": MINT_CLEANER.DEV_TOOL_CACHE_PATTERNS,
            "user_lang_tool_caches": MINT_CLEANER.USER_LANG_TOOL_CACHE_PATTERNS,
            "system_misc_caches": MINT_CLEANER.SYSTEM_MISC_CACHE_PATTERNS,
            "system_extra_caches": MINT_CLEANER.SYSTEM_EXTRA_CACHE_PATTERNS,
        }
        app.log = None

        plan = MINT_CLEANER.MintCleanerApp.build_plan(app)

        for pattern in MINT_CLEANER.DEV_TOOL_CACHE_PATTERNS:
            self.assertIn(pattern, plan["user_py_delete"])
        for pattern in MINT_CLEANER.SYSTEM_MISC_CACHE_PATTERNS:
            self.assertIn(pattern, plan["root_rm_patterns"])

    def test_build_plan_includes_new_user_and_system_extra_caches(self):
        app = type("DummyApp", (), {})()
        app.var_user_cache = DummyVar(False)
        app.var_thumbnails = DummyVar(False)
        app.var_trash = DummyVar(False)
        app.var_firefox = DummyVar(False)
        app.var_chrome = DummyVar(False)
        app.var_flatpak_app_cache = DummyVar(False)
        app.var_config_app_caches = DummyVar(False)
        app.var_dev_tool_caches = DummyVar(False)
        app.var_user_lang_tool_caches = DummyVar(True)
        app.var_flatpak_user = DummyVar(False)
        app.var_flatpak_repair_user = DummyVar(False)
        app.var_tmp = DummyVar(False)
        app.var_flatpak_syscache = DummyVar(False)
        app.var_apt_cache = DummyVar(False)
        app.var_system_misc_caches = DummyVar(False)
        app.var_system_extra_caches = DummyVar(True)
        app.var_flatpak_repair_system = DummyVar(False)
        app.var_apt = DummyVar(False)
        app.var_journal = DummyVar(False)
        app.var_old_kernels = DummyVar(False)
        app.journal_retention = DummyVar("3d")
        app.patterns = {
            "config_app_caches": MINT_CLEANER.CONFIG_CACHE_PATTERNS,
            "dev_tool_caches": MINT_CLEANER.DEV_TOOL_CACHE_PATTERNS,
            "user_lang_tool_caches": MINT_CLEANER.USER_LANG_TOOL_CACHE_PATTERNS,
            "system_misc_caches": MINT_CLEANER.SYSTEM_MISC_CACHE_PATTERNS,
            "system_extra_caches": MINT_CLEANER.SYSTEM_EXTRA_CACHE_PATTERNS,
        }
        app.log = None

        plan = MINT_CLEANER.MintCleanerApp.build_plan(app)

        for pattern in MINT_CLEANER.USER_LANG_TOOL_CACHE_PATTERNS:
            self.assertIn(pattern, plan["user_py_delete"])
        for pattern in MINT_CLEANER.SYSTEM_EXTRA_CACHE_PATTERNS:
            self.assertIn(pattern, plan["root_rm_patterns"])


class TrashPathsTests(unittest.TestCase):
    def test_trash_paths_fallback_moves_file_and_writes_trashinfo(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            file_path = os.path.join(tmp_home, "to-trash.txt")
            with open(file_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("content")

            with mock.patch.dict(os.environ, {"HOME": tmp_home}, clear=False):
                with mock.patch.object(MINT_CLEANER, "exists_in_path", return_value=False):
                    moved, logs = MINT_CLEANER.trash_paths([file_path])

            self.assertEqual(moved, 1)
            self.assertIn("Moved to Trash:", logs)
            self.assertFalse(os.path.exists(file_path))

            trashed_file = os.path.join(tmp_home, ".local/share/Trash/files", "to-trash.txt")
            info_file = os.path.join(tmp_home, ".local/share/Trash/info", "to-trash.txt.trashinfo")
            self.assertTrue(os.path.isfile(trashed_file))
            self.assertTrue(os.path.isfile(info_file))

            with open(info_file, "r", encoding="utf-8") as info_handle:
                info_content = info_handle.read()
            self.assertIn("[Trash Info]", info_content)
            self.assertIn("Path=", info_content)
            self.assertIn("DeletionDate=", info_content)

    def test_trash_paths_skips_entries_inside_trash_root(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            trash_files_dir = os.path.join(tmp_home, ".local/share/Trash/files")
            os.makedirs(trash_files_dir, exist_ok=True)
            in_trash_file = os.path.join(trash_files_dir, "already-there.txt")
            with open(in_trash_file, "w", encoding="utf-8") as file_handle:
                file_handle.write("content")

            with mock.patch.dict(os.environ, {"HOME": tmp_home}, clear=False):
                moved, logs = MINT_CLEANER.trash_paths([in_trash_file])

            self.assertEqual(moved, 0)
            self.assertEqual(logs, "")
            self.assertTrue(os.path.exists(in_trash_file))

    def test_trash_paths_uses_gio_when_available(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            file_path = os.path.join(tmp_home, "gio-trash.txt")
            with open(file_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("content")

            completed = mock.Mock()
            completed.returncode = 0
            completed.stdout = ""

            with mock.patch.dict(os.environ, {"HOME": tmp_home}, clear=False):
                with mock.patch.object(MINT_CLEANER, "exists_in_path", return_value=True):
                    with mock.patch.object(MINT_CLEANER.subprocess, "run", return_value=completed) as run_mock:
                        moved, logs = MINT_CLEANER.trash_paths([file_path])

            self.assertEqual(moved, 1)
            self.assertIn("Trashed:", logs)
            run_mock.assert_called_once_with(
                ["gio", "trash", file_path],
                text=True,
                stdout=mock.ANY,
                stderr=mock.ANY,
            )


if __name__ == "__main__":
    unittest.main()
