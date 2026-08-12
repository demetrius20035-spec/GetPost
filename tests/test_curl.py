import unittest

from getpost_gui import curl, models


class TestToCurl(unittest.TestCase):
    def test_basic_get(self):
        r = models.Request("g")
        r.url = "https://api.test/items"
        cmd = curl.to_curl(r, {})
        self.assertTrue(cmd.startswith("curl "))
        self.assertIn("https://api.test/items", cmd)
        self.assertNotIn("-X GET", cmd)  # GET по умолчанию не указывается

    def test_params_appended_to_url(self):
        r = models.Request()
        r.url = "https://api.test/x"
        r.params = [{"enabled": True, "key": "a", "value": "1"}]
        cmd = curl.to_curl(r, {})
        self.assertIn("https://api.test/x?a=1", cmd)

    def test_variables_substituted(self):
        r = models.Request()
        r.url = "{{base}}/p"
        cmd = curl.to_curl(r, {"base": "https://h.io"})
        self.assertIn("https://h.io/p", cmd)

    def test_bearer_and_body(self):
        r = models.Request()
        r.method = "POST"
        r.url = "https://api.test"
        r.auth_type = models.AUTH_BEARER
        r.auth_bearer_token = "TOK"
        r.body_type = models.BODY_RAW
        r.body_raw = '{"a":1}'
        cmd = curl.to_curl(r, {})
        self.assertIn("-X POST", cmd)
        self.assertIn("Authorization: Bearer TOK", cmd)
        self.assertIn("--data-raw", cmd)

    def test_flags(self):
        r = models.Request()
        r.url = "https://x"
        r.verify_ssl = False
        r.timeout = 5
        cmd = curl.to_curl(r, {})
        self.assertIn("-k", cmd)
        self.assertIn("--max-time 5", cmd)


class TestFromCurl(unittest.TestCase):
    def test_simple(self):
        r = curl.from_curl("curl https://api.test/x")
        self.assertEqual(r.method, "GET")
        self.assertEqual(r.url, "https://api.test/x")

    def test_method_and_headers(self):
        r = curl.from_curl("curl -X DELETE https://x -H 'X-Key: 1'")
        self.assertEqual(r.method, "DELETE")
        self.assertIn({"enabled": True, "key": "X-Key", "value": "1"}, r.headers)

    def test_query_extracted_to_params(self):
        r = curl.from_curl("curl 'https://x/y?a=1&b=2'")
        self.assertEqual(r.url, "https://x/y")
        self.assertEqual(
            r.params,
            [
                {"enabled": True, "key": "a", "value": "1"},
                {"enabled": True, "key": "b", "value": "2"},
            ],
        )

    def test_basic_auth_flag(self):
        r = curl.from_curl("curl https://x -u bob:secret")
        self.assertEqual(r.auth_type, models.AUTH_BASIC)
        self.assertEqual(r.auth_basic_username, "bob")
        self.assertEqual(r.auth_basic_password, "secret")

    def test_authorization_header_to_bearer(self):
        r = curl.from_curl("curl https://x -H 'Authorization: Bearer ABC'")
        self.assertEqual(r.auth_type, models.AUTH_BEARER)
        self.assertEqual(r.auth_bearer_token, "ABC")
        self.assertEqual(r.headers, [])  # заголовок перенесён в Auth

    def test_authorization_header_basic_decoded(self):
        # base64("u:p") == "dTpw"
        r = curl.from_curl("curl https://x -H 'Authorization: Basic dTpw'")
        self.assertEqual(r.auth_type, models.AUTH_BASIC)
        self.assertEqual(r.auth_basic_username, "u")
        self.assertEqual(r.auth_basic_password, "p")

    def test_json_body(self):
        r = curl.from_curl("curl -X POST https://x --data-raw '{\"a\":1}'")
        self.assertEqual(r.body_type, models.BODY_RAW)
        self.assertEqual(r.body_raw, '{"a":1}')
        self.assertEqual(r.body_raw_lang, models.RAW_JSON)
        self.assertEqual(r.method, "POST")

    def test_urlencoded_data(self):
        r = curl.from_curl("curl https://x -d a=1 -d b=2")
        self.assertEqual(r.body_type, models.BODY_URLENCODED)
        self.assertEqual(len(r.body_form), 2)
        self.assertEqual(r.method, "POST")  # тело без -X → POST

    def test_form_multipart(self):
        r = curl.from_curl("curl https://up -F file=@/tmp/a.png -F note=hi")
        self.assertEqual(r.body_type, models.BODY_FORM_DATA)
        self.assertIn({"enabled": True, "key": "note", "value": "hi"}, r.body_form)

    def test_get_with_data_moves_to_query(self):
        r = curl.from_curl("curl -G https://x --data-urlencode q=hello")
        self.assertEqual(r.method, "GET")
        self.assertIn({"enabled": True, "key": "q", "value": "hello"}, r.params)
        self.assertEqual(r.body_type, models.BODY_NONE)

    def test_flags_parsed(self):
        r = curl.from_curl("curl -k -L --max-time 5 https://x")
        self.assertFalse(r.verify_ssl)
        self.assertTrue(r.follow_redirects)
        self.assertEqual(r.timeout, 5.0)

    def test_line_continuations(self):
        r = curl.from_curl("curl -X POST \\\n  https://x \\\n  -H 'A: b'")
        self.assertEqual(r.method, "POST")
        self.assertEqual(r.url, "https://x")


class TestRoundTrip(unittest.TestCase):
    def test_roundtrip_preserves_core(self):
        r = models.Request("orig")
        r.method = "PUT"
        r.url = "https://api.test/items"
        r.params = [{"enabled": True, "key": "page", "value": "2"}]
        r.headers = [{"enabled": True, "key": "X-Key", "value": "v"}]
        r.body_type = models.BODY_RAW
        r.body_raw = '{"x":1}'
        r.auth_type = models.AUTH_BEARER
        r.auth_bearer_token = "T"

        cmd = curl.to_curl(r, {})
        back = curl.from_curl(cmd)
        self.assertEqual(back.method, "PUT")
        self.assertEqual(back.url, "https://api.test/items")
        self.assertIn({"enabled": True, "key": "page", "value": "2"}, back.params)
        self.assertIn({"enabled": True, "key": "X-Key", "value": "v"}, back.headers)
        self.assertEqual(back.auth_type, models.AUTH_BEARER)
        self.assertEqual(back.auth_bearer_token, "T")
        self.assertEqual(back.body_raw, '{"x":1}')


if __name__ == "__main__":
    unittest.main()
