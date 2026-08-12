import tempfile
import unittest
from pathlib import Path

from getpost_gui import models
from getpost_gui.storage import Storage, build_default_workspace


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="getpost_test_")
        self.storage = Storage(self.tmp)

    def test_dirs_created(self):
        self.assertTrue((Path(self.tmp) / "workspaces").is_dir())

    def test_save_load_workspace(self):
        ws = models.Workspace("WS")
        ws.requests.append(models.Request("R"))
        self.storage.save_workspace(ws)

        loaded = self.storage.load_all_workspaces()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "WS")
        self.assertEqual(loaded[0].requests[0].name, "R")
        self.assertTrue(loaded[0].file_path)

    def test_filename_is_id_based(self):
        ws = models.Workspace("Name With Spaces/Slash")
        self.storage.save_workspace(ws)
        expected = Path(self.tmp) / "workspaces" / f"{ws.id}.json"
        self.assertTrue(expected.exists())

    def test_rename_does_not_duplicate(self):
        ws = self.storage.create_workspace("A")
        ws.name = "B"
        self.storage.save_workspace(ws)
        self.assertEqual(len(self.storage.list_workspace_files()), 1)

    def test_settings(self):
        self.storage.save_settings({"last_workspace_id": "abc"})
        self.assertEqual(self.storage.load_settings()["last_workspace_id"], "abc")

    def test_settings_invalid_returns_empty(self):
        (Path(self.tmp) / "settings.json").write_text("not json", encoding="utf-8")
        self.assertEqual(self.storage.load_settings(), {})

    def test_corrupt_workspace_skipped(self):
        good = models.Workspace("Good")
        self.storage.save_workspace(good)
        (Path(self.tmp) / "workspaces" / "broken.json").write_text("{bad", encoding="utf-8")
        loaded = self.storage.load_all_workspaces()
        self.assertEqual([w.name for w in loaded], ["Good"])

    def test_delete(self):
        ws = self.storage.create_workspace("X")
        self.storage.delete_workspace(ws)
        self.assertEqual(self.storage.load_all_workspaces(), [])

    def test_reset(self):
        self.storage.create_workspace("X")
        self.storage.save_settings({"k": "v"})
        self.storage.reset()
        self.assertEqual(self.storage.load_all_workspaces(), [])
        self.assertEqual(self.storage.load_settings(), {})

    def test_default_workspace(self):
        ws = build_default_workspace()
        self.assertIn("base_url", ws.variables)
        self.assertTrue(ws.requests)

    def test_unicode_preserved(self):
        ws = models.Workspace("Прострaнство")
        r = models.Request("Запрос")
        r.body_raw = '{"город":"Москва"}'
        ws.requests.append(r)
        path = self.storage.save_workspace(ws)
        raw = Path(path).read_text(encoding="utf-8")
        self.assertIn("Москва", raw)  # ensure_ascii=False
        reloaded = self.storage.load_all_workspaces()[0]
        self.assertEqual(reloaded.requests[0].body_raw, '{"город":"Москва"}')


if __name__ == "__main__":
    unittest.main()
