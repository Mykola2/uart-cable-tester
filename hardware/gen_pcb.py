"""Generate a starter cable_tester.kicad_pcb: outline, all footprints placed
(positions from design.py), pads assigned to the nets of the exported netlist,
silkscreen labels and GND pours. Routing is left to you (or Freerouting).

Run with KiCad's Python (it has pcbnew):
  "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" gen_pcb.py

Needs cable_tester.net (kicad-cli sch export netlist ...) to be current.
"""
import os

import pcbnew

import design
from gen_schematic import KICAD, PROJECT, find, first, parse, uid

HERE = os.path.dirname(os.path.abspath(__file__))
FPDIR = os.path.join(KICAD, "share", "kicad", "footprints")
MM = pcbnew.FromMM


def pt(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def load_netlist():
    tree = parse(open(os.path.join(HERE, PROJECT + ".net"), encoding="utf-8").read())
    pinnet = {}
    for net in find(first(tree, "nets"), "net"):
        name = first(net, "name")[1]
        for node in find(net, "node"):
            pinnet[(first(node, "ref")[1], first(node, "pin")[1])] = name
    return pinnet


def text(board, s, x, y, size=1.0, layer=pcbnew.F_SilkS, bold=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(pt(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(size * (0.2 if bold else 0.15)))
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    board.Add(t)


def main():
    path = os.path.join(HERE, PROJECT + ".kicad_pcb")
    board = pcbnew.NewBoard(path)
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    ds.m_TrackMinWidth = MM(0.15)
    ds.m_MinClearance = MM(0.15)
    ds.m_ViasMinSize = MM(0.5)
    ds.m_MinThroughDrill = MM(0.3)
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetTrackWidth(MM(0.25))
    nc.SetClearance(MM(0.2))
    nc.SetViaDiameter(MM(0.6))
    nc.SetViaDrill(MM(0.3))

    pinnet = load_netlist()
    nets = {}
    for name in sorted(set(pinnet.values())):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni

    W, H = design.BOARD_W, design.BOARD_H
    edge = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_RECT)
    edge.SetStart(pt(0, 0))
    edge.SetEnd(pt(W, H))
    edge.SetLayer(pcbnew.Edge_Cuts)
    edge.SetWidth(MM(0.1))
    board.Add(edge)

    for part in design.PARTS:
        lib, name = part.footprint.split(":")
        fp = pcbnew.FootprintLoad(os.path.join(FPDIR, lib + ".pretty"), name)
        if fp is None:
            raise RuntimeError("footprint not found: " + part.footprint)
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(part.ref)
        fp.SetValue(part.value)
        fp.SetPath(pcbnew.KIID_PATH("/" + uid("sym", part.ref, 1)))
        board.Add(fp)
        x, y, rot, side = part.pcb
        fp.SetPosition(pt(x, y))
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            net = pinnet.get((part.ref, pad.GetNumber()))
            if net:
                pad.SetNet(nets[net])
        # small refs keep the dense resistor rows readable
        if part.ref.startswith(("RN", "C", "R")):
            fp.Reference().SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8)))
            fp.Reference().SetTextThickness(MM(0.12))

    # ---- silkscreen ---------------------------------------------------------------
    text(board, "RPi <-> CUAV X7 TELEM CABLE TESTER  rev A", 52, 53.5, 1.4, bold=True)
    text(board, "1", 8.4, 10.8, 1.0, bold=True)
    text(board, "RPi 40-PIN  (plug cable exactly as on the Pi, pin 1 left)", 34, 1.5, 0.9)
    for k in range(3):
        cx = 20 + 32 * k
        for w, lab in enumerate(("TX", "RX", "GND")):
            text(board, lab, cx - 7 + 7 * w, 74.3, 1.0, bold=True)
        text(board, "TELEM%d" % (k + 1), cx, 78.3, 1.4, bold=True)
    text(board, "STATUS", 112, 88.3, 1.0, bold=True)
    text(board, "START", 102.3, 83.2, 1.0, bold=True)
    text(board, "hold 3s: LEARN", 102.3, 84.8, 0.8)
    text(board, "USB", 117, 3.0, 1.0, bold=True)
    text(board, "OLED", 103, 53.3, 0.8)
    text(board, "green=OK red=OPEN orange=MISWIRE magenta=SHORT", 60, 81.2, 0.8)
    text(board, "Every 40-pin header contact is an isolated test line", 67, 45, 1.0, layer=pcbnew.B_SilkS)

    # ---- GND pours, both layers --------------------------------------------------------
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(nets["/GND"])
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        ol = z.Outline()
        ol.NewOutline()
        for (x, y) in ((0.5, 0.5), (W - 0.5, 0.5), (W - 0.5, H - 0.5), (0.5, H - 0.5)):
            ol.Append(MM(x), MM(y))
        board.Add(z)
    # Pours are left unfilled: press B in KiCad (scripted fill mishandles NPTH holes).

    pcbnew.SaveBoard(path, board)
    print("wrote", path, "-", len(design.PARTS), "footprints,", len(nets), "nets")


if __name__ == "__main__":
    main()
