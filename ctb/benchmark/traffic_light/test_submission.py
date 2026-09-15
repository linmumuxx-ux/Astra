import unittest
from test_aw import create_controller, set_queue, set_emergency, tick, snapshot

class TestTrafficController(unittest.TestCase):
    def test_initial_full_state(self):
        c=create_controller(); self.assertEqual({'state':'NS_GREEN','elapsed':0,'ns_queue':0,'ew_queue':0,'ns_emergency':False,'ew_emergency':False},snapshot(c))

    def test_min_green_exact_boundary(self):
        c=create_controller(); set_queue(c,'NS',2); set_queue(c,'EW',5); tick(c,9); self.assertEqual('NS_GREEN',snapshot(c)['state']); tick(c,1); self.assertEqual('ALL_RED',snapshot(c)['state'])

    def test_queue_difference_boundary(self):
        c=create_controller(); set_queue(c,'NS',4); set_queue(c,'EW',6); tick(c,10); self.assertEqual('NS_GREEN',snapshot(c)['state']); set_queue(c,'EW',7); tick(c,1); self.assertEqual('ALL_RED',snapshot(c)['state'])

    def test_max_green_exact_boundary_with_one_car(self):
        c=create_controller(); set_queue(c,'NS',20); set_queue(c,'EW',1); tick(c,29); self.assertEqual('NS_GREEN',snapshot(c)['state']); tick(c,1); self.assertEqual('ALL_RED',snapshot(c)['state'])

    def test_max_green_no_red_queue_stays(self):
        c=create_controller(); tick(c,31); s=snapshot(c); self.assertEqual('NS_GREEN',s['state']); self.assertEqual(31,s['elapsed'])

    def test_all_red_exact_two_seconds_and_queue_clear(self):
        c=create_controller(); set_queue(c,'EW',3); tick(c,10); self.assertEqual('ALL_RED',snapshot(c)['state']); tick(c,1); self.assertEqual('ALL_RED',snapshot(c)['state']); tick(c,1); s=snapshot(c); self.assertEqual('EW_GREEN',s['state']); self.assertEqual(0,s['ew_queue'])

    def test_large_tick_continues_after_transition(self):
        c=create_controller(); set_queue(c,'EW',3); tick(c,15); s=snapshot(c); self.assertEqual('EW_GREEN',s['state']); self.assertEqual(3,s['elapsed'])

    def test_emergency_other_direction_immediate(self):
        c=create_controller(); set_emergency(c,'EW'); self.assertEqual('ALL_RED',snapshot(c)['state']); tick(c,2); s=snapshot(c); self.assertEqual('EW_GREEN',s['state']); self.assertFalse(s['ew_emergency'])

    def test_emergency_current_green_does_not_switch(self):
        c=create_controller(); set_emergency(c,'NS'); tick(c,1); self.assertEqual('NS_GREEN',snapshot(c)['state'])

    def test_latest_emergency_resets_all_red_timer(self):
        c=create_controller(); set_emergency(c,'EW'); tick(c,1); set_emergency(c,'NS'); tick(c,1); self.assertEqual('ALL_RED',snapshot(c)['state']); tick(c,1); self.assertEqual('NS_GREEN',snapshot(c)['state'])

    def test_queue_bounds_zero_and_twenty(self):
        c=create_controller(); set_queue(c,'NS',0); set_queue(c,'EW',20); s=snapshot(c); self.assertEqual(0,s['ns_queue']); self.assertEqual(20,s['ew_queue'])

    def test_invalid_queue_preserves_state(self):
        c=create_controller(); set_queue(c,'NS',5); before=snapshot(c).copy()
        for value in (-1,21,1.5,True):
            with self.assertRaises(ValueError): set_queue(c,'NS',value)
            self.assertEqual(before,snapshot(c))

    def test_invalid_direction_preserves_state(self):
        c=create_controller(); before=snapshot(c).copy()
        with self.assertRaises(ValueError): set_queue(c,'XX',1)
        self.assertEqual(before,snapshot(c))

    def test_tick_requires_positive_integer(self):
        c=create_controller(); before=snapshot(c).copy()
        for value in (0,-1,1.5,True):
            with self.assertRaises(ValueError): tick(c,value)
            self.assertEqual(before,snapshot(c))

    def test_emergency_enabled_requires_bool(self):
        c=create_controller(); before=snapshot(c).copy()
        with self.assertRaises(ValueError): set_emergency(c,'EW',1)
        self.assertEqual(before,snapshot(c))

    def test_queue_over_ten_is_not_clamped(self):
        c=create_controller(); set_queue(c,'NS',17); self.assertEqual(17,snapshot(c)['ns_queue'])

    def test_all_red_normal_target_not_changed_by_queue(self):
        c=create_controller(); set_queue(c,'EW',3); tick(c,10); set_queue(c,'NS',20); tick(c,2); self.assertEqual('EW_GREEN',snapshot(c)['state'])

    def test_repeated_same_emergency_does_not_restart_all_red(self):
        c=create_controller(); set_emergency(c,'EW'); tick(c,1); set_emergency(c,'EW',True); tick(c,1); self.assertEqual('EW_GREEN',snapshot(c)['state'])

    def test_latest_emergency_reverse_direction(self):
        c=create_controller(); set_emergency(c,'EW'); tick(c,2); set_emergency(c,'NS'); tick(c,1); set_emergency(c,'EW'); tick(c,2); self.assertEqual('EW_GREEN',snapshot(c)['state'])

    def test_non_target_queue_preserved_after_transition(self):
        c=create_controller(); set_queue(c,'NS',5); set_queue(c,'EW',8); tick(c,10); tick(c,2); s=snapshot(c); self.assertEqual('EW_GREEN',s['state']); self.assertEqual(5,s['ns_queue']); self.assertEqual(0,s['ew_queue'])

if __name__=='__main__': unittest.main()
