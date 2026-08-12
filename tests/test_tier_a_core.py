"""Тесты ядра Tier A: переменные, GraphQL, API Key, cookies, diff, тема."""
import json
import tempfile
import unittest

import requests

from getpost_gui import cookies, diffing, http_client, models, storage, variables


class TestDynamicVariables(unittest.TestCase):
    def test_uuid(self):
        value = variables.substitute("{{$uuid}}", {})
        self.assertRegex(value, r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")

    def test_uuid_differs_each_time(self):
        first = variables.substitute("{{$uuid}}", {})
        second = variables.substitute("{{$uuid}}", {})
        self.assertNotEqual(first, second)

    def test_timestamp_is_numeric(self):
        self.assertTrue(variables.substitute("{{$timestamp}}", {}).isdigit())

    def test_iso_timestamp(self):
        value = variables.substitute("{{$isoTimestamp}}", {})
        self.assertTrue(value.endswith("Z"))
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_date(self):
        self.assertRegex(variables.substitute("{{$date}}", {}), r"^\d{4}-\d{2}-\d{2}$")

    def test_random_int_range(self):
        for _ in range(20):
            value = int(variables.substitute("{{$randomInt(5,7)}}", {}))
            self.assertIn(value, (5, 6, 7))

    def test_random_int_single_bound(self):
        value = int(variables.substitute("{{$randomInt(3)}}", {}))
        self.assertGreaterEqual(value, 0)
        self.assertLessEqual(value, 3)

    def test_random_int_reversed_bounds(self):
        value = int(variables.substitute("{{$randomInt(9,4)}}", {}))
        self.assertGreaterEqual(value, 4)
        self.assertLessEqual(value, 9)

    def test_random_string_length(self):
        self.assertEqual(len(variables.substitute("{{$randomString(16)}}", {})), 16)

    def test_case_insensitive_names(self):
        self.assertTrue(variables.substitute("{{$RANDOMINT(1,1)}}", {}) == "1")

    def test_unknown_dynamic_left_as_is(self):
        self.assertEqual(variables.substitute("{{$nope}}", {}), "{{$nope}}")

    def test_mixed_with_regular(self):
        result = variables.substitute("{{base}}/{{$randomInt(1,1)}}", {"base": "http://x"})
        self.assertEqual(result, "http://x/1")


class TestNestedVariables(unittest.TestCase):
    def test_one_level(self):
        self.assertEqual(
            variables.substitute("{{url}}", {"url": "{{host}}/api", "host": "https://x"}),
            "https://x/api",
        )

    def test_deep_chain(self):
        env = {"a": "{{b}}", "b": "{{c}}", "c": "final"}
        self.assertEqual(variables.substitute("{{a}}", env), "final")

    def test_cycle_does_not_hang(self):
        result = variables.substitute("{{a}}", {"a": "{{b}}", "b": "{{a}}"})
        self.assertIn("{{", result)  # осталось неразрешённым, но без зависания

    def test_self_reference(self):
        self.assertIn("{{", variables.substitute("{{a}}", {"a": "{{a}}"}))

    def test_depth_limit_respected(self):
        env = {f"v{i}": f"{{{{v{i + 1}}}}}" for i in range(variables.MAX_DEPTH + 5)}
        env[f"v{variables.MAX_DEPTH + 5}"] = "end"
        result = variables.substitute("{{v0}}", env)
        self.assertIsInstance(result, str)  # не падает и не зависает


class TestFindUnresolved(unittest.TestCase):
    def test_dynamic_counts_as_known(self):
        self.assertEqual(variables.find_unresolved("{{$uuid}}", {}), [])

    def test_lists_missing_only(self):
        self.assertEqual(
            variables.find_unresolved("{{a}} {{b}} {{$timestamp}}", {"a": "1"}), ["b"]
        )

    def test_unknown_dynamic_is_unresolved(self):
        self.assertEqual(variables.find_unresolved("{{$bogus}}", {}), ["$bogus"])

    def test_no_duplicates(self):
        self.assertEqual(variables.find_unresolved("{{x}} {{x}}", {}), ["x"])


class TestGraphQLBody(unittest.TestCase):
    def request(self, query, gql_vars=""):
        req = models.Request("G")
        req.method = "POST"
        req.url = "http://gql"
        req.body_type = models.BODY_GRAPHQL
        req.body_graphql_query = query
        req.body_graphql_variables = gql_vars
        return req

    def test_query_and_variables(self):
        req = self.request("query { me { id } }", '{"limit": 5}')
        _, _, kwargs = http_client.build_request_kwargs(req, {})
        payload = json.loads(kwargs["data"])
        self.assertEqual(payload["query"], "query { me { id } }")
        self.assertEqual(payload["variables"], {"limit": 5})

    def test_content_type_json(self):
        _, _, kwargs = http_client.build_request_kwargs(self.request("{ x }"), {})
        self.assertTrue(kwargs["headers"]["Content-Type"].startswith("application/json"))

    def test_without_variables(self):
        _, _, kwargs = http_client.build_request_kwargs(self.request("{ x }"), {})
        self.assertNotIn("variables", json.loads(kwargs["data"]))

    def test_invalid_variables_passed_through(self):
        req = self.request("{ x }", "{not json}")
        _, _, kwargs = http_client.build_request_kwargs(req, {})
        self.assertEqual(json.loads(kwargs["data"])["variables"], "{not json}")

    def test_variables_substituted(self):
        req = self.request("query($id: Int) { u(id: $id) }", '{"id": {{uid}}}')
        _, _, kwargs = http_client.build_request_kwargs(req, {"uid": "42"})
        self.assertEqual(json.loads(kwargs["data"])["variables"], {"id": 42})

    def test_roundtrip_keeps_graphql(self):
        req = self.request("{ a }", '{"b": 1}')
        clone = models.Request.from_dict(req.to_dict())
        self.assertEqual(clone.body_graphql_query, "{ a }")
        self.assertEqual(clone.body_graphql_variables, '{"b": 1}')


class TestApiKeyAuth(unittest.TestCase):
    def request(self, location=models.APIKEY_IN_HEADER, name="X-API-Key", value="SECRET"):
        req = models.Request("K")
        req.url = "http://x"
        req.auth_type = models.AUTH_API_KEY
        req.auth_api_key_name = name
        req.auth_api_key_value = value
        req.auth_api_key_location = location
        return req

    def test_in_header(self):
        _, _, kwargs = http_client.build_request_kwargs(self.request(), {})
        self.assertEqual(kwargs["headers"]["X-API-Key"], "SECRET")

    def test_in_query(self):
        _, _, kwargs = http_client.build_request_kwargs(
            self.request(models.APIKEY_IN_QUERY, "api_key"), {}
        )
        self.assertIn(("api_key", "SECRET"), kwargs["params"])

    def test_variables_substituted(self):
        req = self.request(value="{{key}}")
        _, _, kwargs = http_client.build_request_kwargs(req, {"key": "FROM-VAR"})
        self.assertEqual(kwargs["headers"]["X-API-Key"], "FROM-VAR")

    def test_empty_name_ignored(self):
        _, _, kwargs = http_client.build_request_kwargs(self.request(name=""), {})
        self.assertNotIn("headers", kwargs)

    def test_existing_header_not_overwritten(self):
        req = self.request()
        req.headers = [{"enabled": True, "key": "X-API-Key", "value": "MANUAL"}]
        _, _, kwargs = http_client.build_request_kwargs(req, {})
        self.assertEqual(kwargs["headers"]["X-API-Key"], "MANUAL")

    def test_oauth_adds_nothing_at_build_time(self):
        req = models.Request("O")
        req.url = "http://x"
        req.auth_type = models.AUTH_OAUTH2_CC
        req.auth_oauth2_token_url = "http://auth/token"
        _, _, kwargs = http_client.build_request_kwargs(req, {})
        self.assertNotIn("headers", kwargs)
        self.assertTrue(http_client.needs_oauth(req))

    def test_apply_oauth_token(self):
        kwargs = {}
        http_client.apply_oauth_token(kwargs, "TOK")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer TOK")

    def test_apply_oauth_respects_existing_header(self):
        kwargs = {"headers": {"Authorization": "Custom"}}
        http_client.apply_oauth_token(kwargs, "TOK")
        self.assertEqual(kwargs["headers"]["Authorization"], "Custom")


class TestCookieJar(unittest.TestCase):
    def setUp(self):
        self.session = requests.Session()
        self.session.cookies.set("sid", "abc", domain="example.com", path="/")
        self.session.cookies.set("theme", "dark", domain="other.io", path="/app")

    def test_export(self):
        exported = cookies.export_jar(self.session)
        names = {c["name"]: c for c in exported}
        self.assertEqual(names["sid"]["value"], "abc")
        self.assertEqual(names["sid"]["domain"], "example.com")
        self.assertEqual(names["theme"]["path"], "/app")

    def test_roundtrip_through_disk(self):
        store = storage.Storage(tempfile.mkdtemp())
        store.save_cookies(cookies.export_jar(self.session))
        fresh = requests.Session()
        count = cookies.import_jar(fresh, store.load_cookies())
        self.assertEqual(count, 2)
        self.assertEqual(fresh.cookies.get("sid", domain="example.com"), "abc")

    def test_import_skips_broken_entries(self):
        fresh = requests.Session()
        count = cookies.import_jar(fresh, [{"value": "no name"}, "garbage", {"name": "ok"}])
        self.assertEqual(count, 1)

    def test_remove(self):
        self.assertTrue(cookies.remove(self.session, "sid", "example.com", "/"))
        self.assertIsNone(self.session.cookies.get("sid", domain="example.com"))

    def test_remove_missing_returns_false(self):
        self.assertFalse(cookies.remove(self.session, "nope"))

    def test_clear(self):
        cookies.clear(self.session)
        self.assertEqual(len(list(self.session.cookies)), 0)

    def test_summary(self):
        self.assertIn("2 cookies", cookies.summary(self.session))
        cookies.clear(self.session)
        self.assertEqual(cookies.summary(self.session), "нет cookies")

    def test_missing_file_returns_empty(self):
        store = storage.Storage(tempfile.mkdtemp())
        self.assertEqual(store.load_cookies(), [])


def response(text="{}", status=200, headers=None, elapsed=10.0, ctype="application/json"):
    return http_client.ResponseData(
        status_code=status, reason="OK", headers=headers or [("Content-Type", ctype)],
        text=text, elapsed_ms=elapsed, size_bytes=len(text), url="http://x",
        content_type=ctype, ok=status < 400, content=text.encode(),
    )


class TestDiffing(unittest.TestCase):
    def test_normalize_sorts_json_keys(self):
        left = diffing.normalize_body('{"b":1,"a":2}', "application/json")
        right = diffing.normalize_body('{"a":2,"b":1}', "application/json")
        self.assertEqual(left, right)  # порядок ключей не создаёт различий

    def test_normalize_leaves_plain_text(self):
        self.assertEqual(diffing.normalize_body("hello", "text/plain"), "hello")

    def test_normalize_invalid_json(self):
        self.assertEqual(diffing.normalize_body("{oops", "application/json"), "{oops")

    def test_diff_lines(self):
        lines = diffing.diff_lines("a\nb", "a\nc")
        self.assertTrue(any(line.startswith("-b") for line in lines))
        self.assertTrue(any(line.startswith("+c") for line in lines))

    def test_diff_headers(self):
        lines = diffing.diff_headers(
            [("A", "1"), ("B", "2")], [("A", "9"), ("C", "3")]
        )
        joined = "\n".join(lines)
        self.assertIn("- A: 1", joined)
        self.assertIn("+ A: 9", joined)
        self.assertIn("- B: 2", joined)
        self.assertIn("+ C: 3", joined)

    def test_compare_reports_status_change(self):
        report = diffing.compare(response(status=200), response(status=500))
        self.assertIn("500", report)

    def test_compare_identical_bodies(self):
        report = diffing.compare(response('{"a":1}'), response('{"a":1}'))
        self.assertIn("Тело: без изменений", report)

    def test_compare_shows_body_diff(self):
        report = diffing.compare(response('{"a":1}'), response('{"a":2}'))
        self.assertIn("Тело:", report)
        self.assertIn('"a": 2', report)

    def test_compare_includes_timing_delta(self):
        report = diffing.compare(response(elapsed=10.0), response(elapsed=25.0))
        self.assertIn("+15", report)


class TestAuthFieldHelpers(unittest.TestCase):
    def test_defines_auth(self):
        req = models.Request("R")
        self.assertFalse(models.defines_auth(req))
        req.auth_type = models.AUTH_INHERIT
        self.assertFalse(models.defines_auth(req))
        req.auth_type = models.AUTH_API_KEY
        self.assertTrue(models.defines_auth(req))

    def test_auth_roundtrip_all_fields(self):
        req = models.Request("R")
        req.auth_type = models.AUTH_OAUTH2_CC
        req.auth_oauth2_token_url = "http://auth/token"
        req.auth_oauth2_client_id = "cid"
        req.auth_oauth2_client_secret = "sec"
        req.auth_oauth2_scope = "read"
        req.auth_oauth2_send_as = models.OAUTH_SEND_BASIC
        clone = models.Request.from_dict(req.to_dict())
        for field in models.AUTH_FIELDS:
            self.assertEqual(getattr(clone, field), getattr(req, field), field)

    def test_unknown_auth_type_coerced(self):
        req = models.Request.from_dict({"auth_type": "kerberos"})
        self.assertEqual(req.auth_type, models.AUTH_NONE)

    def test_old_file_without_auth_defaults_to_none(self):
        """Поведение сохранённых запросов не меняется после добавления inherit."""
        req = models.Request.from_dict({"name": "Old", "url": "http://x"})
        self.assertEqual(req.auth_type, models.AUTH_NONE)


class TestThemeTokens(unittest.TestCase):
    def test_both_palettes_have_same_tokens(self):
        from getpost_gui import theme

        self.assertEqual(set(theme.LIGHT), set(theme.DARK))
        self.assertEqual(set(theme.LIGHT_SYNTAX), set(theme.DARK_SYNTAX))

    def test_all_colors_are_valid_hex(self):
        from getpost_gui import theme

        for palette in (theme.LIGHT, theme.DARK, theme.LIGHT_SYNTAX, theme.DARK_SYNTAX):
            for name, value in palette.items():
                self.assertRegex(value, r"^#[0-9a-fA-F]{6}$", f"{name}={value}")


if __name__ == "__main__":
    unittest.main()
