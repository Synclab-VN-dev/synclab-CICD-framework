import tempfile
import unittest
from pathlib import Path

from synclab_release.errors import PreflightError
from synclab_release.gradle_version import read_gradle_version, write_gradle_version
from synclab_release.models import GradleVersion


class GradleVersionTest(unittest.TestCase):
    def test_reads_and_writes_groovy_version(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "build.gradle"
            path.write_text(
                """android {
    defaultConfig {
        versionCode 1003050006
        versionName "10.3.5.6"
    }
}
""",
                encoding="utf-8",
            )

            self.assertEqual(read_gradle_version(path), GradleVersion("10.3.5.6", 1003050006))
            write_gradle_version(path, GradleVersion("10.3.5.7", 1003050007))
            text = path.read_text(encoding="utf-8")
            self.assertIn('versionName "10.3.5.7"', text)
            self.assertIn("versionCode 1003050007", text)

    def test_rejects_multiple_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "build.gradle"
            path.write_text(
                """versionName "10.3.5.6"
versionName "10.3.5.7"
versionCode 1003050006
""",
                encoding="utf-8",
            )
            with self.assertRaises(PreflightError):
                read_gradle_version(path)


if __name__ == "__main__":
    unittest.main()
