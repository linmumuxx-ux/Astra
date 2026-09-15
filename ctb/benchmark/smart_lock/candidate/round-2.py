from with_experience import TestSmartLock
from test_aw import create_controller, enter_pin, open_door, close_door, admin_reset, tick, snapshot


def test_back_unlock_timer_advances_with_tick(self):
    c=create_controller(); enter_pin(c,'BACK','2468'); tick(c,9); self.assertFalse(snapshot(c,'BACK')['locked']); tick(c,1); self.assertTrue(snapshot(c,'BACK')['locked'])


def test_close_before_timeout_does_not_lock_or_refresh(self):
    c=create_controller(); enter_pin(c,'FRONT','2468'); tick(c,3); self.assertTrue(open_door(c,'FRONT')); close_door(c,'FRONT')
    s=snapshot(c,'FRONT'); self.assertFalse(s['locked']); self.assertFalse(s['door_open']); self.assertEqual(7,s['unlock_remaining'])


def test_admin_reset_back_clears_lockout_without_other_side_effects(self):
    c=create_controller(); [enter_pin(c,'BACK','1111') for _ in range(3)]; before_front=snapshot(c,'FRONT').copy(); admin_reset(c,'BACK')
    s=snapshot(c,'BACK'); self.assertTrue(s['locked']); self.assertEqual(0,s['failed_attempts']); self.assertEqual(0,s['lockout_remaining']); self.assertEqual(before_front,snapshot(c,'FRONT'))


TestSmartLock.test_back_unlock_timer_advances_with_tick = test_back_unlock_timer_advances_with_tick
TestSmartLock.test_close_before_timeout_does_not_lock_or_refresh = test_close_before_timeout_does_not_lock_or_refresh
TestSmartLock.test_admin_reset_back_clears_lockout_without_other_side_effects = test_admin_reset_back_clears_lockout_without_other_side_effects
