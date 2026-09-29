"""Build JLCPCB order files from cable_tester.kicad_pcb into fab/:
  gerbers/ + cable_tester_gerbers.zip  (PCB order)
  BOM_JLC.csv, CPL_JLC.csv             (SMT assembly order, top side)

Run (board must be saved; can be open in KiCad):
  python make_jlc.py
"""
import csv
import os
import shutil
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe")
PCB = os.path.join(HERE, "cable_tester.kicad_pcb")
FAB = os.path.join(HERE, "fab")
GERB = os.path.join(FAB, "gerbers")

# Hand-soldered / not assembled by JLC: module, through-hole parts, optional header.
NOT_ASSEMBLED = ("A1", "J1", "J5", "SW1", "BZ1", "MH1", "MH2", "MH3", "MH4")

# (value, footprint name) -> (LCSC#, description). Verified on lcsc.com.
LCSC = {
    ("100n", "C_0603_1608Metric"): ("C14663", "100nF 50V X7R 0603 (Yageo CC0603KRX7R9BB104)"),
    ("10u", "C_0805_2012Metric"): ("C15850", "10uF 25V X5R 0805 (Samsung CL21A106KAYNNNE)"),
    ("330", "R_0603_1608Metric"): ("C23138", "330R 1% 0603 (0603WAF3300T5E)"),
    ("4k7", "R_0603_1608Metric"): ("C23162", "4.7k 1% 0603 (0603WAF4701T5E)"),
    ("1k", "R_0603_1608Metric"): ("C21190", "1k 1% 0603 (0603WAF1001T5E)"),
    ("10k", "R_0603_1608Metric"): ("C25804", "10k 1% 0603 (0603WAF1002T5E)"),
    ("4x220", "R_Array_Convex_4x0603"): ("C29719", "4x220R 0603x4 array (UniOhm 4D03WGJ0221T5E)"),
    ("MCP23017-E/SO", "SOIC-28W_7.5x17.9mm_P1.27mm"): ("C47023", "MCP23017-E/SO"),
    ("74AHCT1G125", "SOT-23-5"): ("C7484", "SN74AHCT1G125DBVR"),
    ("MMBT3904", "SOT-23"): ("C20526", "MMBT3904 (JSCJ)"),
    ("1N4148W", "D_SOD-123"): ("C81598", "1N4148W SOD-123"),
    ("WS2812B", "LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm"): ("C114586", "WS2812B-B/W (Worldsemi)"),
}
JST = ("C133065", "JST SM06B-GHS-TB(LF)(SN)")


def run(*args):
    subprocess.run([CLI, *args], check=True, stdout=subprocess.DEVNULL)


def gerbers():
    shutil.rmtree(GERB, ignore_errors=True)
    os.makedirs(GERB)
    run("pcb", "export", "gerbers", "--output", GERB + os.sep,
        "--layers", "F.Cu,B.Cu,F.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts",
        "--subtract-soldermask", "--no-x2", "--no-netlist", PCB)
    run("pcb", "export", "drill", "--output", GERB + os.sep, "--format", "excellon",
        "--drill-origin", "absolute", "--excellon-units", "mm", "--excellon-zeros-format", "decimal",
        "--excellon-oval-format", "alternate", "--excellon-separate-th", "--generate-map",
        "--map-format", "gerberx2", PCB)
    z = os.path.join(FAB, "cable_tester_gerbers.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(GERB)):
            zf.write(os.path.join(GERB, f), f)
    return z, sorted(os.listdir(GERB))


def assembly():
    pos = os.path.join(FAB, "_pos.csv")
    run("pcb", "export", "pos", "--output", pos, "--format", "csv", "--units", "mm",
        "--side", "front", PCB)
    rows = list(csv.DictReader(open(pos, encoding="utf-8")))
    os.remove(pos)
    groups, cpl, missing = {}, [], []
    for r in rows:
        ref = r["Ref"]
        if ref in NOT_ASSEMBLED:
            continue
        fp = r["Package"]
        if fp.startswith("JST_GH_SM06B"):
            lcsc = JST
            r["Val"] = "SM06B-GHS-TB"
        else:
            lcsc = LCSC.get((r["Val"], fp))
        if not lcsc:
            missing.append((ref, r["Val"], fp))
            continue
        groups.setdefault((r["Val"], fp, lcsc[0], lcsc[1]), []).append(ref)
        cpl.append([ref, "%.3fmm" % float(r["PosX"]), "%.3fmm" % float(r["PosY"]),
                    "Top", "%.1f" % (float(r["Rot"]) % 360)])
    with open(os.path.join(FAB, "BOM_JLC.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Description"])
        for (val, fp, lc, desc), refs in sorted(groups.items(), key=lambda kv: kv[1][0]):
            w.writerow([val, ",".join(refs), fp, lc, desc])
    with open(os.path.join(FAB, "CPL_JLC.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(sorted(cpl))
    return groups, len(cpl), missing


if __name__ == "__main__":
    os.makedirs(FAB, exist_ok=True)
    z, files = gerbers()
    print("gerbers:", ", ".join(files))
    print("zip:", z)
    groups, n, missing = assembly()
    print("BOM lines: %d, placements: %d" % (len(groups), n))
    for m in missing:
        print("NO LCSC PART for", m)
