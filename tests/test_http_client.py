import unittest

from getpost_gui import http_client, models


def build(req, variables=None):
    return http_client.build_request_kwargs(req, variables or {})


class TestBuildRequestKwargs(unittest.TestCase):
    def test_method_and_url_substitution(self):
        r = models.Request()
        r.method = "get"  # должно нормализоваться в верхний регистр
        r.url = "  {{base}}/items  "
        method, url, _ = build(r, {"base": "https://api.test"})
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.test/items")

    def test_params_and_headers_filtered(self):
        r = models.Request()
        r.url = "http://x"
        r.params = [
            {"enabled": True, "key": "a", "value": "{{v}}"},
            {"enabled": False, "key": "skip", "value": "1"},
            {"enabled": True, "key": "", "value": "noкey"},
        ]
        r.headers = [{"enabled": True, "key": "X", "value": "1"}]
        _, _, kw = build(r, {"v": "10"})
        self.assertEqual(kw["params"], [("a", "10")])
        self.assertEqual(kw["headers"], {"X": "1"})

    def test_raw_json_sets_content_type(self):
        r = models.Request()
        r.method = "POST"
        r.url = "http://x"
        r.body_type = models.BODY_RAW
        r.body_raw = '{"k": 1}'
        r.body_raw_lang = models.RAW_JSON
        _, _, kw = build(r)
        self.assertEqual(kw["data"], b'{"k": 1}')
        self.assertTrue(kw["headers"]["Content-Type"].startswith("application/json"))

    def test_raw_does_not_override_explicit_content_type(self):
        r = models.Request()
        r.method = "POST"
        r.url = "http://x"
        r.headers = [{"enabled": True, "key": "Content-Type", "value": "text/csv"}]
        r.body_type = models.BODY_RAW
        r.body_raw = "a,b"
        r.body_raw_lang = models.RAW_TEXT
        _, _, kw = build(r)
        self.assertEqual(kw["headers"]["Content-Type"], "text/csv")

    def test_urlencoded(self):
        r = models.Request()
        r.method = "POST"
        r.url = "http://x"
        r.body_type = models.BODY_URLENCODED
        r.body_form = [
            {"enabled": True, "key": "a", "value": "1"},
            {"enabled": False, "key": "b", "value": "2"},
        ]
        _, _, kw = build(r)
        self.assertEqual(kw["data"], [("a", "1")])
        self.assertNotIn("files", kw)

    def test_form_data_multipart(self):
        r = models.Request()
        r.method = "POST"
        r.url = "http://x"
        r.body_type = models.BODY_FORM_DATA
        r.body_form = [{"enabled": True, "key": "field", "value": "val"}]
        _, _, kw = build(r)
        self.assertEqual(kw["files"], [("field", (None, "val"))])

    def test_bearer_auth_header(self):
        r = models.Request()
        r.url = "http://x"
        r.auth_type = models.AUTH_BEARER
        r.auth_bearer_token = "{{tok}}"
        _, _, kw = build(r, {"tok": "abc"})
        self.assertEqual(kw["headers"]["Authorization"], "Bearer abc")

    def test_bearer_does_not_override_existing_auth_header(self):
        r = models.Request()
        r.url = "http://x"
        r.headers = [{"enabled": True, "key": "Authorization", "value": "Custom"}]
        r.auth_type = models.AUTH_BEARER
        r.auth_bearer_token = "abc"
        _, _, kw = build(r)
        self.assertEqual(kw["headers"]["Authorization"], "Custom")

    def test_basic_auth(self):
        from requests.auth import HTTPBasicAuth

        r = models.Request()
        r.url = "http://x"
        r.auth_type = models.AUTH_BASIC
        r.auth_basic_username = "u"
        r.auth_basic_password = "p"
        _, _, kw = build(r)
        self.assertIsInstance(kw["auth"], HTTPBasicAuth)
        self.assertEqual(kw["auth"].username, "u")
        self.assertEqual(kw["auth"].password, "p")

    def test_get_with_none_body_has_no_data(self):
        r = models.Request()
        r.url = "http://x"
        r.body_type = models.BODY_NONE
        _, _, kw = build(r)
        self.assertNotIn("data", kw)
        self.assertNotIn("files", kw)

    def test_empty_url_raises_on_perform(self):
        with self.assertRaises(ValueError):
            http_client.perform_prepared("GET", "", {})


class TestResponseData(unittest.TestCase):
    def test_status_line(self):
        rd = http_client.ResponseData(
            404, "Not Found", [], "", 1.0, 0, "http://x", "", False
        )
        self.assertEqual(rd.status_line, "404 Not Found")

    def test_status_line_no_reason(self):
        rd = http_client.ResponseData(200, "", [], "", 1.0, 0, "http://x", "", True)
        self.assertEqual(rd.status_line, "200")


if __name__ == "__main__":
    unittest.main()
