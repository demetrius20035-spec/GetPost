import json
import unittest

from getpost_gui import models, share


class TestExport(unittest.TestCase):
    def test_envelope_request(self):
        r = models.Request("R")
        env = share.export_dict(r)
        self.assertEqual(env[share.FORMAT_KEY], share.FORMAT_VERSION)
        self.assertEqual(env["type"], share.KIND_REQUEST)
        self.assertEqual(env["data"]["name"], "R")
        self.assertIn("exported_at", env)

    def test_detect_kind(self):
        self.assertEqual(share.detect_kind(models.Workspace()), share.KIND_WORKSPACE)
        self.assertEqual(share.detect_kind(models.Folder()), share.KIND_FOLDER)
        self.assertEqual(share.detect_kind(models.Request()), share.KIND_REQUEST)

    def test_detect_kind_bad(self):
        with self.assertRaises(TypeError):
            share.detect_kind(object())


class TestParse(unittest.TestCase):
    def test_request_roundtrip_new_id(self):
        r = models.Request("R")
        r.method = "POST"
        kind, obj = share.parse(share.export_str(r))
        self.assertEqual(kind, share.KIND_REQUEST)
        self.assertEqual(obj.method, "POST")
        self.assertNotEqual(obj.id, r.id)

    def test_folder_deep_new_ids(self):
        f = models.Folder("F")
        sub = models.Folder("S")
        sub.requests.append(models.Request("a"))
        f.folders.append(sub)
        kind, obj = share.parse(share.export_str(f))
        self.assertEqual(kind, share.KIND_FOLDER)
        self.assertNotEqual(obj.id, f.id)
        self.assertNotEqual(obj.folders[0].id, sub.id)
        self.assertNotEqual(obj.folders[0].requests[0].id, sub.requests[0].id)

    def test_workspace_roundtrip(self):
        ws = models.Workspace("W")
        ws.variables = {"k": "v"}
        ws.add_env("Prod")
        kind, obj = share.parse(share.export_str(ws))
        self.assertEqual(kind, share.KIND_WORKSPACE)
        self.assertNotEqual(obj.id, ws.id)
        self.assertEqual(obj.env_names(), ["Default", "Prod"])

    def test_no_reassign_option(self):
        r = models.Request("R")
        kind, obj = share.parse(share.export_str(r), reassign=False)
        self.assertEqual(obj.id, r.id)

    def test_raw_workspace_fallback(self):
        ws = models.Workspace("Raw")
        raw = json.dumps(ws.to_dict())
        kind, obj = share.parse(raw)
        self.assertEqual(kind, share.KIND_WORKSPACE)
        self.assertEqual(obj.name, "Raw")

    def test_invalid_rejected(self):
        with self.assertRaises(ValueError):
            share.parse('{"foo": 1}')

    def test_not_json(self):
        with self.assertRaises(ValueError):
            share.parse("[]")

    def test_bad_envelope_type(self):
        bad = json.dumps({share.FORMAT_KEY: "1.0", "type": "alien", "data": {}})
        with self.assertRaises(ValueError):
            share.parse(bad)


class TestFolderHeight(unittest.TestCase):
    def test_height(self):
        self.assertEqual(share.folder_height(models.Folder()), 1)
        f = models.Folder()
        f.folders.append(models.Folder())
        self.assertEqual(share.folder_height(f), 2)


if __name__ == "__main__":
    unittest.main()
