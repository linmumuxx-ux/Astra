"""Frozen starter used for CTB Skill A/B evaluation."""
import unittest

from test_aw import create_controller, snapshot


class TestSmartLock(unittest.TestCase):
    def test_initial_state(self):
        c = create_controller()
        self.assertTrue(snapshot(c, "FRONT")["locked"])


if __name__ == "__main__":
    unittest.main()
