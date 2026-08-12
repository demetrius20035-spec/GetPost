import json
import unittest

from getpost_gui import capture, models


class TestJsonPath(unittest.TestCase):
    def test_simple_key(self):
        self.assertEqual(capture.extract_json_path({"a": 1}, "a"), 1)

    def test_nested(self):
        data = {"a": {"b": {"c": "deep"}}}
        self.assertEqual(capture.extract_json_path(data, "a.b.c"), "deep")

    def test_index(self):
        data = {"items": [{"id": 10}, {"id": 20}]}
        self.assertEqual(capture.extract_json_path(data, "items[1].id"), 20)

    def test_negative_index(self):
        self.assertEqual(capture.extract_json_path({"x": [1, 2, 3]}, "x[-1]"), 3)

    def test_root_list(self):
        self.assertEqual(capture.extract_json_path([{"k": "v"}], "[0].k"), "v")

    def test_missing_returns_none(self):
        self.assertIsNone(capture.extract_json_path({"a": 1}, "b"))
        self.assertIsNone(capture.extract_json_path({"a": 1}, "a.b.c"))
        self.assertIsNone(capture.extract_json_path({"x": []}, "x[5]"))

    def test_index_on_non_list(self):
        self.assertIsNone(capture.extract_json_path({"a": {"b": 1}}, "a[0]"))


class TestApplyCaptures(unittest.TestCase):
    def setUp(self):
        self.body = json.dumps(
            {"access_token": "AT-1", "user": {"id": 7, "admin": True}, "list": [1, 2]}
        )
        self.headers = [("Content-Type", "application/json"), ("X-Request-Id", "req-9")]

    def rule(self, name, source=models.CAPTURE_JSON, expr="", enabled=True):
        return {"enabled": enabled, "name": name, "source": source, "expr": expr}

    def test_json_capture(self):
        values, problems = capture.apply_captures(
            [self.rule("token", expr="access_token")], 200, self.headers, self.body
        )
        self.assertEqual(values, {"token": "AT-1"})
        self.assertEqual(problems, [])

    def test_types_stringified(self):
        values, _ = capture.apply_captures(
            [self.rule("uid", expr="user.id"), self.rule("adm", expr="user.admin"),
             self.rule("lst", expr="list")],
            200, self.headers, self.body,
        )
        self.assertEqual(values["uid"], "7")
        self.assertEqual(values["adm"], "true")
        self.assertEqual(values["lst"], "[1, 2]")

    def test_header_capture(self):
        values, _ = capture.apply_captures(
            [self.rule("rid", models.CAPTURE_HEADER, "x-request-id")],
            200, self.headers, self.body,
        )
        self.assertEqual(values["rid"], "req-9")  # регистр заголовка не важен

    def test_status_and_body(self):
        values, _ = capture.apply_captures(
            [self.rule("code", models.CAPTURE_STATUS), self.rule("raw", models.CAPTURE_BODY)],
            201, self.headers, "hello",
        )
        self.assertEqual(values["code"], "201")
        self.assertEqual(values["raw"], "hello")

    def test_disabled_rule_skipped(self):
        values, problems = capture.apply_captures(
            [self.rule("t", expr="access_token", enabled=False)], 200, self.headers, self.body
        )
        self.assertEqual(values, {})
        self.assertEqual(problems, [])

    def test_unnamed_rule_skipped(self):
        values, _ = capture.apply_captures(
            [self.rule("", expr="access_token")], 200, self.headers, self.body
        )
        self.assertEqual(values, {})

    def test_missing_path_reported(self):
        values, problems = capture.apply_captures(
            [self.rule("x", expr="nope.deep")], 200, self.headers, self.body
        )
        self.assertEqual(values, {})
        self.assertEqual(len(problems), 1)
        self.assertIn("nope.deep", problems[0])

    def test_missing_header_reported(self):
        _, problems = capture.apply_captures(
            [self.rule("x", models.CAPTURE_HEADER, "X-Absent")], 200, self.headers, self.body
        )
        self.assertIn("X-Absent", problems[0])

    def test_non_json_body_reported(self):
        _, problems = capture.apply_captures(
            [self.rule("x", expr="a")], 200, [], "<html>not json</html>"
        )
        self.assertIn("JSON", problems[0])

    def test_no_rules(self):
        self.assertEqual(capture.apply_captures([], 200, [], ""), ({}, []))


if __name__ == "__main__":
    unittest.main()
