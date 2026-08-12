import unittest

from getpost_gui import codegen, models


def sample_request():
    req = models.Request("Login")
    req.method = "POST"
    req.url = "{{base}}/login"
    req.headers = [{"enabled": True, "key": "X-Key", "value": "k1"}]
    req.params = [{"enabled": True, "key": "v", "value": "2"}]
    req.body_type = models.BODY_RAW
    req.body_raw = '{"user": "bob"}'
    req.body_raw_lang = models.RAW_JSON
    return req


VARS = {"base": "https://api.test"}


class TestPython(unittest.TestCase):
    def setUp(self):
        self.code = codegen.generate(codegen.LANG_PYTHON, sample_request(), VARS)

    def test_is_valid_python(self):
        compile(self.code, "generated.py", "exec")

    def test_contains_essentials(self):
        self.assertIn("import requests", self.code)
        self.assertIn("https://api.test/login", self.code)
        self.assertIn("X-Key", self.code)
        self.assertIn("json=json_body", self.code)

    def test_basic_auth_rendered(self):
        req = sample_request()
        req.auth_type = models.AUTH_BASIC
        req.auth_basic_username = "u"
        req.auth_basic_password = "p"
        code = codegen.generate(codegen.LANG_PYTHON, req, VARS)
        compile(code, "generated.py", "exec")
        self.assertIn("auth=(", code)

    def test_form_urlencoded(self):
        req = models.Request("f")
        req.method = "POST"
        req.url = "http://x"
        req.body_type = models.BODY_URLENCODED
        req.body_form = [{"enabled": True, "key": "a", "value": "1"}]
        code = codegen.generate(codegen.LANG_PYTHON, req, {})
        compile(code, "generated.py", "exec")
        self.assertIn("data=data", code)

    def test_options_reflected(self):
        req = sample_request()
        req.verify_ssl = False
        req.follow_redirects = False
        code = codegen.generate(codegen.LANG_PYTHON, req, VARS)
        self.assertIn("verify=False", code)
        self.assertIn("allow_redirects=False", code)

    def test_invalid_json_body_falls_back_to_data(self):
        req = sample_request()
        req.body_raw = "{not json"
        code = codegen.generate(codegen.LANG_PYTHON, req, VARS)
        compile(code, "generated.py", "exec")
        self.assertIn("data=data", code)


class TestJavaScript(unittest.TestCase):
    def test_fetch_snippet(self):
        code = codegen.generate(codegen.LANG_JS, sample_request(), VARS)
        self.assertIn("await fetch(", code)
        # Параметры уходят в URL.
        self.assertIn("https://api.test/login?v=2", code)
        self.assertIn('"X-Key"', code)

    def test_basic_auth_becomes_header(self):
        req = sample_request()
        req.auth_type = models.AUTH_BASIC
        req.auth_basic_username = "u"
        req.auth_basic_password = "p"
        code = codegen.generate(codegen.LANG_JS, req, VARS)
        self.assertIn("Authorization", code)
        self.assertIn("Basic ", code)

    def test_urlencoded_uses_urlsearchparams(self):
        req = models.Request("f")
        req.method = "POST"
        req.url = "http://x"
        req.body_type = models.BODY_URLENCODED
        req.body_form = [{"enabled": True, "key": "a", "value": "1"}]
        code = codegen.generate(codegen.LANG_JS, req, {})
        self.assertIn("URLSearchParams", code)


class TestHttpie(unittest.TestCase):
    def test_command(self):
        code = codegen.generate(codegen.LANG_HTTPIE, sample_request(), VARS)
        self.assertIn("http", code)
        self.assertIn("POST", code)
        self.assertIn("--json", code)
        self.assertIn("X-Key:k1", code)

    def test_flags(self):
        req = sample_request()
        req.verify_ssl = False
        req.timeout = 5
        code = codegen.generate(codegen.LANG_HTTPIE, req, VARS)
        self.assertIn("--verify=no", code)
        self.assertIn("--timeout=5", code)


class TestDispatch(unittest.TestCase):
    def test_all_languages_produce_output(self):
        req = sample_request()
        for key, _title in codegen.LANGUAGES:
            code = codegen.generate(key, req, VARS)
            self.assertTrue(code.strip(), f"пустой вывод для {key}")

    def test_curl_delegates(self):
        code = codegen.generate(codegen.LANG_CURL, sample_request(), VARS)
        self.assertTrue(code.startswith("curl"))

    def test_unknown_language(self):
        with self.assertRaises(ValueError):
            codegen.generate("cobol", sample_request(), VARS)


if __name__ == "__main__":
    unittest.main()
