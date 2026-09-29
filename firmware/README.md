# Cable tester firmware (CircuitPython)

## Install
1. Hold BOOTSEL, plug in USB, and drop the CircuitPython UF2 for **Raspberry Pi Pico** onto the RPI-RP2 drive (circuitpython.org). The Pico build also runs on the WeAct RP2040.
2. Copy `code.py`, `hwmap.py`, `mcp_bus.py`, `tester.py` and `wiring.json` to the `CIRCUITPY` drive. No libraries are needed.
3. Open the serial console (Mu, Thonny or PuTTY at any baud rate). You should see `# cable tester ready` followed by a CSV header.

## Use
- **Plug the cable in.**
  - A good cable passes about 0.3 s after it's fully connected: all wire LEDs turn green, the status LED turns green, and it gives one short beep.
  - A fault that stays for 3 s gives FAIL: status LED red and a long beep. The wire LEDs show the fault type:

| Wire LED | Meaning |
|---|---|
| green | OK |
| red | OPEN |
| orange | MISWIRE (swapped, wrong cavity or wrong header pin) |
| magenta | SHORT |

- **Wiggle test.** After a PASS, flex the cable near each crimp. A fault that appears and clears within 2 s is logged as INTERMITTENT: the status LED blinks red and the affected wire LED blinks.
- **Unplug.** The tester returns to idle (status LED dim blue) after 1 s with nothing connected.
- **Short press:** during a test, forces the verdict now; after a verdict, starts a retest.
- **Hold 3 s with a known-good cable plugged in:** LEARN.
  - The tester stores the cable's wiring in NVM, prints it as JSON (ready to paste into `wiring.json`), and beeps once per net (9 beeps expected).
- **Hold 3 s with nothing plugged in:** clears the learned map and goes back to `wiring.json`.
- Editing `wiring.json` also overrides an old learned map.

The serial log is CSV (`time_s,count,result,faults`), e.g. `412.3,57,FAIL,T2_RX OPEN [T2.3] | [H7]`.

## Pinout changes
Edit `wiring.json` on the CIRCUITPY drive, or use LEARN.
- Pins are named `H1`–`H40` (RPi header numbering) and `T1.1`–`T3.6` (TELEM connector.pin).
- `leds` says which JST pin each wire LED reports.
- **The default map is a placeholder.** It is TELEM1 = UART0 (pins 8/10), TELEM2 = UART3 (7/29) and TELEM3 = UART5 (32/33). Confirm it against your cable drawing.
- **Ground wires can go to any Pi GND pin.** A net entry such as `"T1_GND": ["T1.6", "PI_GND"]` passes if the wire reaches any pin listed under `any_of.PI_GND` (6, 9, 14, 20, 25, 30, 34 or 39).
  - Several GND wires sharing one GND pin is fine. So is a bridge between two GND pins, because they are common on the Pi.
  - A GND wire on a non-GND pin, or a GND pin bridged to a signal pin, still fails.
  - `PI_5V` (2, 4) and `PI_3V3` (1, 17) groups are defined the same way, ready for future cables.
- Signal wires (TX/RX) are still checked against their exact header pin.
- LEARN stores the ground wires of a known-good cable as `PI_GND` too, not as the specific pin that cable happened to use.

## PC tests
```bash
python pc_tests/test_tester.py
```
These simulate the four MCP23017s at register level together with a set of cables (good, open, TX/RX swap, short, wrong cavity, stray bridge, stuck line, learn) and the PASS/FAIL/INTERMITTENT state machine.
