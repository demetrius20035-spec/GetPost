import unittest

from getpost_gui.variables import find_variables, substitute


class TestSubstitute(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(substitute("{{base}}/x", {"base": "http://a"}), "http://a/x")

    def test_spaces_inside_braces(self):
        self.assertEqual(substitute("{{ base }}", {"base": "v"}), "v")

    def test_unknown_left_intact(self):
        self.assertEqual(substitute("{{nope}}", {}), "{{nope}}")

    def test_multiple(self):
        self.assertEqual(
            substitute("{{a}}-{{b}}", {"a": "1", "b": "2"}), "1-2"
        )

    def test_empty_and_no_vars(self):
        self.assertEqual(substitute("", {"a": "1"}), "")
        self.assertEqual(substitute("plain text", {"a": "1"}), "plain text")

    def test_non_string_value(self):
        self.assertEqual(substitute("{{n}}", {"n": 5}), "5")

    def test_find_variables(self):
        self.assertEqual(find_variables("{{a}}/{{ b }}"), ["a", "b"])
        self.assertEqual(find_variables("nope"), [])


if __name__ == "__main__":
    unittest.main()
