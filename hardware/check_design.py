"""Verify the KiCad netlist exported from the schematic.

- every one of the 58 test lines: connector pin -> 220R -> correct MCP23017 pin,
  exactly as firmware/hwmap.py expects
- no DUT connector pin touches GND / +3V3 / +5V or any other net
- MCP address straps match hwmap.ADDRS

Run:  kicad-cli sch export netlist --format kicadsexpr -o cable_tester.net cable_tester.kicad_sch
      python check_design.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware"))
import hwmap  # noqa: E402
from gen_schematic import parse, find, first  # noqa: E402

tree = parse(open(os.path.join(HERE, "cable_tester.net"), encoding="utf-8").read())
nets = {}   # net name -> set of (ref, pin)
pinnet = {}  # (ref, pin) -> net name
pinname = {}
for net in find(first(tree, "nets"), "net"):
    name = first(net, "name")[1].lstrip("/")
    for node in find(net, "node"):
        key = (first(node, "ref")[1], first(node, "pin")[1])
        nets.setdefault(name, set()).add(key)
        pinnet[key] = name
        pn = first(node, "pinfunction")
        pinname[key] = pn[1] if pn else ""

errors = []


def err(msg):
    errors.append(msg)


# MCP pin name -> number, from the netlist's pinfunction
mcp_pin = {}
for (ref, num), fn in pinname.items():
    if ref.startswith("U") and fn:
        mcp_pin[(ref, fn)] = num

conn = {"H": "J1"}
for k in (1, 2, 3):
    conn["T%d" % k] = "J%d" % (k + 1)

for name, chip, bit in hwmap.LINES:
    if name.startswith("H"):
        cref, cpin = "J1", name[1:]
    else:
        port, p = name[1:].split(".")
        cref, cpin = "J%d" % (int(port) + 1), p
    n1 = pinnet.get((cref, cpin))
    if n1 is None:
        err("%s: %s pin %s unconnected" % (name, cref, cpin))
        continue
    members = nets[n1]
    others = [m for m in members if m != (cref, cpin)]
    if len(others) != 1 or not others[0][0].startswith("RN"):
        err("%s: connector net %s has %s (expected exactly one RN pin)" % (name, n1, sorted(others)))
        continue
    rn, rpin = others[0]
    rpin2 = str(9 - int(rpin))  # R_Pack04: 1<->8, 2<->7, 3<->6, 4<->5
    n2 = pinnet.get((rn, rpin2))
    io = [m for m in nets.get(n2, ()) if m != (rn, rpin2)]
    want_ref = "U%d" % (chip + 1)
    want_fn = ("GPA%d" if bit < 8 else "GPB%d") % (bit % 8)
    want = (want_ref, mcp_pin.get((want_ref, want_fn)))
    if io != [want]:
        err("%s: IO side %s reaches %s, expected %s %s" % (name, n2, io, want_ref, want_fn))

# address straps
for i, addr in enumerate(hwmap.ADDRS):
    ref = "U%d" % (i + 1)
    val = 0x20
    for bitn, fn in ((0, "A0"), (1, "A1"), (2, "A2")):
        net = pinnet.get((ref, mcp_pin.get((ref, fn))))
        if net == "+3V3":
            val |= 1 << bitn
        elif net != "GND":
            err("%s %s on %s" % (ref, fn, net))
    if val != addr:
        err("%s strapped to 0x%02X, firmware expects 0x%02X" % (ref, val, addr))

# DUT pins must never be on a power net
for (ref, num), net in pinnet.items():
    if ref in ("J1", "J2", "J3", "J4") and net in ("GND", "+3V3", "+5V"):
        err("DUT pin %s.%s is on power net %s" % (ref, num, net))

print("checked %d test lines, %d nets" % (len(hwmap.LINES), len(nets)))
for e in errors:
    print("ERROR", e)
print("OK" if not errors else "%d error(s)" % len(errors))
sys.exit(1 if errors else 0)
