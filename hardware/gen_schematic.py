"""Generate cable_tester.kicad_sch (KiCad 9) from design.py.

Symbols are copied from the installed KiCad libraries and every pin is
connected with a net label at its end, so the result is an ordinary,
editable KiCad schematic.

Run:  python gen_schematic.py
"""
import copy
import os
import re
import uuid

import design

KICAD = os.environ.get("KICAD9_DIR", r"C:\Program Files\KiCad\9.0")
SYMDIR = os.path.join(KICAD, "share", "kicad", "symbols")
PROJECT = "cable_tester"
HERE = os.path.dirname(os.path.abspath(__file__))
NS = uuid.UUID("6b1d3f0e-7c1a-4d5e-9a57-cab1e7e57e20")


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


# ---- tiny s-expression reader/writer ------------------------------------------
class Q(str):
    """A quoted string token."""


TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def parse(text):
    stack = [[]]
    pos = 0
    while True:
        m = TOKEN.match(text, pos)
        if not m:
            break
        pos = m.end()
        if m.group(1):
            stack.append([])
        elif m.group(2):
            done = stack.pop()
            stack[-1].append(done)
        elif m.group(3) is not None:
            stack[-1].append(Q(m.group(3).replace('\\"', '"').replace("\\\\", "\\")))
        else:
            stack[-1].append(m.group(4))
    return stack[0][0]


def dump(node, indent=0):
    if not isinstance(node, list):
        if isinstance(node, Q):
            return '"%s"' % node.replace("\\", "\\\\").replace('"', '\\"')
        return str(node)
    simple = all(not isinstance(c, list) for c in node)
    if simple:
        return "(" + " ".join(dump(c) for c in node) + ")"
    pad = "\t" * (indent + 1)
    out = "(" + " ".join(dump(c) for c in node if not isinstance(c, list))
    for c in node:
        if isinstance(c, list):
            out += "\n" + pad + dump(c, indent + 1)
    return out + "\n" + "\t" * indent + ")"


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def first(node, key):
    r = find(node, key)
    return r[0] if r else None


# ---- library access ---------------------------------------------------------------
_libs = {}


def lib(name):
    if name not in _libs:
        with open(os.path.join(SYMDIR, name + ".kicad_sym"), encoding="utf-8") as f:
            _libs[name] = parse(f.read())
    return _libs[name]


def lib_symbol(libname, name):
    """Flattened symbol definition (resolves 'extends')."""
    for s in find(lib(libname), "symbol"):
        if s[1] == name:
            break
    else:
        raise KeyError("%s:%s" % (libname, name))
    ext = first(s, "extends")
    if not ext:
        return copy.deepcopy(s)
    parent = lib_symbol(libname, ext[1])
    out = copy.deepcopy(parent)
    out[1] = Q(name)
    child_props = {p[1]: p for p in find(s, "property")}
    new = []
    for c in out:
        if isinstance(c, list) and c and c[0] == "property" and c[1] in child_props:
            new.append(copy.deepcopy(child_props.pop(c[1])))
        elif isinstance(c, list) and c and c[0] == "symbol":
            c = copy.deepcopy(c)
            c[1] = Q(name + c[1][len(ext[1]):])
            new.append(c)
        else:
            new.append(c)
    # properties only present on the child go after the parent's properties
    idx = max(i for i, c in enumerate(new) if isinstance(c, list) and c and c[0] == "property") + 1
    for p in child_props.values():
        new.insert(idx, copy.deepcopy(p))
        idx += 1
    return new


def symbol_pins(sym):
    """[(unit, number, name, etype, x, y, angle, hidden)] for body style 1."""
    pins = []
    for sub in find(sym, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", sub[1])
        unit, style = int(m.group(1)), int(m.group(2))
        if style not in (0, 1):
            continue
        for p in find(sub, "pin"):
            at = first(p, "at")
            hidden = "hide" in p or any(isinstance(c, list) and c[:2] == ["hide", "yes"] for c in p)
            pins.append((unit, first(p, "number")[1], first(p, "name")[1], p[1],
                         float(at[1]), float(at[2]), int(float(at[3])) if len(at) > 3 else 0, hidden))
    return pins


def units_of(sym):
    us = set()
    for sub in find(sym, "symbol"):
        u = int(re.match(r".*_(\d+)_\d+$", sub[1]).group(1))
        if u:
            us.add(u)
    return sorted(us) or [1]


# ---- schematic building ---------------------------------------------------------------
def fmt(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def effects(size=1.27, justify=None, hide=False):
    e = ["effects", ["font", ["size", fmt(size), fmt(size)]]]
    if justify:
        e.append(["justify"] + justify.split())
    if hide:
        e.append(["hide", "yes"])
    return e


def prop(name, value, x, y, hide=False, pid=None):
    return ["property", Q(name), Q(value), ["at", fmt(x), fmt(y), "0"], effects(hide=hide)]


# pin angle (direction from pin end towards the body) -> label angle, justify
LABEL_DIR = {0: ("180", "right bottom"), 180: ("0", "left bottom"),
             90: ("270", "right bottom"), 270: ("90", "left bottom")}


def resolve_pins(part, pins):
    """Map design pin keys (number or name) -> net for each pin number."""
    by_num = {p[1]: p for p in pins}
    netmap = {}
    for key, net in part.pins.items():
        if key in by_num:
            netmap[key] = net
            continue
        hits = [p[1] for p in pins if p[2] == key]
        if not hits:
            raise KeyError("%s: no pin %r in %s:%s" % (part.ref, key, part.lib, part.sym))
        for num in hits:
            netmap[num] = net
    return netmap


def build():
    root = uid("root")
    lib_symbols = ["lib_symbols"]
    body = []
    seen = set()
    nets = {}  # net -> [(ref, pin)]
    for part in design.PARTS:
        lib_id = "%s:%s" % (part.lib, part.sym)
        sym = lib_symbol(part.lib, part.sym)
        if lib_id not in seen:
            seen.add(lib_id)
            emb = copy.deepcopy(sym)
            emb[1] = Q(lib_id)
            lib_symbols.append(emb)
        pins = symbol_pins(sym)
        netmap = resolve_pins(part, pins)
        units = units_of(sym)
        for ui, unit in enumerate(units):
            X, Y = part.sch[0] + 25.4 * ui, part.sch[1]
            su = uid("sym", part.ref, unit)
            inst = ["symbol", ["lib_id", Q(lib_id)], ["at", fmt(X), fmt(Y), "0"], ["unit", str(unit)],
                    ["exclude_from_sim", "no"], ["in_bom", "yes" if part.ref[:2] != "MH" else "no"],
                    ["on_board", "yes"], ["dnp", "no"], ["uuid", Q(su)],
                    prop("Reference", part.ref, X, Y - 3.0),
                    prop("Value", part.value, X, Y + 3.0),
                    prop("Footprint", part.footprint, X, Y, hide=True),
                    prop("Datasheet", "", X, Y, hide=True),
                    prop("MPN", part.mpn, X, Y, hide=True)]
            # Place Reference/Value above/below the pin bbox
            upins = [p for p in pins if p[0] in (0, unit)]
            if upins:
                top = max(p[5] for p in upins)
                bot = min(p[5] for p in upins)
                inst[9][3] = ["at", fmt(X + 2.54), fmt(Y - max(top, 2.54) - 1.27), "0"]
                inst[10][3] = ["at", fmt(X + 2.54), fmt(Y - min(bot, -2.54) + 2.54), "0"]
            for p in upins:
                inst.append(["pin", Q(p[1]), ["uuid", Q(uid("pin", part.ref, p[1]))]])
            inst.append(["instances", ["project", Q(PROJECT),
                         ["path", Q("/" + root), ["reference", Q(part.ref)], ["unit", str(unit)]]]])
            body.append(inst)
            done = {}  # stacked pins (e.g. Pico GND) share one endpoint: label it once
            for (u, num, name, etype, px, py, ang, hidden) in sorted(upins, key=lambda p: (p[7], p[1] not in netmap)):
                ex, ey = X + px, Y - py
                if etype == "no_connect":
                    continue
                net = netmap.get(num)
                key = (round(ex, 3), round(ey, 3))
                if key in done:
                    if net is not None and net != done[key]:
                        raise ValueError("%s: stacked pins on different nets" % part.ref)
                    if net is not None:
                        nets.setdefault(net, []).append((part.ref, num))
                    continue
                done[key] = net
                if net is None:
                    body.append(["no_connect", ["at", fmt(ex), fmt(ey)], ["uuid", Q(uid("nc", part.ref, num))]])
                    continue
                nets.setdefault(net, []).append((part.ref, num))
                la, just = LABEL_DIR[ang % 360]
                body.append(["label", Q(net), ["at", fmt(ex), fmt(ey), la], effects(1.27, just),
                             ["uuid", Q(uid("lbl", part.ref, num))]])
    sch = ["kicad_sch", ["version", "20250114"], ["generator", Q("eeschema")],
           ["generator_version", Q("9.0")], ["uuid", Q(root)], ["paper", Q("A2")],
           ["title_block", ["title", Q("RPi <-> CUAV X7 telemetry cable tester")],
            ["rev", Q("A")], ["comment", "1", Q("Generated by gen_schematic.py from design.py")]],
           lib_symbols] + body + [["sheet_instances", ["path", Q("/"), ["page", Q("1")]]],
                                  ["embedded_fonts", "no"]]
    return sch, nets, root


def write_bom(path):
    groups = {}
    for p in design.PARTS:
        if p.ref.startswith("MH"):
            continue
        groups.setdefault((p.value, p.footprint, p.mpn), []).append(p)

    def refkey(r):
        m = re.match(r"([A-Z]+)(\d+)", r)
        return (m.group(1), int(m.group(2)))

    rows = sorted(groups.items(), key=lambda kv: refkey(min((x.ref for x in kv[1]), key=refkey)))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("Qty,References,Value,Footprint,MPN,LCSC (fill in),Notes\n")
        for (value, fp, mpn), parts in rows:
            refs = " ".join(sorted((x.ref for x in parts), key=refkey))
            notes = "; ".join(sorted(set(x.note for x in parts if x.note and not x.ref.startswith("D"))))
            f.write('%d,"%s","%s","%s","%s",,"%s"\n' % (len(parts), refs, value, fp, mpn, notes))


def main():
    sch, nets, root = build()
    path = os.path.join(HERE, PROJECT + ".kicad_sch")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dump(sch) + "\n")
    pro = os.path.join(HERE, PROJECT + ".kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w", encoding="utf-8", newline="\n") as f:
            f.write('{\n  "meta": {\n    "filename": "%s.kicad_pro",\n    "version": 3\n  }\n}\n' % PROJECT)
    write_bom(os.path.join(HERE, "BOM.csv"))
    single = sorted(n for n, m in nets.items() if len(m) < 2)
    print("wrote %s: %d parts, %d nets" % (path, len(design.PARTS), len(nets)))
    if single:
        print("WARNING single-pin nets:", single)


if __name__ == "__main__":
    main()
