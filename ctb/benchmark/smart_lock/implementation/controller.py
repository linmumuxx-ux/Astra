class SmartLockController:
    VALID_PIN = "2468"
    DOORS = ("FRONT", "BACK")

    def __init__(self):
        self.d = {
            name: {
                "locked": True,
                "door_open": False,
                "failed_attempts": 0,
                "lockout_remaining": 0,
                "unlock_remaining": 0,
            }
            for name in self.DOORS
        }

    def _door(self, door):
        if door not in self.DOORS:
            raise ValueError("door")
        return self.d[door]

    def _pin(self, pin):
        if type(pin) is not str or len(pin) != 4 or not pin.isdigit():
            raise ValueError("pin")

    def enter_pin(self, door, pin):
        s = self._door(door)
        self._pin(pin)
        if s["lockout_remaining"] > 0:
            return False
        if not s["locked"]:
            return pin == self.VALID_PIN
        if pin == self.VALID_PIN:
            s["locked"] = False
            s["unlock_remaining"] = 10
            s["failed_attempts"] = 0
            return True
        s["failed_attempts"] += 1
        if s["failed_attempts"] >= 3:
            s["failed_attempts"] = 0
            s["lockout_remaining"] = 30
        return False

    def open_door(self, door):
        s = self._door(door)
        if s["locked"]:
            return False
        s["door_open"] = True
        return True

    def close_door(self, door):
        s = self._door(door)
        if not s["door_open"]:
            return
        s["door_open"] = False
        if s["unlock_remaining"] == 0:
            s["locked"] = True

    def admin_reset(self, door):
        s = self._door(door)
        s["failed_attempts"] = 0
        s["lockout_remaining"] = 0

    def tick(self, seconds):
        if type(seconds) is not int or seconds <= 0:
            raise ValueError("seconds")
        for _ in range(seconds):
            for s in self.d.values():
                if s["lockout_remaining"] > 0:
                    s["lockout_remaining"] -= 1
                if not s["locked"] and s["unlock_remaining"] > 0:
                    s["unlock_remaining"] -= 1
                    if s["unlock_remaining"] == 0 and not s["door_open"]:
                        s["locked"] = True

    def snapshot(self, door):
        return dict(self._door(door))
