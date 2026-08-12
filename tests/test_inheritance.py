import unittest

from getpost_gui import inheritance, models


def folder(name, base_url="", headers=None, auth=None):
    f = models.Folder(name)
    f.base_url = base_url
    f.headers = headers or []
    if auth:
        models.auth_from_dict(f, auth)
    return f


def header(key, value, enabled=True):
    return {"enabled": enabled, "key": key, "value": value}


class TestFindChain(unittest.TestCase):
    def setUp(self):
        self.ws = models.Workspace("W")
        self.outer = models.Folder("Outer")
        self.inner = models.Folder("Inner")
        self.deep_req = models.Request("Deep")
        self.root_req = models.Request("Root")
        self.inner.requests.append(self.deep_req)
        self.outer.folders.append(self.inner)
        self.ws.folders.append(self.outer)
        self.ws.requests.append(self.root_req)

    def test_chain_for_nested(self):
        chain = inheritance.find_chain(self.ws, self.deep_req)
        self.assertEqual([f.name for f in chain], ["Outer", "Inner"])

    def test_chain_for_root_request(self):
        self.assertEqual(inheritance.find_chain(self.ws, self.root_req), [])

    def test_unknown_request(self):
        self.assertIsNone(inheritance.find_chain(self.ws, models.Request("Alien")))


class TestJoinUrl(unittest.TestCase):
    def test_join_variants(self):
        self.assertEqual(inheritance.join_url("https://a.io/v1", "users"), "https://a.io/v1/users")
        self.assertEqual(inheritance.join_url("https://a.io/v1/", "/users"), "https://a.io/v1/users")
        self.assertEqual(inheritance.join_url("", "users"), "users")
        self.assertEqual(inheritance.join_url("https://a.io", ""), "https://a.io")

    def test_is_absolute(self):
        self.assertTrue(inheritance.is_absolute("http://x"))
        self.assertTrue(inheritance.is_absolute("HTTPS://X"))
        self.assertFalse(inheritance.is_absolute("/users"))
        self.assertFalse(inheritance.is_absolute("{{base}}/x"))


class TestResolveUrl(unittest.TestCase):
    def test_base_url_applied(self):
        f = folder("API", base_url="https://api.test/v1")
        req = models.Request("R")
        req.url = "users"
        self.assertEqual(inheritance.resolve(req, [f]).url, "https://api.test/v1/users")

    def test_nearest_base_url_wins(self):
        outer = folder("Outer", base_url="https://outer.io")
        inner = folder("Inner", base_url="https://inner.io")
        req = models.Request("R")
        req.url = "x"
        self.assertEqual(inheritance.resolve(req, [outer, inner]).url, "https://inner.io/x")

    def test_outer_used_when_inner_empty(self):
        outer = folder("Outer", base_url="https://outer.io")
        inner = folder("Inner")
        req = models.Request("R")
        req.url = "x"
        self.assertEqual(inheritance.resolve(req, [outer, inner]).url, "https://outer.io/x")

    def test_absolute_url_untouched(self):
        f = folder("API", base_url="https://api.test")
        req = models.Request("R")
        req.url = "https://other.io/x"
        self.assertEqual(inheritance.resolve(req, [f]).url, "https://other.io/x")

    def test_variable_yielding_absolute_url_untouched(self):
        f = folder("API", base_url="https://api.test")
        req = models.Request("R")
        req.url = "{{host}}/x"
        resolved = inheritance.resolve(req, [f], {"host": "https://var.io"})
        self.assertEqual(resolved.url, "{{host}}/x")

    def test_relative_variable_url_gets_base(self):
        f = folder("API", base_url="https://api.test")
        req = models.Request("R")
        req.url = "{{path}}"
        resolved = inheritance.resolve(req, [f], {"path": "items"})
        self.assertEqual(resolved.url, "https://api.test/{{path}}")

    def test_no_chain_returns_same_object(self):
        req = models.Request("R")
        self.assertIs(inheritance.resolve(req, []), req)


class TestResolveHeaders(unittest.TestCase):
    def test_folder_headers_merged(self):
        outer = folder("Outer", headers=[header("X-Outer", "1")])
        inner = folder("Inner", headers=[header("X-Inner", "2")])
        req = models.Request("R")
        req.headers = [header("X-Req", "3")]
        merged = {h["key"]: h["value"] for h in inheritance.resolve(req, [outer, inner]).headers}
        self.assertEqual(merged, {"X-Outer": "1", "X-Inner": "2", "X-Req": "3"})

    def test_request_overrides_folder(self):
        f = folder("API", headers=[header("Accept", "application/json")])
        req = models.Request("R")
        req.headers = [header("Accept", "text/plain")]
        resolved = inheritance.resolve(req, [f])
        accepts = [h["value"] for h in resolved.headers if h["key"].lower() == "accept"]
        self.assertEqual(accepts, ["text/plain"])

    def test_inner_folder_overrides_outer(self):
        outer = folder("Outer", headers=[header("X-Env", "prod")])
        inner = folder("Inner", headers=[header("x-env", "stage")])
        resolved = inheritance.resolve(models.Request("R"), [outer, inner])
        values = [h["value"] for h in resolved.headers]
        self.assertEqual(values, ["stage"])  # регистр имени не важен

    def test_source_request_not_modified(self):
        f = folder("API", headers=[header("X-Folder", "1")])
        req = models.Request("R")
        req.headers = [header("X-Req", "2")]
        inheritance.resolve(req, [f])
        self.assertEqual([h["key"] for h in req.headers], ["X-Req"])


class TestResolveAuth(unittest.TestCase):
    def test_inherit_takes_folder_auth(self):
        f = folder("API", auth={"auth_type": models.AUTH_BEARER, "auth_bearer_token": "T"})
        req = models.Request("R")
        req.auth_type = models.AUTH_INHERIT
        resolved = inheritance.resolve(req, [f])
        self.assertEqual(resolved.auth_type, models.AUTH_BEARER)
        self.assertEqual(resolved.auth_bearer_token, "T")

    def test_nearest_folder_auth_wins(self):
        outer = folder("Outer", auth={"auth_type": models.AUTH_BEARER, "auth_bearer_token": "OUT"})
        inner = folder("Inner", auth={"auth_type": models.AUTH_BASIC,
                                      "auth_basic_username": "u", "auth_basic_password": "p"})
        req = models.Request("R")
        req.auth_type = models.AUTH_INHERIT
        resolved = inheritance.resolve(req, [outer, inner])
        self.assertEqual(resolved.auth_type, models.AUTH_BASIC)
        self.assertEqual(resolved.auth_basic_username, "u")

    def test_own_auth_not_replaced(self):
        f = folder("API", auth={"auth_type": models.AUTH_BEARER, "auth_bearer_token": "FOLDER"})
        req = models.Request("R")
        req.auth_type = models.AUTH_BEARER
        req.auth_bearer_token = "OWN"
        self.assertEqual(inheritance.resolve(req, [f]).auth_bearer_token, "OWN")

    def test_explicit_none_not_replaced(self):
        f = folder("API", auth={"auth_type": models.AUTH_BEARER, "auth_bearer_token": "FOLDER"})
        req = models.Request("R")
        req.auth_type = models.AUTH_NONE
        self.assertEqual(inheritance.resolve(req, [f]).auth_type, models.AUTH_NONE)

    def test_inherit_without_folder_auth_becomes_none(self):
        req = models.Request("R")
        req.auth_type = models.AUTH_INHERIT
        self.assertEqual(inheritance.resolve(req, [folder("Plain")]).auth_type, models.AUTH_NONE)


class TestResolveIn(unittest.TestCase):
    def test_resolve_in_workspace(self):
        ws = models.Workspace("W")
        f = folder("API", base_url="https://api.test")
        req = models.Request("R")
        req.url = "ping"
        f.requests.append(req)
        ws.folders.append(f)
        resolved, chain = inheritance.resolve_in(ws, req)
        self.assertEqual(resolved.url, "https://api.test/ping")
        self.assertEqual(len(chain), 1)


class TestDescribe(unittest.TestCase):
    def test_describes_inherited_pieces(self):
        f = folder("API", base_url="https://api.test",
                   headers=[header("X-A", "1")],
                   auth={"auth_type": models.AUTH_BEARER, "auth_bearer_token": "T"})
        req = models.Request("R")
        req.auth_type = models.AUTH_INHERIT
        notes = " ".join(inheritance.describe(req, [f]))
        self.assertIn("базовый URL", notes)
        self.assertIn("заголовки", notes)
        self.assertIn("авторизация", notes)

    def test_no_chain_no_notes(self):
        self.assertEqual(inheritance.describe(models.Request("R"), []), [])


class TestFolderSettings(unittest.TestCase):
    def test_has_settings(self):
        self.assertFalse(models.Folder("Plain").has_settings())
        self.assertTrue(folder("A", base_url="https://x").has_settings())
        self.assertTrue(folder("B", headers=[header("X", "1")]).has_settings())
        self.assertTrue(
            folder("C", auth={"auth_type": models.AUTH_BEARER}).has_settings()
        )

    def test_folder_roundtrip_keeps_settings(self):
        f = folder("API", base_url="https://api.test", headers=[header("X-A", "1")],
                   auth={"auth_type": models.AUTH_BEARER, "auth_bearer_token": "T"})
        clone = models.Folder.from_dict(f.to_dict())
        self.assertEqual(clone.base_url, "https://api.test")
        self.assertEqual(clone.headers, f.headers)
        self.assertEqual(clone.auth_type, models.AUTH_BEARER)
        self.assertEqual(clone.auth_bearer_token, "T")


if __name__ == "__main__":
    unittest.main()
