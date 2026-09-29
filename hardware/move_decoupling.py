"""Move the MCP23017 decoupling caps C1-C4 next to VDD/VSS (pins 9/10) on an
already-routed board, reconnect them with two short F.Cu tracks, clean up the
old routing and refill the zones.

Run with KiCad's Python, with the board CLOSED in KiCad:
  "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" move_decoupling.py [in.kicad_pcb] [out.kicad_pcb]
"""
import sys

import pcbnew

MM = pcbnew.FromMM
PAIRS = (("U1", "C1"), ("U2", "C2"), ("U3", "C3"), ("U4", "C4"))
GAP = 0.63  # mm between cap pad edge and MCP pad edge


def segs(board):
    return [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]


def vias(board):
    return [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]


def on_segment(p, t):
    """p strictly inside segment t (not at its ends)."""
    a, b = t.GetStart(), t.GetEnd()
    if p == a or p == b:
        return False
    cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
    if abs(cross) > MM(0.001) * max(abs(b.x - a.x), abs(b.y - a.y), 1):
        return False
    return min(a.x, b.x) <= p.x <= max(a.x, b.x) and min(a.y, b.y) <= p.y <= max(a.y, b.y)


def prune_spur(board, point, layer, net, stop_pads):
    """Delete a dead-end chain of tracks starting at `point` (where a removed
    pad used to be), up to the first pad, junction or via."""
    removed = 0
    while True:
        ends = [t for t in segs(board) if t.GetNetCode() == net and t.GetLayer() == layer
                and (t.GetStart() == point or t.GetEnd() == point)]
        if len(ends) != 1:
            return removed
        t = ends[0]
        nxt = t.GetEnd() if t.GetStart() == point else t.GetStart()
        board.Remove(t)
        removed += 1
        point = nxt
        if any(p.HitTest(point) for p in stop_pads):
            return removed
        if any(v.GetPosition() == point for v in vias(board)):
            return removed
        if any(on_segment(point, o) for o in segs(board) if o.GetNetCode() == net and o.GetLayer() == layer):
            return removed


def main(src, dst):
    board = pcbnew.LoadBoard(src)
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    all_pads = [p for f in board.GetFootprints() for p in f.Pads()]
    for u, c in PAIRS:
        upads = {p.GetNumber(): p for p in fps[u].Pads()}
        vdd, vss = upads["9"], upads["10"]
        cap = fps[c]
        cpads = {p.GetNumber(): p for p in cap.Pads()}
        old = {n: (p.GetPosition(), p.GetNetCode(), p.GetLayer()) for n, p in cpads.items()}
        # tracks that ended inside the old cap pads
        attached = {n: [t for t in segs(board) if cpads[n].HitTest(t.GetStart()) or cpads[n].HitTest(t.GetEnd())]
                    for n in cpads}

        # 1) move the cap: vertical, pad1 (+3V3) level with pin 9, pad2 (GND) with pin 10
        cap.SetOrientationDegrees(270)
        pad_half = cpads["1"].GetSize().y // 2 if cpads["1"].GetSize().y > cpads["1"].GetSize().x else cpads["1"].GetSize().x // 2
        cap_half_w = min(cpads["1"].GetSize().x, cpads["1"].GetSize().y) // 2
        x = vdd.GetPosition().x - vdd.GetSize().x // 2 - MM(GAP) - cap_half_w
        y = (vdd.GetPosition().y + vss.GetPosition().y) // 2
        cap.SetPosition(pcbnew.VECTOR2I(x, y))

        # 2) repair routing at the old pad locations
        for n, (pos, net, layer) in old.items():
            ts = attached[n]
            if len(ts) >= 2:  # the pad was a pass-through: join the tracks at the old centre
                for t in ts:
                    if (t.GetStart() - pos).EuclideanNorm() < (t.GetEnd() - pos).EuclideanNorm():
                        t.SetStart(pos)
                    else:
                        t.SetEnd(pos)
            elif len(ts) == 1:  # dead-end spur that only fed the cap
                t = ts[0]
                t.SetStart(pos) if (t.GetStart() - pos).EuclideanNorm() < (t.GetEnd() - pos).EuclideanNorm() else t.SetEnd(pos)
                others = [p for p in all_pads if p.GetParentFootprint() is not cap]
                n_removed = prune_spur(board, pos, layer, net, others)
                print("  %s pad %s: removed %d old spur segment(s)" % (c, n, n_removed))

        # 3) two short tracks to pins 9 and 10
        cpads = {p.GetNumber(): p for p in cap.Pads()}
        for cn, up in (("1", vdd), ("2", vss)):
            t = pcbnew.PCB_TRACK(board)
            t.SetLayer(pcbnew.F_Cu)
            t.SetWidth(MM(0.4))
            t.SetStart(pcbnew.VECTOR2I(cpads[cn].GetPosition().x, up.GetPosition().y))
            t.SetEnd(up.GetPosition())
            t.SetNet(up.GetNet())
            board.Add(t)
        d = (cpads["1"].GetPosition() - vdd.GetPosition()).EuclideanNorm()
        print("%s -> %s: now %.2f mm from VDD pin" % (c, u, pcbnew.ToMM(d)))

    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(dst, board)
    print("saved", dst)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cable_tester.kicad_pcb",
         sys.argv[2] if len(sys.argv) > 2 else "cable_tester.kicad_pcb")
