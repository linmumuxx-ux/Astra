import unittest
from test_aw import create_controller, snapshot

class TestTrafficController(unittest.TestCase):
    def test_initial_state(self):
        c=create_controller(); self.assertEqual('NS_GREEN',snapshot(c)['state'])

if __name__=='__main__': unittest.main()
