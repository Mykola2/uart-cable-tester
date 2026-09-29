"""PC tests: simulated MCP23017s + simulated cables -> scan -> evaluate -> session.

Run:  python firmware/pc_tests/test_tester.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import hwmap  # noqa: E402
import tester  # noqa: E402
from mcp_bus import Expanders  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(HERE), "wiring.json")))
NETS = CFG["nets"]
ANY = CFG["any_of"]
# a concrete cable: each wire lands on one pin (GND wires on the first choice)
GOOD_WIRING = {"T1_GND": ["T1.6", "H6"], "T2_GND": ["T2.6", "H9"], "T3_GND": ["T3.6", "H34"]}
LEDS = CFG["leds"]


class SimI2C:
    """Register-level model of 4 MCP23017 (BANK=0, sequential addressing)
    wired to a cable given as a list of connected pin groups."""

    def __init__(self, groups, stuck=()):
        self.regs = {a: bytearray(0x16) for a in hwmap.ADDRS}
        for r in self.regs.values():
            r[0] = r[1] = 0xFF  # IODIR resets to inputs
        self.set_cable(groups, stuck)
        self.transactions = 0

    def set_cable(self, groups, stuck=()):
        self.group_of = {}
        for g in groups:
            for p in g:
                self.group_of[hwmap.INDEX[p]] = [hwmap.INDEX[q] for q in g]
        self.stuck = {hwmap.INDEX[p] for p in stuck}

    def scan(self):
        return list(hwmap.ADDRS)

    def writeto(self, addr, buf):
        self.transactions += 1
        reg = buf[0]
        for k, v in enumerate(buf[1:]):
            self.regs[addr][reg + k] = v

    def _driven_low(self, i):
        c, b = hwmap.CHIPBITS[i]
        r = self.regs[hwmap.ADDRS[c]]
        iodir = r[0] | (r[1] << 8)
        olat = r[0x14] | (r[0x15] << 8)
        return not (iodir >> b) & 1 and not (olat >> b) & 1

    def _level(self, i):
        if i in self.stuck:
            return 0
        for j in self.group_of.get(i, [i]):
            if self._driven_low(j):
                return 0
        return 1  # pulled up

    def writeto_then_readfrom(self, addr, out, inbuf):
        self.transactions += 1
        reg = out[0]
        chip = hwmap.ADDRS.index(addr)
        gpio = 0xFFFF
        for i, (c, b) in enumerate(hwmap.CHIPBITS):
            if c == chip and not self._level(i):
                gpio &= ~(1 << b)
        for k in range(len(inbuf)):
            rr = reg + k
            inbuf[k] = (gpio & 0xFF) if rr == 0x12 else (gpio >> 8) if rr == 0x13 else self.regs[addr][rr]


def good():
    return [list(GOOD_WIRING.get(n, p)) for n, p in NETS.items()]


def run(groups, stuck=()):
    i2c = SimI2C(groups, stuck)
    bus = Expanders(i2c, hwmap.ADDRS)
    bus.init()
    adj, st = bus.scan(hwmap.CHIPBITS)
    return tester.evaluate(hwmap.NAMES, adj, st, NETS, hwmap.INDEX, ANY), adj, i2c


def replace(groups, old, new):
    return [[new if p == old else p for p in g] for g in groups]


failures = 0


def check(name, cond, detail=""):
    global failures
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail))
    if not cond:
        failures += 1


# --- static evaluation cases -------------------------------------------------
errs = tester.validate(NETS, LEDS, hwmap.INDEX, ANY)
check("wiring.json valid", not errs, errs)

r, adj, i2c = run(good())
check("good cable passes", r.passed and r.connected, r.faults)
check("scan transaction count", i2c.transactions < 400, i2c.transactions)
leds, _ = tester.led_status(r.status, NETS, LEDS)
check("all 9 LEDs OK", leds == [tester.OK] * 9, leds)

r, _, _ = run([], ())
check("nothing plugged -> not connected", not r.connected and not r.passed)

g = [p for p in good() if "T2.3" not in p]  # T2_RX wire missing
r, _, _ = run(g)
check("open wire", r.status["T2_RX"] == tester.OPEN and sum(s != tester.OK for s in r.status.values()) == 1, r.faults)
leds, _ = tester.led_status(r.status, NETS, LEDS)
check("open -> only LED5 red", leds[4] == tester.OPEN and leds.count(tester.OK) == 8, leds)

g = replace(replace(good(), "T1.2", "X"), "T1.3", "T1.2")
g = replace(g, "X", "T1.3")  # TX/RX crossed at the JST
r, _, _ = run(g)
check("TX/RX swap", r.status["T1_TX"] == tester.MISWIRE and r.status["T1_RX"] == tester.MISWIRE, r.faults)

g = good()
g = [g[0] + g[1]] + g[2:]  # T1_TX bridged to T1_RX
r, _, _ = run(g)
check("short between nets", r.status["T1_TX"] == tester.SHORT and r.status["T1_RX"] == tester.SHORT, r.faults)

r, _, _ = run(replace(good(), "T3.6", "T3.5"))  # GND wire in wrong cavity
check("GND in wrong JST cavity -> MISWIRE", r.status["T3_GND"] == tester.MISWIRE and not r.passed, r.faults)

r, _, _ = run(replace(good(), "H10", "H12"))  # TX on the wrong header pin
check("wrong header pin (signal)", r.status["T1_TX"] == tester.MISWIRE, r.faults)

# --- ground may land on any Pi GND pin --------------------------------------------
r, _, _ = run(replace(replace(replace(good(), "H6", "H14"), "H9", "H39"), "H34", "H20"))
check("GND wires on other Pi GND pins pass", r.passed, r.faults)

g = [p for p in good() if "T2.6" not in p and "T3.6" not in p] + [["T2.6", "T3.6", "H25"]]
r, _, _ = run(g)
check("two GND wires sharing one Pi GND pin pass", r.passed, r.faults)

r, _, _ = run(replace(good(), "H6", "H11"))  # GND wire on a signal pin
check("GND wire on non-GND pin -> MISWIRE", r.status["T1_GND"] == tester.MISWIRE, r.faults)

r, _, _ = run([p for p in good() if "T1.6" not in p] + [["T1.6"]])
check("GND wire open -> OPEN", r.status["T1_GND"] == tester.OPEN, r.faults)

r, _, _ = run(replace(good(), "H6", "H10"))  # GND wire onto T1 TX pin
check("GND wire onto a used signal pin", r.status["T1_GND"] == tester.MISWIRE and r.status["T1_TX"] == tester.SHORT, r.faults)

r, _, _ = run(good() + [["H14", "H20"]])
check("bridge between two Pi GND pins is harmless", r.passed, r.faults)

r, _, _ = run(good() + [["H14", "H13"]])
check("bridge Pi GND to signal pin fails", not r.passed, r.faults)

r, _, _ = run(replace(good(), "T1.6", "T1.5"))  # GND in wrong JST cavity
check("GND in wrong JST cavity (T1)", r.status["T1_GND"] == tester.MISWIRE and not r.passed, r.faults)

r, _, _ = run(good() + [["H11", "H12"]])
check("stray bridge on unused pins", not r.passed and any(f.startswith("STRAY") for f in r.faults), r.faults)

g = [p + ["H40"] if "H10" in p else p for p in good()]  # extra solder blob to unused pin
r, _, _ = run(g)
check("short to unused pin", r.status["T1_TX"] == tester.SHORT, r.faults)

r, _, _ = run(good(), stuck=["H5"])
check("stuck line", not r.passed and any("STUCK_LOW H5" in f for f in r.faults), r.faults)

r, adj, _ = run(good())
learned = tester.learn(hwmap.NAMES, adj, ANY)
check("learn reproduces map", {k: sorted(v) for k, v in learned.items()} == {k: sorted(v) for k, v in NETS.items()}, learned)

# --- session state machine ----------------------------------------------------
GOOD = run(good())[0]
EMPTY = run([])[0]
OPENR = run([p for p in good() if "T2.3" not in p])[0]


def drive(seq, dt=0.1):
    """seq: list of (result, n_scans). Returns list of (t, event)."""
    s = tester.Session()
    t = 0.0
    evs = []
    for res, n in seq:
        for _ in range(n):
            ev = s.update(t, res)
            if ev:
                evs.append((round(t, 1), ev[0]))
            t += dt
    return s, evs


s, evs = drive([(EMPTY, 5), (GOOD, 10)])
check("session: good -> PASS quickly", [e for _, e in evs] == ["PASS"] and evs[0][0] <= 1.0, evs)

s, evs = drive([(OPENR, 20), (GOOD, 10)])
check("session: plugging in (partial) does not fail early", [e for _, e in evs] == ["PASS"], evs)

s, evs = drive([(OPENR, 40)])
check("session: persistent fault -> FAIL after ~3s", [e for _, e in evs] == ["FAIL"], evs)

s, evs = drive([(GOOD, 10), (OPENR, 2), (GOOD, 5)])
check("session: wiggle glitch -> INTERMITTENT", [e for _, e in evs] == ["PASS", "INTERMITTENT"]
      and s.latched.get("T2_RX") == tester.OPEN, (evs, s.latched))

s, evs = drive([(GOOD, 10), (OPENR, 30), (EMPTY, 15)])
check("session: unplug after PASS is not flagged", [e for _, e in evs] == ["PASS"] and s.state == tester.IDLE, evs)

s, evs = drive([(GOOD, 10), (EMPTY, 15), (OPENR, 40)])
check("session: next cable gets its own verdict", [e for _, e in evs] == ["PASS", "FAIL"], evs)

# --- scan timing estimate ------------------------------------------------------
i2c = SimI2C(good())
bus = Expanders(i2c, hwmap.ADDRS)
bus.init()
i2c.transactions = 0
bus.scan(hwmap.CHIPBITS)
# 400 kHz: ~3 bytes write ~0.1 ms, write+read(2) ~0.15 ms, plus ~0.2 ms CircuitPython overhead each
est = i2c.transactions * 0.35
print("# scan: %d I2C transactions, est. %.0f ms on RP2040/CircuitPython" % (i2c.transactions, est))

print("\n%d failure(s)" % failures)
sys.exit(1 if failures else 0)
