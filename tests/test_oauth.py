import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from getpost_gui import models, oauth


class FakeClock:
    """Управляемые «часы» для проверки истечения токена без ожидания."""

    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class TestTokenCache(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.cache = oauth.TokenCache(time_func=self.clock)
        self.key = ("https://auth/token", "client", "scope")

    def test_stores_and_returns(self):
        self.cache.put(self.key, "T1", 3600)
        self.assertEqual(self.cache.get(self.key), "T1")

    def test_missing_key(self):
        self.assertIsNone(self.cache.get(("other", "", "")))

    def test_expires_after_lifetime(self):
        self.cache.put(self.key, "T1", 3600)
        self.clock.advance(3600 - oauth.EXPIRY_MARGIN + 1)
        self.assertIsNone(self.cache.get(self.key))

    def test_refreshed_before_expiry_margin(self):
        """Токен считается просроченным заранее, за EXPIRY_MARGIN до конца."""
        self.cache.put(self.key, "T1", 100)
        self.clock.advance(100 - oauth.EXPIRY_MARGIN - 1)
        self.assertEqual(self.cache.get(self.key), "T1")
        self.clock.advance(2)
        self.assertIsNone(self.cache.get(self.key))

    def test_short_lived_token_still_usable(self):
        """Токен с очень коротким сроком годится для текущего запроса."""
        self.cache.put(self.key, "T1", 1)
        self.assertEqual(self.cache.get(self.key), "T1")

    def test_clear(self):
        self.cache.put(self.key, "T1", 3600)
        self.cache.clear()
        self.assertIsNone(self.cache.get(self.key))

    def test_different_scope_is_different_token(self):
        self.cache.put(("u", "c", "read"), "R", 3600)
        self.cache.put(("u", "c", "write"), "W", 3600)
        self.assertEqual(self.cache.get(("u", "c", "read")), "R")
        self.assertEqual(self.cache.get(("u", "c", "write")), "W")


class _TokenHandler(BaseHTTPRequestHandler):
    """Мини token endpoint для проверки реального обмена."""

    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        _TokenHandler.calls.append(
            {"path": self.path, "body": body, "auth": self.headers.get("Authorization", "")}
        )
        if self.path == "/bad":
            payload = json.dumps({"error": "invalid_client"}).encode()
            self.send_response(401)
        elif self.path == "/notoken":
            payload = json.dumps({"foo": "bar"}).encode()
            self.send_response(200)
        elif self.path == "/notjson":
            payload = b"<html>oops</html>"
            self.send_response(200)
        else:
            payload = json.dumps({"access_token": "AT-XYZ", "expires_in": 3600}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class TestFetchToken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _TokenHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _TokenHandler.calls.clear()
        self.clock = FakeClock()
        self.cache = oauth.TokenCache(time_func=self.clock)

    def config(self, path="/token", **overrides):
        config = {
            "token_url": f"http://127.0.0.1:{self.port}{path}",
            "client_id": "cid",
            "client_secret": "csecret",
            "scope": "read",
            "send_as": models.OAUTH_SEND_BODY,
        }
        config.update(overrides)
        return config

    def test_fetches_token(self):
        token = oauth.fetch_token(self.config(), token_cache=self.cache)
        self.assertEqual(token, "AT-XYZ")
        self.assertIn("grant_type=client_credentials", _TokenHandler.calls[0]["body"])
        self.assertIn("scope=read", _TokenHandler.calls[0]["body"])

    def test_credentials_in_body(self):
        oauth.fetch_token(self.config(), token_cache=self.cache)
        self.assertIn("client_id=cid", _TokenHandler.calls[0]["body"])

    def test_credentials_as_basic_auth(self):
        oauth.fetch_token(
            self.config(send_as=models.OAUTH_SEND_BASIC), token_cache=self.cache
        )
        self.assertTrue(_TokenHandler.calls[0]["auth"].startswith("Basic "))
        self.assertNotIn("client_secret", _TokenHandler.calls[0]["body"])

    def test_uses_cache_on_second_call(self):
        oauth.fetch_token(self.config(), token_cache=self.cache)
        oauth.fetch_token(self.config(), token_cache=self.cache)
        self.assertEqual(len(_TokenHandler.calls), 1)  # второй раз — из кэша

    def test_force_bypasses_cache(self):
        oauth.fetch_token(self.config(), token_cache=self.cache)
        oauth.fetch_token(self.config(), token_cache=self.cache, force=True)
        self.assertEqual(len(_TokenHandler.calls), 2)

    def test_error_status_raises(self):
        with self.assertRaises(oauth.TokenError) as ctx:
            oauth.fetch_token(self.config("/bad"), token_cache=self.cache)
        self.assertIn("401", str(ctx.exception))

    def test_missing_access_token_raises(self):
        with self.assertRaises(oauth.TokenError):
            oauth.fetch_token(self.config("/notoken"), token_cache=self.cache)

    def test_non_json_raises(self):
        with self.assertRaises(oauth.TokenError):
            oauth.fetch_token(self.config("/notjson"), token_cache=self.cache)

    def test_missing_url_raises(self):
        with self.assertRaises(oauth.TokenError):
            oauth.fetch_token(self.config(token_url=""), token_cache=self.cache)

    def test_unreachable_host_raises(self):
        with self.assertRaises(oauth.TokenError):
            oauth.fetch_token(
                self.config(token_url="http://127.0.0.1:1/token"), token_cache=self.cache
            )


class TestConfigFrom(unittest.TestCase):
    def test_substitutes_variables(self):
        req = models.Request("R")
        req.auth_type = models.AUTH_OAUTH2_CC
        req.auth_oauth2_token_url = "{{auth_host}}/token"
        req.auth_oauth2_client_id = "{{cid}}"
        req.auth_oauth2_client_secret = "s3cret"
        req.auth_oauth2_scope = "read write"
        config = oauth.config_from(req, {"auth_host": "https://auth.io", "cid": "abc"})
        self.assertEqual(config["token_url"], "https://auth.io/token")
        self.assertEqual(config["client_id"], "abc")
        self.assertEqual(config["scope"], "read write")


if __name__ == "__main__":
    unittest.main()
