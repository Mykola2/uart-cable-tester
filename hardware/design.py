"""Single source of truth for the cable-tester PCB.

Every component: KiCad symbol, footprint, pin -> net map, schematic position,
starter PCB position. gen_schematic.py and gen_pcb.py both read this file.
Pin keys may be a pin number ("21") or a pin name ("GPIO4"); pins not listed
get a no-connect flag.
"""

# Test lines, in the same order as firmware/hwmap.py LINES.
# (connector-side net, expander ref, expander pin name)
LINES = []
for _n in range(1, 41):
    _idx = _n - 1
    _chip, _bit = _idx // 16, _idx % 16
    LINES.append(("H%d" % _n, "U%d" % (_chip + 1), ("GPA%d" if _bit < 8 else "GPB%d") % (_bit % 8)))
for _k, (_u, _port) in enumerate((("U3", "GPB"), ("U4", "GPA"), ("U4", "GPB")), start=1):
    for _p in range(1, 7):
        LINES.append(("T%d.%d" % (_k, _p), _u, "%s%d" % (_port, _p - 1)))

SPARE_IO = {"U3": ["GPB6", "GPB7"], "U4": ["GPA6", "GPA7", "GPB6", "GPB7"]}
MCP_ADDR_PINS = {  # A2 A1 A0 -> 0x20..0x23
    "U1": ("GND", "GND", "GND"),
    "U2": ("GND", "GND", "+3V3"),
    "U3": ("GND", "+3V3", "GND"),
    "U4": ("GND", "+3V3", "+3V3"),
}


class Part:
    def __init__(self, ref, lib, sym, value, footprint, pins, sch, pcb=None, mpn="", note=""):
        self.ref = ref
        self.lib = lib
        self.sym = sym
        self.value = value
        self.footprint = footprint
        self.pins = pins
        self.sch = sch  # (x, y) on the schematic sheet, mm
        self.pcb = pcb  # (x, y, rotation_deg, "F"/"B") or None
        self.mpn = mpn
        self.note = note


PARTS = []


def add(*a, **kw):
    PARTS.append(Part(*a, **kw))


# ---- MCU module ---------------------------------------------------------------
add("A1", "MCU_Module", "RaspberryPi_Pico", "Pico / WeAct RP2040 (USB-C)",
    "Module:RaspberryPi_Pico_SMD_HandSolder",
    {"GPIO4": "I2C_SDA", "GPIO5": "I2C_SCL", "GPIO14": "BUZZER", "GPIO15": "BUTTON",
     "GPIO16": "LED_DATA_3V3", "VBUS": "+5V", "3V3": "+3V3", "GND": "GND"},
    sch=(55.88, 88.9), pcb=(117.0, 28.5, 0, "F"),
    mpn="Raspberry Pi Pico (SC0915) or WeAct Studio RP2040",
    note="USB-C variant recommended; castellated, solder directly or on 2x 1x20 sockets")

# ---- I/O expanders --------------------------------------------------------------
for _i, _u in enumerate(("U1", "U2", "U3", "U4")):
    _pins = {"VDD": "+3V3", "VSS": "GND", "SCK": "I2C_SCL", "SDA": "I2C_SDA", "~{RESET}": "+3V3"}
    _pins.update(dict(zip(("A2", "A1", "A0"), MCP_ADDR_PINS[_u])))
    for _net, _ref, _pin in LINES:
        if _ref == _u:
            _pins[_pin] = _net + "_IO"
    add(_u, "Interface_Expansion", "MCP23017_SO", "MCP23017-E/SO",
        "Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm", _pins,
        sch=(162.56, 60.96 + 76.2 * _i), pcb=(16.0 + 24.0 * _i, 40.0, 0, "F"),
        mpn="MCP23017-E/SO", note="I2C addr 0x%02X" % (0x20 + _i))
    add("C%d" % (_i + 1), "Device", "C", "100n", "Capacitor_SMD:C_0603_1608Metric",
        {"1": "+3V3", "2": "GND"}, sch=(215.9 + 12.7 * _i, 25.4),
        pcb=(16.0 + 24.0 * _i + 8.5, 31.0, 90, "F"), mpn="0603 100nF X7R 16V")

# ---- 220R series protection on every test line --------------------------------------
_rn = 0
for _base in range(0, len(LINES), 4):
    _rn += 1
    _pins = {}
    for _k, (_net, _ref, _pin) in enumerate(LINES[_base:_base + 4]):
        _pins["R%d.1" % (_k + 1)] = _net           # connector side
        _pins["R%d.2" % (_k + 1)] = _net + "_IO"   # expander side
    _col, _row = (_rn - 1) % 5, (_rn - 1) // 5
    if _rn <= 10:  # header lines: row under the 40-pin header
        _pcb = (9.0 + 5.3 * (_rn - 1), 19.0, 0, "F")
    else:          # JST lines: row above the JSTs
        _pcb = ((17.0, 30.0, 48.0, 78.0, 91.0)[_rn - 11], 58.0, 0, "F")
    add("RN%d" % _rn, "Device", "R_Pack04", "4x220", "Resistor_SMD:R_Array_Convex_4x0603",
        _pins, sch=(254.0 + 33.02 * _col, 60.96 + 50.8 * _row), pcb=_pcb,
        mpn="YC164-JR-07220RL (4x220R 0603 convex)")

# ---- DUT connectors -----------------------------------------------------------------
add("J1", "Connector_Generic", "Conn_02x20_Odd_Even", "RPi 40-pin (DUT)",
    "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical",
    {str(n): "H%d" % n for n in range(1, 41)}, sch=(452.12, 101.6), pcb=(10.0, 8.5, 90, "F"),
    mpn="2x20 2.54mm male pin header", note="ALL pins are isolated test lines - never tie to power/GND")
for _k in range(1, 4):
    add("J%d" % (_k + 1), "Connector_Generic_MountingPin", "Conn_01x06_MountingPin", "TELEM%d (DUT)" % _k,
        "Connector_JST:JST_GH_SM06B-GHS-TB_1x06-1MP_P1.25mm_Horizontal",
        {str(p): "T%d.%d" % (_k, p) for p in range(1, 7)},
        sch=(452.12, 177.8 + 38.1 * (_k - 1)), pcb=(20.0 + 32.0 * (_k - 1), 86.8, 0, "F"),
        mpn="JST SM06B-GHS-TB(LF)(SN)", note="~50 mating cycles: consumable, keep spares")

# ---- LED data level shifter ------------------------------------------------------------
add("U5", "74xGxx", "74AHCT1G125", "74AHCT1G125", "Package_TO_SOT_SMD:SOT-23-5",
    {"1": "GND", "2": "LED_DATA_3V3", "4": "LED_DATA_5V", "5": "+5V", "3": "GND"},  # 1=~OE 2=A 4=Y,
    sch=(55.88, 172.72), pcb=(101.0, 60.0, 0, "F"), mpn="SN74AHCT1G125DBVR")
add("C5", "Device", "C", "100n", "Capacitor_SMD:C_0603_1608Metric", {"1": "+5V", "2": "GND"},
    sch=(266.7, 25.4), pcb=(101.0, 64.0, 0, "F"), mpn="0603 100nF X7R 16V")
add("R1", "Device", "R", "330", "Resistor_SMD:R_0603_1608Metric", {"1": "LED_DATA_5V", "2": "LED_DIN"},
    sch=(88.9, 172.72), pcb=(105.0, 60.0, 90, "F"), mpn="0603 330R")

# ---- I2C pull-ups --------------------------------------------------------------------
add("R2", "Device", "R", "4k7", "Resistor_SMD:R_0603_1608Metric", {"1": "+3V3", "2": "I2C_SDA"},
    sch=(106.68, 55.88), pcb=(101.0, 36.0, 90, "F"), mpn="0603 4.7k")
add("R3", "Device", "R", "4k7", "Resistor_SMD:R_0603_1608Metric", {"1": "+3V3", "2": "I2C_SCL"},
    sch=(119.38, 55.88), pcb=(103.0, 36.0, 90, "F"), mpn="0603 4.7k")

# ---- Buzzer (5V active, low-side NPN) ---------------------------------------------------
add("R4", "Device", "R", "1k", "Resistor_SMD:R_0603_1608Metric", {"1": "BUZZER", "2": "BUZ_B"},
    sch=(55.88, 213.36), pcb=(108.5, 66.0, 0, "F"), mpn="0603 1k")
add("R5", "Device", "R", "10k", "Resistor_SMD:R_0603_1608Metric", {"1": "BUZ_B", "2": "GND"},
    sch=(71.12, 213.36), pcb=(108.5, 68.5, 0, "F"), mpn="0603 10k")
add("Q1", "Transistor_BJT", "MMBT3904", "MMBT3904", "Package_TO_SOT_SMD:SOT-23",
    {"B": "BUZ_B", "E": "GND", "C": "BUZ_N"}, sch=(88.9, 213.36), pcb=(112.5, 67.0, 0, "F"), mpn="MMBT3904")
add("BZ1", "Device", "Buzzer", "5V active buzzer", "Buzzer_Beeper:Buzzer_12x9.5RM7.6",
    {"1": "+5V", "2": "BUZ_N"}, sch=(119.38, 210.82), pcb=(121.0, 74.0, 0, "F"),
    mpn="TMB12A05 (12mm 5V active, 7.6mm pitch)")
add("D11", "Device", "D", "1N4148W", "Diode_SMD:D_SOD-123", {"K": "+5V", "A": "BUZ_N"},
    sch=(134.62, 210.82), pcb=(112.5, 71.0, 0, "F"), mpn="1N4148W")

# ---- Button, OLED header -----------------------------------------------------------------
add("SW1", "Switch", "SW_Push", "START / LEARN", "Button_Switch_THT:SW_PUSH_6mm_H5mm",
    {"1": "BUTTON", "2": "GND"}, sch=(55.88, 243.84), pcb=(99.0, 75.0, 0, "F"),
    mpn="6x6mm THT tactile switch", note="short press: retest / force verdict; hold 3s: learn")
add("J5", "Connector_Generic", "Conn_01x04", "OLED (opt.)",
    "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    {"1": "GND", "2": "+3V3", "3": "I2C_SCL", "4": "I2C_SDA"}, sch=(88.9, 243.84),
    pcb=(103.0, 44.0, 0, "F"), mpn="1x4 2.54mm header (DNP)", note="SSD1306 128x64 I2C, GND-VCC-SCL-SDA")

# ---- Bulk caps -------------------------------------------------------------------------
add("C6", "Device", "C", "10u", "Capacitor_SMD:C_0805_2012Metric", {"1": "+3V3", "2": "GND"},
    sch=(279.4, 25.4), pcb=(101.0, 40.0, 0, "F"), mpn="0805 10uF X5R 16V")
add("C7", "Device", "C", "10u", "Capacitor_SMD:C_0805_2012Metric", {"1": "+5V", "2": "GND"},
    sch=(292.1, 25.4), pcb=(101.0, 56.0, 0, "F"), mpn="0805 10uF X5R 16V")

# ---- WS2812B chain: D1-D9 per wire (3 per TELEM port: TX RX GND), D10 status ---------------------
for _i in range(10):
    _din = "LED_DIN" if _i == 0 else "LED_D%d" % (_i + 1)
    _dout = "LED_D%d" % (_i + 2) if _i < 9 else None
    _pins = {"DIN": _din, "VDD": "+5V", "VSS": "GND"}
    if _dout:
        _pins["DOUT"] = _dout
    if _i < 9:
        _port, _w = _i // 3, _i % 3
        _pcb = (13.0 + 32.0 * _port + 7.0 * _w, 70.0, 0, "F")
        _note = "TELEM%d %s" % (_port + 1, ("TX", "RX", "GND")[_w])
    else:
        _pcb = (112.0, 84.0, 0, "F")
        _note = "PASS/FAIL status"
    add("D%d" % (_i + 1), "LED", "WS2812B", "WS2812B", "LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm",
        _pins, sch=(38.1 + 43.18 * _i, 365.76), pcb=_pcb, mpn="WS2812B-5050", note=_note)
    add("C%d" % (8 + _i), "Device", "C", "100n", "Capacitor_SMD:C_0603_1608Metric",
        {"1": "+5V", "2": "GND"}, sch=(38.1 + 43.18 * _i, 393.7),
        pcb=(_pcb[0], _pcb[1] - 4.5, 0, "F"), mpn="0603 100nF X7R 16V")

# ---- Mounting holes -----------------------------------------------------------------------
for _i, (_x, _y) in enumerate(((3.5, 3.5), (97.0, 3.5), (3.5, 86.5), (131.5, 86.5))):
    add("MH%d" % (_i + 1), "Mechanical", "MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3",
        {}, sch=(495.3 + 10.16 * _i, 393.7), pcb=(_x, _y, 0, "F"), mpn="(none)")

BOARD_W = 135.0
BOARD_H = 90.0
