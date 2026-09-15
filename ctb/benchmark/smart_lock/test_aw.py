from implementation.controller import SmartLockController

def create_controller(): return SmartLockController()
def enter_pin(ctrl, door, pin): return ctrl.enter_pin(door, pin)
def open_door(ctrl, door): return ctrl.open_door(door)
def close_door(ctrl, door): return ctrl.close_door(door)
def admin_reset(ctrl, door): return ctrl.admin_reset(door)
def tick(ctrl, seconds): return ctrl.tick(seconds)
def snapshot(ctrl, door): return ctrl.snapshot(door)
