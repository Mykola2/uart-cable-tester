# Cable evaluation and test-session state machine.
# Pure logic (no hardware imports) so it runs on CircuitPython and on a PC.

OK = "OK"
OPEN = "OPEN"
MISWIRE = "MISWIRE"
SHORT = "SHORT"
UNUSED = "UNUSED"
SEVERITY = {UNUSED: 0, OK: 1, OPEN: 2, MISWIRE: 3, SHORT: 4}

PASS = "PASS"
FAIL = "FAIL"
INTERMITTENT = "INTERMITTENT"

IDLE = "IDLE"
TESTING = "TESTING"
DONE = "DONE"

# CUAV TELEM pinout, used to name nets captured by learn()
ROLES = {"1": "VCC", "2": "TX", "3": "RX", "4": "CTS", "5": "RTS", "6": "GND"}


def _roots(n, adj):
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in adj[i]:
            a, b = find(i), find(j)
            if a != b:
                parent[b] = a
    return [find(i) for i in range(n)]


def _members(roots):
    m = {}
    for i, r in enumerate(roots):
        m.setdefault(r, []).append(i)
    return m


def validate(nets, leds, index, any_of={}):
    """Return a list of config errors (empty if fine)."""
    errors = []
    seen = {}
    for name, pins in any_of.items():
        for p in pins:
            if p not in index:
                errors.append("any_of %s: unknown pin %s" % (name, p))
    for net, pins in nets.items():
        fixed = [p for p in pins if p not in any_of]
        if len(pins) < 2 or not fixed:
            errors.append("net %s needs at least 2 entries, one a real pin" % net)
        for p in fixed:
            if p not in index:
                errors.append("net %s: unknown pin or any_of group %s" % (net, p))
            elif p in seen:
                errors.append("pin %s is in both %s and %s" % (p, seen[p], net))
            else:
                seen[p] = net
    for p in leds:
        if p not in index:
            errors.append("leds: unknown pin %s" % p)
    return errors


class Result:
    def __init__(self):
        self.passed = True
        self.connected = False
        self.status = {}  # net name -> OK/OPEN/MISWIRE/SHORT
        self.faults = []  # human-readable fault strings
        self.stuck = []


def evaluate(names, adj, stuck, nets, index, any_of={}):
    """any_of: {"PI_GND": ["H6", "H9", ...]} - pins that are common on the Pi.
    A net entry naming such a group is satisfied by reaching ANY of its pins,
    and wires sharing a group (e.g. several GND wires on one Pi GND pin) are fine."""
    roots = _roots(len(names), adj)
    members = _members(roots)
    owner = {}  # line -> net, fixed pins only
    fixed = {}
    groups_of = {}
    for net, pins in nets.items():
        fixed[net] = [index[p] for p in pins if p not in any_of]
        groups_of[net] = [g for g in pins if g in any_of]
        for i in fixed[net]:
            owner[i] = net
    alias_lines = {g: set(index[p] for p in pins) for g, pins in any_of.items()}
    alias_of = {}  # line -> group name
    for g, lines in alias_lines.items():
        for i in lines:
            alias_of[i] = g

    def fmt(r):
        return "-".join(names[i] for i in members[r])

    # groups touching no expected wire; a bridge between pins that are common
    # on the Pi anyway (e.g. two GND pins) is harmless
    strays = []
    for r, m in members.items():
        if len(m) < 2 or any(i in owner for i in m):
            continue
        if alias_of.get(m[0]) and all(alias_of.get(i) == alias_of[m[0]] for i in m):
            continue
        strays.append(r)

    res = Result()
    res.stuck = list(stuck)
    res.connected = any(len(m) > 1 for m in members.values())
    for net in nets:
        rs = []
        for i in fixed[net]:
            r = roots[i]
            if r not in rs:
                rs.append(r)
        allowed = set(fixed[net])
        for g in groups_of[net]:
            allowed |= alias_lines[g]
            for other in nets:  # other wires to the same common pins may share
                if g in groups_of[other]:
                    allowed.update(fixed[other])
        extra = [i for r in rs for i in members[r] if i not in allowed]
        split = len(rs) > 1
        missing = [g for g in groups_of[net]
                   if not any(i in alias_lines[g] for r in rs for i in members[r])]
        # common pin connected to some unexpected pin -> the wire probably went there
        landed = [r for r in strays for g in missing if any(i in alias_lines[g] for i in members[r])]
        if missing and landed and not extra:
            st = MISWIRE
            rs = rs + landed
        elif extra and (split or missing):
            st = MISWIRE
        elif extra:
            st = SHORT
        elif split or missing:
            st = OPEN
        else:
            st = OK
        res.status[net] = st
        if st == OK:
            continue
        res.passed = False
        if st == SHORT:
            others = []
            for i in extra:
                o = owner.get(i, names[i])
                if o not in others:
                    others.append(o)
            res.faults.append("%s SHORT to %s [%s]" % (net, "+".join(others), fmt(rs[0])))
        else:
            hint = " (not on any %s pin)" % "/".join(missing) if missing else ""
            res.faults.append("%s %s %s%s" % (net, st, " | ".join("[%s]" % fmt(r) for r in rs), hint))
    for r in strays:
        res.passed = False
        res.faults.append("STRAY [%s]" % fmt(r))
    for i in stuck:
        res.passed = False
        res.faults.append("STUCK_LOW %s (tester fault?)" % names[i])
    return res


def led_status(status, nets, leds):
    """Per-LED status: the status of the net that contains that LED's JST pin."""
    pin_net = {}
    for net, pins in nets.items():
        for p in pins:
            pin_net[p] = net
    out = []
    for p in leds:
        net = pin_net.get(p)
        out.append(status.get(net, UNUSED) if net else UNUSED)
    return out, [pin_net.get(p) for p in leds]


def learn(names, adj, any_of={}):
    """Turn the connections of a known-good cable into a nets dict. Wires that
    land only on pins of an any_of group (e.g. Pi GND) are stored as
    [jst_pin, group] so the next cable may use any pin of that group."""
    members = _members(_roots(len(names), adj))
    groups = sorted((m for m in members.values() if len(m) > 1), key=min)
    nets = {}
    k = 0

    def put(name, pins):
        nonlocal k
        if name is None or name in nets:
            k += 1
            name = "NET%d" % k
        nets[name] = pins

    def tname(p):
        port, pin = p[1:].split(".")
        return "T%s_%s" % (port, ROLES.get(pin, "P" + pin))

    for m in groups:
        pins = [names[i] for i in m]
        tpins = [p for p in pins if p.startswith("T")]
        hpins = [p for p in pins if not p.startswith("T")]
        common = [g for g, gp in any_of.items() if hpins and all(p in gp for p in hpins)]
        if tpins and common:
            for p in tpins:
                put(tname(p), [p, common[0]])
        else:
            put(tname(tpins[0]) if len(tpins) == 1 else None, pins)
    return nets


def _worse(a, b):
    return a if SEVERITY.get(a, 0) >= SEVERITY.get(b, 0) else b


class Session:
    """Decides when a plugged-in cable gets its PASS/FAIL verdict and watches
    for intermittent faults afterwards (wiggle test)."""

    def __init__(self, pass_stable_s=0.3, fail_stable_s=3.0, glitch_window_s=2.0, idle_after_s=1.0):
        self.pass_stable_s = pass_stable_s
        self.fail_stable_s = fail_stable_s
        self.glitch_window_s = glitch_window_s
        self.idle_after_s = idle_after_s
        self._reset()
        self._sig = None
        self._since = 0.0

    def _reset(self):
        self.state = IDLE
        self.verdict = None
        self.latched = {}  # net -> worst status seen during an intermittent
        self._glitch = None
        self._glitch_faults = []
        self._empty_since = None

    def _decide(self, res):
        self.state = DONE
        self.verdict = PASS if res.passed else FAIL
        return (self.verdict, list(res.faults))

    def update(self, now, res, retest=False):
        """Feed one scan result. Returns (verdict, faults) when a verdict is
        reached or changes, else None."""
        sig = (res.passed, tuple(res.faults))
        if sig != self._sig:
            self._sig = sig
            self._since = now
        stable = now - self._since

        if not res.connected and not res.stuck:
            if self._empty_since is None:
                self._empty_since = now
            if self.state != IDLE and now - self._empty_since >= self.idle_after_s:
                self._reset()
            return None
        self._empty_since = None

        if retest:
            if self.state == TESTING:
                return self._decide(res)  # operator forces the verdict now
            self._reset()
            self.state = TESTING
            self._since = now
            return None

        if self.state == IDLE:
            self.state = TESTING
            return None

        if self.state == TESTING:
            if res.passed and stable >= self.pass_stable_s:
                return self._decide(res)
            if not res.passed and stable >= self.fail_stable_s:
                return self._decide(res)
            return None

        # DONE: live monitoring for the wiggle test
        if self.verdict in (PASS, INTERMITTENT):
            if not res.passed:
                if self._glitch is None:
                    self._glitch = now
                    self._glitch_status = {}
                    self._glitch_faults = []
                for net, st in res.status.items():
                    if st != OK:
                        self._glitch_status[net] = _worse(st, self._glitch_status.get(net, OK))
                for f in res.faults:
                    if f not in self._glitch_faults:
                        self._glitch_faults.append(f)
            elif self._glitch is not None:
                # Fault came and went quickly -> intermittent. A long fault
                # followed by a pass is a deliberate unplug/replug, not flagged.
                ev = None
                if now - self._glitch <= self.glitch_window_s:
                    self.verdict = INTERMITTENT
                    for net, st in self._glitch_status.items():
                        self.latched[net] = _worse(st, self.latched.get(net, OK))
                    ev = (INTERMITTENT, list(self._glitch_faults))
                self._glitch = None
                return ev
        elif self.verdict == FAIL and res.passed and stable >= self.pass_stable_s:
            self.verdict = PASS
            return (PASS, ["after reseat"])
        return None
