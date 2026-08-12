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


class TestSecrets(unittest.TestCase):
    def _workspace(self):
        ws = models.Workspace("W")
        req = models.Request("Login")
        req.auth_type = models.AUTH_BASIC
        req.auth_basic_username = "admin"
        req.auth_basic_password = "PW"
        req.auth_bearer_token = "TOKEN"
        folder = models.Folder("Auth")
        folder.requests.append(req)
        ws.folders.append(folder)
        ws.variables = {"api_key": "KEY", "base_url": "https://api.io", "my_token": "T"}
        ws.set_secret("api_key", True)
        return ws

    def test_export_strips_auth_secrets(self):
        text = share.export_str(self._workspace())
        self.assertNotIn("PW", text)
        self.assertNotIn("TOKEN", text)
        self.assertIn("admin", text)  # логин — не секрет

    def test_export_strips_marked_and_heuristic_variables(self):
        text = share.export_str(self._workspace())
        self.assertNotIn('"KEY"', text)   # помечен вручную
        self.assertNotIn('"T"', text)     # распознан по имени (my_token)
        self.assertIn("https://api.io", text)

    def test_export_reports_what_was_stripped(self):
        env = share.export_dict(self._workspace())
        self.assertFalse(env["contains_secrets"])
        self.assertTrue(env["stripped"])

    def test_include_secrets_keeps_everything(self):
        text = share.export_str(self._workspace(), include_secrets=True)
        self.assertIn("PW", text)
        self.assertIn("KEY", text)
        self.assertTrue(json.loads(text)["contains_secrets"])

    def test_export_does_not_mutate_source(self):
        ws = self._workspace()
        share.export_str(ws)
        self.assertEqual(ws.variables["api_key"], "KEY")
        self.assertEqual(ws.folders[0].requests[0].auth_basic_password, "PW")

    def test_structure_survives_stripping(self):
        kind, obj = share.parse(share.export_str(self._workspace()))
        self.assertEqual(kind, share.KIND_WORKSPACE)
        self.assertEqual(obj.folders[0].requests[0].auth_basic_username, "admin")
        self.assertEqual(obj.folders[0].requests[0].auth_basic_password, "")
        self.assertIn("api_key", obj.variables)  # имя осталось, значение пустое
        self.assertEqual(obj.variables["api_key"], "")

    def test_looks_secret_heuristic(self):
        for name in ("token", "API_KEY", "my-password", "clientSecret", "session_id"):
            self.assertTrue(share.looks_secret(name), name)
        for name in ("base_url", "page", "user_name", "timeout"):
            self.assertFalse(share.looks_secret(name), name)

    def test_no_secrets_no_stripped_key(self):
        ws = models.Workspace("Clean")
        ws.variables = {"base_url": "http://x"}
        self.assertNotIn("stripped", share.export_dict(ws))


class TestFolderHeight(unittest.TestCase):
    def test_height(self):
        self.assertEqual(share.folder_height(models.Folder()), 1)
        f = models.Folder()
        f.folders.append(models.Folder())
        self.assertEqual(share.folder_height(f), 2)


if __name__ == "__main__":
    unittest.main()
