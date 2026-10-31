from pathlib import Path
import re
import subprocess
import unittest


class PackageVersionTests(unittest.TestCase):
    def test_debian_preview_version_becomes_valid_arch_version(self):
        script = (Path(__file__).resolve().parents[1] / "package.sh").read_text()
        conversion = next(line for line in script.splitlines() if line.startswith("arch_version="))
        result = subprocess.run(["bash", "-c", 'version="0.3.1~linux1"\n' + conversion
                                 + '\nprintf "%s" "$arch_version"'],
                                check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, "0.3.1.linux1")
        self.assertRegex(result.stdout, r"^[0-9][a-zA-Z0-9.+]*$")
