import unittest

from synclab_release.errors import PreflightError
from synclab_release.models import GradleVersion
from synclab_release.quad_version import QuadVersion
from synclab_release.version_resolver import resolve_version


class QuadVersionTest(unittest.TestCase):
    def test_computes_version_code(self):
        self.assertEqual(QuadVersion.parse("10.3.5.6").to_version_code(), 1003050006)
        self.assertEqual(QuadVersion.parse("10.3.5.60").to_version_code(), 1003050060)
        self.assertEqual(QuadVersion.parse("10.12.5.6").to_version_code(), 1012050006)

    def test_bumps_each_level(self):
        version = QuadVersion.parse("10.3.5.6")
        self.assertEqual(str(version.bump("d")), "10.3.5.7")
        self.assertEqual(str(version.bump("c")), "10.3.6.0")
        self.assertEqual(str(version.bump("b")), "10.4.0.0")
        self.assertEqual(str(version.bump("a")), "11.0.0.0")

    def test_rejects_invalid_versions(self):
        for value in ("1.0.0", "v1.0.0.0", "1.0.0.0-preview", "1.0.0.10000"):
            with self.subTest(value=value):
                with self.assertRaises(PreflightError):
                    QuadVersion.parse(value)

    def test_resolves_auto_version(self):
        resolved = resolve_version(GradleVersion("10.3.5.6", 1003050006), "d", None)
        self.assertEqual(resolved.next.version_name, "10.3.5.7")
        self.assertEqual(resolved.next.version_code, 1003050007)

    def test_rejects_current_code_mismatch(self):
        with self.assertRaises(PreflightError):
            resolve_version(GradleVersion("10.3.5.6", 1), "d", None)

    def test_rejects_manual_not_greater(self):
        with self.assertRaises(PreflightError):
            resolve_version(GradleVersion("10.3.5.6", 1003050006), "d", "10.3.5.6")


if __name__ == "__main__":
    unittest.main()
