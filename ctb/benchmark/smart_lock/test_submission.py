"""参赛 testcase 模板。ctb-test-design 应在公开 workspace 中修改本文件。"""
import unittest
from test_aw import create_controller, enter_pin, open_door, close_door, admin_reset, tick, snapshot


class TestSmartLock(unittest.TestCase):
    def test_initial_state(self):
        c = create_controller()
        self.assertTrue(snapshot(c, 'FRONT')['locked'])


if __name__ == '__main__':
    unittest.main()
