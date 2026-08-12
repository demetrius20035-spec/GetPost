import os
import sys
import tempfile
import unittest

# getpost.py лежит в корне репозитория.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import getpost  # noqa: E402
from getpost_gui import models  # noqa: E402


def parse_send(*cli):
    return getpost.build_parser().parse_args(["send", *cli])


class TestParsing(unittest.TestCase):
    def test_split_pair_ok(self):
        self.assertEqual(getpost._split_pair("a=b=c", "=", "x"), ("a", "b=c"))

    def test_split_pair_bad(self):
        with self.assertRaises(ValueError):
            getpost._split_pair("nope", "=", "параметра")

    def test_parse_headers(self):
        self.assertEqual(
            getpost.parse_headers(["X-Key: 1", "Accept:application/json"]),
            [
                {"enabled": True, "key": "X-Key", "value": "1"},
                {"enabled": True, "key": "Accept", "value": "application/json"},
            ],
        )

    def test_parse_kv(self):
        self.assertEqual(
            getpost.parse_kv(["a=1", "b=two"], "параметра"),
            [
                {"enabled": True, "key": "a", "value": "1"},
                {"enabled": True, "key": "b", "value": "two"},
            ],
        )

    def test_read_value_inline_and_file(self):
        self.assertEqual(getpost.read_value("plain"), "plain")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("FROMFILE")
            path = fh.name
        try:
            self.assertEqual(getpost.read_value("@" + path), "FROMFILE")
        finally:
            os.unlink(path)


class TestRequestFromArgs(unittest.TestCase):
    def test_json_and_bearer(self):
        args = parse_send("GET", "http://x", "--json", '{"a":1}', "--bearer", "T")
        req = getpost.request_from_args(args)
        self.assertEqual(req.body_type, models.BODY_RAW)
        self.assertEqual(req.body_raw, '{"a":1}')
        self.assertEqual(req.body_raw_lang, models.RAW_JSON)
        self.assertEqual(req.auth_type, models.AUTH_BEARER)
        self.assertEqual(req.auth_bearer_token, "T")

    def test_basic_auth(self):
        args = parse_send("GET", "http://x", "-u", "user:pass")
        req = getpost.request_from_args(args)
        self.assertEqual(req.auth_type, models.AUTH_BASIC)
        self.assertEqual(req.auth_basic_username, "user")
        self.assertEqual(req.auth_basic_password, "pass")

    def test_form_and_headers_and_query(self):
        args = parse_send("POST", "http://x", "-F", "a=1", "-F", "b=2",
                          "-H", "X: y", "-q", "p=q", "-A", "MyAgent")
        req = getpost.request_from_args(args)
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.body_type, models.BODY_URLENCODED)
        self.assertEqual(len(req.body_form), 2)
        self.assertIn({"enabled": True, "key": "X", "value": "y"}, req.headers)
        self.assertIn({"enabled": True, "key": "User-Agent", "value": "MyAgent"}, req.headers)
        self.assertEqual(req.params, [{"enabled": True, "key": "p", "value": "q"}])

    def test_method_uppercased(self):
        args = getpost.build_parser().parse_args(["send", "get", "http://x"])
        self.assertEqual(args.method, "GET")


class TestWorkspaceLookup(unittest.TestCase):
    def _ws(self):
        ws = models.Workspace("WS")
        f = models.Folder("Group")
        r1 = models.Request("Ping")
        r2 = models.Request("Ping")  # дубликат имени в другой папке
        sub = models.Folder("Sub")
        sub.requests.append(r2)
        f.requests.append(r1)
        f.folders.append(sub)
        ws.folders.append(f)
        ws.requests.append(models.Request("Root"))
        return ws

    def test_iter_requests_paths(self):
        ws = self._ws()
        paths = sorted(p for p, _ in getpost.iter_requests(ws))
        self.assertEqual(paths, ["Group/Ping", "Group/Sub/Ping", "Root"])

    def test_find_by_unique_name(self):
        ws = self._ws()
        self.assertEqual(len(getpost.find_request(ws, "Root")), 1)

    def test_find_ambiguous_name(self):
        ws = self._ws()
        # «Ping» встречается дважды — должно вернуться 2 совпадения.
        self.assertEqual(len(getpost.find_request(ws, "Ping")), 2)

    def test_find_by_path(self):
        ws = self._ws()
        matches = getpost.find_request(ws, "Group/Sub/Ping")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], "Group/Sub/Ping")


class TestArgvRewrite(unittest.TestCase):
    def test_bare_method_becomes_send(self):
        # main() переписывает «GET url» в «send GET url»; проверим парсер на этом.
        parser = getpost.build_parser()
        args = parser.parse_args(["send", "GET", "http://x"])
        self.assertEqual(args.command, "send")
        self.assertTrue(callable(args.func))


if __name__ == "__main__":
    unittest.main()
