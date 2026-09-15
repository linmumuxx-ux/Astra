from implementation.controller import TrafficController

def create_controller(): return TrafficController()
def set_queue(ctrl,direction,count): ctrl.set_queue(direction,count)
def set_emergency(ctrl,direction,enabled=True): ctrl.set_emergency(direction,enabled)
def tick(ctrl,seconds): ctrl.tick(seconds)
def snapshot(ctrl): return ctrl.snapshot()
