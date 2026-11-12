import os
import subprocess
import unittest
from pathlib import Path

from helpers import stub, tmpdir

READER = Path(__file__).resolve().parents[2] / "files/usr/libexec/atomic-hyprland/md-reader"


class MdReaderTest(unittest.TestCase):
    def run_reader(self, columns: str) -> str:
        root = tmpdir(self)
        stub(root / "bin", "glow", 'echo "PAGER=$PAGER $*"')
        env = {"PATH": f"{root / 'bin'}:/usr/bin:/bin", "COLUMNS": columns}
        # A new session has no controlling terminal, so the reader falls back to $COLUMNS.
        out = subprocess.run([str(READER), "/x/answer.md"], env=env, capture_output=True,
                             text=True, start_new_session=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_wraps_to_the_window(self):
        self.assertEqual(self.run_reader("90"), "PAGER=less -R -p -w 86 /x/answer.md")

    def test_wide_window_capped_for_reading(self):
        self.assertEqual(self.run_reader("135"), "PAGER=less -R -p -w 120 /x/answer.md")

    def test_narrow_window_keeps_a_floor(self):
        self.assertEqual(self.run_reader("30"), "PAGER=less -R -p -w 40 /x/answer.md")


if __name__ == "__main__":
    unittest.main()
