from pathlib import Path
import subprocess
import unittest


class NativeAdapterTests(unittest.TestCase):
    def test_native_host_and_provider_public_boundaries(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("native.test.cjs"))],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
