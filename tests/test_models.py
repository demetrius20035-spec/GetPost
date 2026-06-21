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


if __name__ == "__main__":
    unittest.main()
