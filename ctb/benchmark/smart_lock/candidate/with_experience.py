import unittest
from test_aw import create_controller, enter_pin, open_door, close_door, admin_reset, tick, snapshot

class TestSmartLock(unittest.TestCase):
    def test_initial_states_independent(self):
        c=create_controller(); e={'locked':True,'door_open':False,'failed_attempts':0,'lockout_remaining':0,'unlock_remaining':0}
        self.assertEqual(e,snapshot(c,'FRONT')); self.assertEqual(e,snapshot(c,'BACK'))
    def test_correct_pin_unlocks_for_ten_seconds(self):
        c=create_controller(); self.assertTrue(enter_pin(c,'FRONT','2468')); s=snapshot(c,'FRONT'); self.assertFalse(s['locked']); self.assertEqual(10,s['unlock_remaining']); self.assertEqual(0,s['failed_attempts'])
    def test_unlock_timeout_exact_boundary(self):
        c=create_controller(); enter_pin(c,'FRONT','2468'); tick(c,9); self.assertFalse(snapshot(c,'FRONT')['locked']); tick(c,1); s=snapshot(c,'FRONT'); self.assertTrue(s['locked']); self.assertEqual(0,s['unlock_remaining'])
    def test_three_wrong_pins_start_lockout(self):
        c=create_controller(); enter_pin(c,'FRONT','1111'); enter_pin(c,'FRONT','1111'); self.assertEqual(2,snapshot(c,'FRONT')['failed_attempts']); enter_pin(c,'FRONT','1111'); s=snapshot(c,'FRONT'); self.assertEqual(0,s['failed_attempts']); self.assertEqual(30,s['lockout_remaining'])
    def test_lockout_exact_duration(self):
        c=create_controller(); [enter_pin(c,'FRONT','1111') for _ in range(3)]; tick(c,29); self.assertEqual(1,snapshot(c,'FRONT')['lockout_remaining']); tick(c,1); self.assertEqual(0,snapshot(c,'FRONT')['lockout_remaining']); self.assertTrue(enter_pin(c,'FRONT','2468'))
    def test_correct_pin_during_lockout_does_not_change_state(self):
        c=create_controller(); [enter_pin(c,'FRONT','1111') for _ in range(3)]; before=snapshot(c,'FRONT').copy(); self.assertFalse(enter_pin(c,'FRONT','2468')); self.assertEqual(before,snapshot(c,'FRONT'))
    def test_success_resets_prior_failures(self):
        c=create_controller(); enter_pin(c,'FRONT','1111'); enter_pin(c,'FRONT','2222'); enter_pin(c,'FRONT','2468'); self.assertEqual(0,snapshot(c,'FRONT')['failed_attempts'])
    def test_repeat_correct_pin_does_not_refresh_timer(self):
        c=create_controller(); enter_pin(c,'FRONT','2468'); tick(c,6); self.assertEqual(4,snapshot(c,'FRONT')['unlock_remaining']); enter_pin(c,'FRONT','2468'); self.assertEqual(4,snapshot(c,'FRONT')['unlock_remaining'])
    def test_wrong_pin_while_unlocked_has_no_side_effect(self):
        c=create_controller(); enter_pin(c,'FRONT','2468'); tick(c,3); before=snapshot(c,'FRONT').copy(); self.assertFalse(enter_pin(c,'FRONT','1111')); self.assertEqual(before,snapshot(c,'FRONT'))
    def test_open_door_prevents_timeout_lock_until_close(self):
        c=create_controller(); enter_pin(c,'FRONT','2468'); open_door(c,'FRONT'); tick(c,10); s=snapshot(c,'FRONT'); self.assertFalse(s['locked']); self.assertTrue(s['door_open']); self.assertEqual(0,s['unlock_remaining']); close_door(c,'FRONT'); self.assertTrue(snapshot(c,'FRONT')['locked'])
    def test_open_locked_door_rejected(self):
        c=create_controller(); before=snapshot(c,'FRONT').copy(); self.assertFalse(open_door(c,'FRONT')); self.assertEqual(before,snapshot(c,'FRONT'))
    def test_repeated_close_when_already_closed_is_noop(self):
        c=create_controller(); enter_pin(c,'FRONT','2468'); tick(c,2); before=snapshot(c,'FRONT').copy(); close_door(c,'FRONT'); self.assertEqual(before,snapshot(c,'FRONT'))
    def test_admin_reset_clears_security_counters_only(self):
        c=create_controller(); [enter_pin(c,'FRONT','1111') for _ in range(3)]; admin_reset(c,'FRONT'); s=snapshot(c,'FRONT'); self.assertTrue(s['locked']); self.assertEqual(0,s['failed_attempts']); self.assertEqual(0,s['lockout_remaining']); self.assertEqual(0,s['unlock_remaining'])
    def test_admin_reset_does_not_change_unlocked_timer(self):
        c=create_controller(); enter_pin(c,'FRONT','2468'); tick(c,4); before=snapshot(c,'FRONT').copy(); admin_reset(c,'FRONT'); self.assertEqual(before,snapshot(c,'FRONT'))
    def test_front_back_security_state_isolated(self):
        c=create_controller(); enter_pin(c,'FRONT','1111'); enter_pin(c,'FRONT','1111'); enter_pin(c,'BACK','2468'); self.assertEqual(2,snapshot(c,'FRONT')['failed_attempts']); self.assertFalse(snapshot(c,'BACK')['locked']); self.assertEqual(0,snapshot(c,'BACK')['failed_attempts'])
    def test_back_direction_full_lockout_flow(self):
        c=create_controller(); [enter_pin(c,'BACK','1111') for _ in range(3)]; self.assertEqual(30,snapshot(c,'BACK')['lockout_remaining']); self.assertEqual(0,snapshot(c,'FRONT')['lockout_remaining'])
    def test_invalid_pin_preserves_state(self):
        c=create_controller(); before=snapshot(c,'FRONT').copy()
        for pin in ('123','12345','12a4',2468,True):
            with self.assertRaises(ValueError): enter_pin(c,'FRONT',pin)
            self.assertEqual(before,snapshot(c,'FRONT'))
    def test_invalid_door_preserves_other_door(self):
        c=create_controller(); f=snapshot(c,'FRONT').copy(); b=snapshot(c,'BACK').copy()
        with self.assertRaises(ValueError): enter_pin(c,'SIDE','2468')
        self.assertEqual(f,snapshot(c,'FRONT')); self.assertEqual(b,snapshot(c,'BACK'))
    def test_tick_requires_positive_integer_and_preserves_state(self):
        c=create_controller(); enter_pin(c,'FRONT','2468'); before=snapshot(c,'FRONT').copy()
        for value in (0,-1,1.5,True):
            with self.assertRaises(ValueError): tick(c,value)
            self.assertEqual(before,snapshot(c,'FRONT'))
    def test_large_tick_matches_sequential_semantics(self):
        a=create_controller(); b=create_controller(); enter_pin(a,'FRONT','2468'); enter_pin(b,'FRONT','2468'); tick(a,12)
        for _ in range(12): tick(b,1)
        self.assertEqual(snapshot(b,'FRONT'),snapshot(a,'FRONT')); self.assertEqual(snapshot(b,'BACK'),snapshot(a,'BACK'))

if __name__=='__main__': unittest.main()
