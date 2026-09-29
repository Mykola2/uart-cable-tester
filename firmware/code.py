# RPi <-> CUAV X7 telemetry cable tester - CircuitPython main program.
# Hardware: RP2040 Pico module, 4x MCP23017 (0x20-0x23) on I2C0 (GP4/GP5),
# 10x WS2812B on GP16 (D1-D9 wires, D10 status), button GP15, buzzer GP14.

import json
import struct
import time

import board
import busio
import digitalio
import microcontroller
import neopixel_write

import hwmap
import tester
from mcp_bus import Expanders

WIRE_LEDS = 9
STATUS_LED = 9
LONG_PRESS_S = 3.0

OFF = (0, 0, 0)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
MAGENTA = (255, 0, 255)
ORANGE = (255, 90, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)
COLORS = {tester.OK: GREEN, tester.OPEN: RED, tester.MISWIRE: ORANGE,
          tester.SHORT: MAGENTA, tester.UNUSED: OFF}

NVM_MAGIC = b"LRN1"


class Pixels:
    def __init__(self, pin, n):
        self.io = digitalio.DigitalInOut(pin)
        self.io.direction = digitalio.Direction.OUTPUT
        self.buf = bytearray(3 * n)
        self.brightness = 0.15

    def __setitem__(self, i, rgb):
        s = self.brightness
        self.buf[3 * i] = int(rgb[1] * s)  # WS2812 byte order is GRB
        self.buf[3 * i + 1] = int(rgb[0] * s)
        self.buf[3 * i + 2] = int(rgb[2] * s)

    def fill(self, rgb):
        for i in range(len(self.buf) // 3):
            self[i] = rgb

    def show(self):
        neopixel_write.neopixel_write(self.io, self.buf)


class Buzzer:
    def __init__(self, pin):
        self.io = digitalio.DigitalInOut(pin)
        self.io.direction = digitalio.Direction.OUTPUT
        self.io.value = False
        self.seq = []
        self.until = 0

    def play(self, pattern):
        self.seq = list(pattern)
        self._next(time.monotonic())

    def _next(self, now):
        if self.seq:
            on, dur = self.seq.pop(0)
            self.io.value = on
            self.until = now + dur
        else:
            self.io.value = False
            self.until = 0

    def update(self, now):
        if self.until and now >= self.until:
            self._next(now)


def beeps(n, on=0.07, off=0.12):
    out = []
    for _ in range(n):
        out += [(True, on), (False, off)]
    return out


BEEP_PASS = [(True, 0.08)]
BEEP_FAIL = [(True, 0.7)]
BEEP_GLITCH = beeps(3, 0.04, 0.06)


class Button:
    """Active-low button. update() returns 'short' on release or 'long' once
    while held for LONG_PRESS_S."""

    def __init__(self, pin):
        self.io = digitalio.DigitalInOut(pin)
        self.io.switch_to_input(pull=digitalio.Pull.UP)
        self.down_since = None
        self.long_fired = False

    def update(self, now):
        pressed = not self.io.value
        if pressed:
            if self.down_since is None:
                self.down_since = now
                self.long_fired = False
            elif not self.long_fired and now - self.down_since >= LONG_PRESS_S:
                self.long_fired = True
                return "long"
            return None
        if self.down_since is not None:
            held = now - self.down_since
            self.down_since = None
            if not self.long_fired and held >= 0.03:
                return "short"
        return None


def fnv1a(data):
    h = 2166136261
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def nvm_load(wiring_hash):
    """Learned nets, only if learned against the current wiring.json (editing
    wiring.json therefore overrides an old learned map)."""
    nvm = microcontroller.nvm
    if nvm is None or bytes(nvm[0:4]) != NVM_MAGIC:
        return None
    h, n = struct.unpack("<II", bytes(nvm[4:12]))
    if h != wiring_hash or n > len(nvm) - 12:
        return None
    try:
        return json.loads(bytes(nvm[12:12 + n]))
    except ValueError:
        return None


def nvm_save(wiring_hash, nets):
    nvm = microcontroller.nvm
    data = json.dumps(nets).encode()
    if nvm is None or len(data) > len(nvm) - 12:
        print("# learn: map too large for NVM, not saved")
        return False
    nvm[12:12 + len(data)] = data
    nvm[4:12] = struct.pack("<II", wiring_hash, len(data))
    nvm[0:4] = NVM_MAGIC
    return True


def nvm_clear():
    if microcontroller.nvm is not None:
        microcontroller.nvm[0:4] = b"\x00\x00\x00\x00"


def fatal(pixels, msg):
    print("# ERROR:", msg)
    while True:
        pixels.fill(OFF)
        pixels[STATUS_LED] = MAGENTA if int(time.monotonic() * 2) % 2 else OFF
        pixels.show()
        time.sleep(0.1)


def main():
    pixels = Pixels(board.GP16, WIRE_LEDS + 1)
    buzzer = Buzzer(board.GP14)
    button = Button(board.GP15)
    pixels.fill(OFF)
    pixels.show()

    raw = open("/wiring.json", "rb").read()
    cfg = json.loads(raw)
    wiring_hash = fnv1a(raw)
    pixels.brightness = cfg.get("brightness", 0.15)
    leds = cfg["leds"][:WIRE_LEDS]
    any_of = cfg.get("any_of", {})
    nets = nvm_load(wiring_hash)
    source = "learned (NVM)"
    if nets is None:
        nets = cfg["nets"]
        source = "wiring.json"
    errors = tester.validate(nets, leds, hwmap.INDEX, any_of)
    if errors:
        fatal(pixels, "; ".join(errors))

    i2c = busio.I2C(board.GP5, board.GP4, frequency=400000)
    while not i2c.try_lock():
        pass
    bus = Expanders(i2c, hwmap.ADDRS)
    missing = bus.missing()
    if missing:
        fatal(pixels, "MCP23017 not found at " + ", ".join(hex(a) for a in missing))
    bus.init()

    session = tester.Session(cfg.get("pass_stable_s", 0.3), cfg.get("fail_stable_s", 3.0),
                             cfg.get("glitch_window_s", 2.0), cfg.get("idle_after_s", 1.0))
    count = 0
    print("# cable tester ready, %d nets from %s" % (len(nets), source))
    print("time_s,count,result,faults")

    while True:
        adj, stuck = bus.scan(hwmap.CHIPBITS)
        now = time.monotonic()
        res = tester.evaluate(hwmap.NAMES, adj, stuck, nets, hwmap.INDEX, any_of)
        press = button.update(now)

        if press == "long":
            if res.connected and not stuck:
                nets = tester.learn(hwmap.NAMES, adj, any_of)
                saved = nvm_save(wiring_hash, nets)
                print("# learned %d nets%s:" % (len(nets), "" if saved else " (NOT saved)"))
                print(json.dumps({"nets": nets}))
                buzzer.play(beeps(len(nets)))
                for _ in range(3):
                    pixels.fill(BLUE)
                    pixels.show()
                    time.sleep(0.15)
                    pixels.fill(OFF)
                    pixels.show()
                    time.sleep(0.15)
            else:
                nvm_clear()
                nets = cfg["nets"]
                print("# learned map cleared, using wiring.json")
                buzzer.play([(True, 0.3), (False, 0.2), (True, 0.3)])
            session = tester.Session(session.pass_stable_s, session.fail_stable_s,
                                     session.glitch_window_s, session.idle_after_s)
            continue

        ev = session.update(now, res, retest=(press == "short"))
        if ev:
            verdict, faults = ev
            if verdict != tester.INTERMITTENT and faults != ["after reseat"]:
                count += 1
            print("%.1f,%d,%s,%s" % (now, count, verdict, " ; ".join(faults)))
            buzzer.play({tester.PASS: BEEP_PASS, tester.FAIL: BEEP_FAIL}.get(verdict, BEEP_GLITCH))
        buzzer.update(now)

        # LEDs
        blink = int(now * 4) % 2 == 0
        if session.state == tester.IDLE:
            pixels.fill(OFF)
            pixels[STATUS_LED] = (0, 0, 60)
        else:
            states, led_nets = tester.led_status(res.status, nets, leds)
            for i, st in enumerate(states):
                latched = session.latched.get(led_nets[i])
                if latched and blink:
                    pixels[i] = COLORS[latched]
                else:
                    pixels[i] = COLORS[st]
            if session.state == tester.TESTING:
                pixels[STATUS_LED] = ORANGE if blink else OFF
            elif session.verdict == tester.PASS:
                pixels[STATUS_LED] = GREEN
            elif session.verdict == tester.FAIL:
                pixels[STATUS_LED] = RED
            else:  # INTERMITTENT
                pixels[STATUS_LED] = RED if blink else OFF
        pixels.show()


main()
