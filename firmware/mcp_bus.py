# Minimal MCP23017 driver + "walking one" connectivity scan.
# Works with CircuitPython busio.I2C (already locked) or any object with
# writeto(addr, buf) / writeto_then_readfrom(addr, out, in) / scan().

IODIRA = 0x00
IOCON = 0x0A
GPPUA = 0x0C
GPIOA = 0x12
OLATA = 0x14


class Expanders:
    def __init__(self, i2c, addrs):
        self.i2c = i2c
        self.addrs = addrs
        self._reg = bytearray(1)
        self._rd = bytearray(2)
        self._w3 = bytearray(3)

    def missing(self):
        found = self.i2c.scan()
        return [a for a in self.addrs if a not in found]

    def init(self):
        for a in self.addrs:
            self.i2c.writeto(a, bytes((IOCON, 0x00)))  # BANK=0, sequential A/B pairs
            self._write16(a, OLATA, 0x0000)  # output latch low: a driven pin pulls low
            self._write16(a, GPPUA, 0xFFFF)  # ~100k pull-ups on everything
            self._write16(a, IODIRA, 0xFFFF)  # all inputs

    def _write16(self, addr, reg, value):
        b = self._w3
        b[0] = reg
        b[1] = value & 0xFF
        b[2] = (value >> 8) & 0xFF
        self.i2c.writeto(addr, b)

    def _read16(self, addr, reg):
        self._reg[0] = reg
        self.i2c.writeto_then_readfrom(addr, self._reg, self._rd)
        return self._rd[0] | (self._rd[1] << 8)

    def read_all(self):
        return [self._read16(a, GPIOA) for a in self.addrs]

    def scan(self, chipbits):
        """Drive each line low in turn and see which others follow.

        Returns (adj, stuck): adj[i] = list of line indices connected to line i,
        stuck = line indices that read low with nothing driven (tester fault).
        """
        n = len(chipbits)
        base = self.read_all()
        stuck = [i for i, (c, b) in enumerate(chipbits) if not (base[c] >> b) & 1]
        stuck_set = set(stuck)
        adj = [[] for _ in range(n)]
        for i, (c, b) in enumerate(chipbits):
            if i in stuck_set:
                continue
            addr = self.addrs[c]
            self._write16(addr, IODIRA, 0xFFFF ^ (1 << b))
            reads = self.read_all()
            self._write16(addr, IODIRA, 0xFFFF)
            row = adj[i]
            for j, (cj, bj) in enumerate(chipbits):
                if j != i and not (reads[cj] >> bj) & 1 and j not in stuck_set:
                    row.append(j)
        return adj, stuck
