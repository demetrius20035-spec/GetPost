import unittest

from getpost_gui import models


class TestRequest(unittest.TestCase):
    def test_defaults(self):
        r = models.Request()
        self.assertEqual(r.method, "GET")
        self.assertEqual(r.body_type, models.BODY_NONE)
        self.assertEqual(r.auth_type, models.AUTH_NONE)
        self.assertTrue(r.id)

    def test_roundtrip(self):
        r = models.Request("My Req")
        r.method = "PATCH"
        r.url = "{{base}}/x"
        r.headers = [{"enabled": True, "key": "A", "value": "1"}]
        r.params = [{"enabled": False, "key": "q", "value": "z"}]
        r.body_type = models.BODY_RAW
        r.body_raw = '{"a":1}'
        r.body_raw_lang = models.RAW_JSON
        r.auth_type = models.AUTH_BASIC
        r.auth_basic_username = "u"
        r.auth_basic_password = "p"

        clone = models.Request.from_dict(r.to_dict())
        self.assertEqual(clone.id, r.id)
        self.assertEqual(clone.method, "PATCH")
        self.assertEqual(clone.url, "{{base}}/x")
        self.assertEqual(clone.headers, r.headers)
        self.assertEqual(clone.params, r.params)
        self.assertEqual(clone.body_raw, '{"a":1}')
        self.assertEqual(clone.auth_basic_username, "u")

    def test_invalid_values_coerced(self):
        r = models.Request.from_dict(
            {"method": "TRACE", "body_type": "weird", "auth_type": "oauth"}
        )
        self.assertEqual(r.method, "GET")
        self.assertEqual(r.body_type, models.BODY_NONE)
        self.assertEqual(r.auth_type, models.AUTH_NONE)

    def test_kv_normalization(self):
        r = models.Request.from_dict({"headers": [{"key": "A"}, "garbage", {"value": "v"}]})
        self.assertEqual(
            r.headers,
            [
                {"enabled": True, "key": "A", "value": ""},
                {"enabled": True, "key": "", "value": "v"},
            ],
        )


class TestFolderWorkspace(unittest.TestCase):
    def test_nested_roundtrip(self):
        ws = models.Workspace("WS")
        ws.variables = {"base": "http://a"}
        f1 = models.Folder("F1")
        f2 = models.Folder("F2")
        req = models.Request("R")
        f2.requests.append(req)
        f1.folders.append(f2)
        ws.folders.append(f1)
        ws.requests.append(models.Request("Root Req"))

        clone = models.Workspace.from_dict(ws.to_dict())
        self.assertEqual(clone.name, "WS")
        self.assertEqual(clone.variables, {"base": "http://a"})
        self.assertEqual(clone.folders[0].name, "F1")
        self.assertEqual(clone.folders[0].folders[0].name, "F2")
        self.assertEqual(clone.folders[0].folders[0].requests[0].name, "R")
        self.assertEqual(clone.requests[0].name, "Root Req")

    def test_variables_coerced_to_str(self):
        ws = models.Workspace.from_dict({"variables": {"n": 5, "b": True}})
        self.assertEqual(ws.variables, {"n": "5", "b": "True"})


class TestClone(unittest.TestCase):
    def test_request_clone_new_id(self):
        r = models.Request("R")
        r.method = "POST"
        r.timeout = 9.0
        c = r.clone()
        self.assertNotEqual(c.id, r.id)
        self.assertEqual(c.method, "POST")
        self.assertEqual(c.timeout, 9.0)
        self.assertTrue(c.name.endswith("(копия)"))

    def test_folder_clone_deep_new_ids(self):
        f = models.Folder("F")
        r = models.Request("a")
        sub = models.Folder("S")
        subr = models.Request("b")
        sub.requests.append(subr)
        f.requests.append(r)
        f.folders.append(sub)

        c = f.clone()
        self.assertNotEqual(c.id, f.id)
        self.assertNotEqual(c.requests[0].id, r.id)
        self.assertNotEqual(c.folders[0].id, sub.id)
        self.assertNotEqual(c.folders[0].requests[0].id, subr.id)
        # содержимое сохранено
        self.assertEqual(c.folders[0].requests[0].name, "b")


class TestEnvironments(unittest.TestCase):
    def test_default_env(self):
        ws = models.Workspace("W")
        self.assertEqual(ws.env_names(), ["Default"])
        self.assertEqual(ws.active_env, "Default")
        self.assertEqual(ws.variables, {})

    def test_variables_property_targets_active(self):
        ws = models.Workspace("W")
        ws.variables = {"a": "1"}
        ws.add_env("Prod")
        ws.set_active_env("Prod")
        ws.variables = {"a": "2"}
        self.assertEqual(ws.environments["Default"], {"a": "1"})
        self.assertEqual(ws.environments["Prod"], {"a": "2"})

    def test_add_rename_remove(self):
        ws = models.Workspace("W")
        self.assertTrue(ws.add_env("Stage"))
        self.assertFalse(ws.add_env("Stage"))  # дубликат
        ws.set_active_env("Stage")
        self.assertTrue(ws.rename_env("Stage", "Staging"))
        self.assertEqual(ws.active_env, "Staging")
        self.assertIn("Staging", ws.env_names())
        self.assertTrue(ws.remove_env("Staging"))
        self.assertNotIn("Staging", ws.env_names())

    def test_cannot_remove_last_env(self):
        ws = models.Workspace("W")
        self.assertFalse(ws.remove_env("Default"))

    def test_roundtrip(self):
        ws = models.Workspace("W")
        ws.variables = {"base": "dev"}
        ws.add_env("Prod")
        ws.set_active_env("Prod")
        ws.variables = {"base": "prod"}
        clone = models.Workspace.from_dict(ws.to_dict())
        self.assertEqual(clone.env_names(), ["Default", "Prod"])
        self.assertEqual(clone.active_env, "Prod")
        self.assertEqual(clone.variables, {"base": "prod"})

    def test_legacy_migration(self):
        ws = models.Workspace.from_dict({"name": "L", "variables": {"k": "v"}})
        self.assertEqual(ws.env_names(), ["Default"])
        self.assertEqual(ws.variables, {"k": "v"})


if __name__ == "__main__":
    unittest.main()
