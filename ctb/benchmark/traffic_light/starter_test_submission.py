"""Frozen starter used for CTB Skill A/B evaluation."""
import unittest

from test_aw import create_controller, snapshot


class TestTrafficController(unittest.TestCase):
    def test_initial_state(self):
        c = create_controller()
        state = snapshot(c)
        self.assertEqual(state["state"], "NS_GREEN")
        self.assertEqual(state["elapsed"], 0)
        self.assertEqual(state["ns_queue"], 0)
        self.assertEqual(state["ew_queue"], 0)
        self.assertFalse(state["ns_emergency"])
        self.assertFalse(state["ew_emergency"])


if __name__ == "__main__":
    unittest.main()
