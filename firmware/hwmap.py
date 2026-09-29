# Physical wiring of the tester PCB: every DUT contact -> (expander index, bit).
# Bits 0-7 = GPA0-7, bits 8-15 = GPB0-7. Must match hardware/design.py
# (hardware/check_design.py cross-checks the two).
#
# Line names:
#   H1..H40  - 40-pin RPi header, pin numbers as on the Raspberry Pi
#   T1.1..T3.6 - TELEM1..3 JST-GH, pin 1..6 (CUAV: 1 VCC, 2 TX, 3 RX, 4 CTS, 5 RTS, 6 GND)

ADDRS = (0x20, 0x21, 0x22, 0x23)  # U1..U4


def _build():
    lines = []
    for n in range(1, 41):  # U1: H1-16, U2: H17-32, U3 GPA: H33-40
        lines.append(("H%d" % n, (n - 1) // 16, (n - 1) % 16))
    for p in range(1, 7):  # U3 GPB0-5
        lines.append(("T1.%d" % p, 2, 7 + p))
    for p in range(1, 7):  # U4 GPA0-5
        lines.append(("T2.%d" % p, 3, p - 1))
    for p in range(1, 7):  # U4 GPB0-5
        lines.append(("T3.%d" % p, 3, 7 + p))
    return lines


LINES = _build()
NAMES = [name for name, _, _ in LINES]
INDEX = {name: i for i, name in enumerate(NAMES)}
CHIPBITS = [(chip, bit) for _, chip, bit in LINES]
