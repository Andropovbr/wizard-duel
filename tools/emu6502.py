"""Deterministic 6502 emulator for the Wizard Duel ROM.

Covers the opcodes used by src/main.asm so the assembled ROM can be executed
deterministically without a display.  TIA/RIOT peripherals are modeled just
enough to let the frame loop advance and to validate game state and timing:

  * TIA writes ($00-$3F) and INPT0-5 reads are tracked.
  * WSYNC stalls the CPU until the next 76-cycle scanline boundary.
  * TIM64T starts a 64-cycle/tick countdown; INTIM returns the remaining
    ticks (0 when expired), so the WaitVBlank / overscan spin loops behave
    like the real timer.
  * SWCHA ($0280) returns $FF (nothing pressed).
  * INPT4/INPT5 reads are exposed via `cpu.inpt[4]` / `cpu.inpt[5]` (bit 7
    clear = button pressed); tests set them to simulate the fire buttons.
  * TIA collision latches are modeled at the REGISTER level: `cpu.cxm0p`
    / `cpu.cxm1p` hold the CXM0P/CXM1P read values, they persist until a
    CXCLR write clears them, and reads have no side effects - exactly the
    real latch contract.  Tests inject latch bits to represent an overlap
    rendered by the visible kernel (the emulator does not simulate pixel
    geometry; see docs/en/timing.md for the Stella-based pixel validation).
  * Game RAM is RIOT $80-$FF plus a separate $0100-$01FF stack page.

This is a functional model with realistic 6502 branch timing: a branch
costs 2 cycles when not taken, 3 when taken, and 4 when a taken branch
crosses a page boundary; indexed loads (LDA abs,Y) add a cycle on a page
crossing.  Without this the WaitVBlank INTIM spin is modelled too cheaply:
the real (taken) branch cost was what pushed the VBLANK work past the
TIM64T expiry and made frames slip to 263+ scanlines (the whole-screen
shake, fixed in Round 6).  The model validates behavior (missile firing,
movement, frame scanline count) and the timing it is exercised for.
"""

from pathlib import Path

ROM_ORIGIN = 0xF000
VECTOR_RESET = 0xFFFC

# Base cycle counts for the opcodes used by src/main.asm (6502).  Branches
# are 2 here; execute() adds +1 when taken and +1 more when the taken branch
# crosses a page boundary.  Indexed absolute loads (LDA abs,Y) are 4 here;
# execute() adds +1 when the effective address crosses a page boundary.
CYC = {
    0x18: 2, 0x38: 2, 0x78: 2, 0xD8: 2, 0xEA: 2, 0x48: 3, 0x68: 4, 0xAA: 2,
    0xA8: 2, 0x8A: 2, 0x98: 2, 0x9A: 2, 0xE8: 2, 0xC8: 2, 0xCA: 2, 0x88: 2,
    0x0A: 2, 0x60: 6, 0x4C: 3, 0x20: 6,
    0xA9: 2, 0xA0: 2, 0xA2: 2, 0x69: 2, 0xE9: 2, 0x29: 2, 0x49: 2, 0x05: 2, 0x09: 2, 0xC9: 2,
    0xE0: 2,
    0xA5: 3, 0xAD: 4, 0xB9: 4, 0xB5: 4, 0xA4: 3, 0xAC: 4, 0xA6: 3, 0xAE: 4,
    0xB6: 4,
    0x85: 3, 0x8D: 4, 0x99: 5, 0x95: 4, 0x84: 3, 0x86: 3,
    0xC6: 5, 0xE6: 5, 0xC5: 3, 0xE5: 3, 0x65: 3, 0xE4: 3, 0x24: 3,
    0xD0: 2, 0xF0: 2, 0xB0: 2, 0x90: 2, 0x30: 2,
}


class Cpu:
    def __init__(self, rom, ram_size=128):
        self.rom = rom
        self.ram = bytearray(ram_size)          # RIOT RAM $80-$FF
        self.stack = bytearray(256)             # stack page $0100-$01FF
        self.tia = [0] * 64                     # TIA write registers $00-$3F
        self.inpt = [0xFF] * 6                  # INPT0-5 reads (buttons released)
        self.cxm0p = 0                          # CXM0P read latch (D7 M0-P1, D6 M0-P0)
        self.cxm1p = 0                          # CXM1P read latch (D7 M1-P0, D6 M1-P1)
        self.riot = [0] * 32                    # $0280-$029F
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 0xFD
        self.pc = 0
        self.n = self.v = self.d = self.i = self.z = self.c = 0
        self.cycles = 0
        self.steps = 0
        self.timer = 0          # RIOT timer: remaining cycles until INTIM = 0

    # ---- memory ----
    def read(self, addr):
        addr &= 0xFFFF
        if ROM_ORIGIN <= addr <= 0xFFFF:
            return self.rom[addr - ROM_ORIGIN]
        if 0x80 <= addr <= 0xFF:
            return self.ram[addr - 0x80]
        if 0x100 <= addr <= 0x1FF:
            return self.stack[addr - 0x100]
        if addr < 0x40:
            if 0x38 <= addr <= 0x3D:    # INPT0-5 reads
                return self.inpt[addr - 0x38]
            if addr == 0x00:            # CXM0P read (M0 vs P0/P1 latches)
                return self.cxm0p
            if addr == 0x01:            # CXM1P read (M1 vs P0/P1 latches)
                return self.cxm1p
            return self.tia[addr]
        if addr < 0x80:
            m = addr & 0x3F
            if 0x38 <= m <= 0x3D:       # mirrored INPT0-5 reads
                return self.inpt[m - 0x38]
            if m == 0x00:               # mirrored CXM0P read
                return self.cxm0p
            if m == 0x01:               # mirrored CXM1P read
                return self.cxm1p
            return self.tia[m]
        if 0x280 <= addr <= 0x29F:
            if addr == 0x284:                   # INTIM
                return self.timer // 64
            return self.riot[addr - 0x280]
        raise AssertionError(f"read from ${addr:04X}")

    def write(self, addr, value):
        value &= 0xFF
        addr &= 0xFFFF
        if ROM_ORIGIN <= addr <= 0xFFFF:
            raise AssertionError(f"write to ROM ${addr:04X}")
        if 0x80 <= addr <= 0xFF:
            self.ram[addr - 0x80] = value
            return
        if 0x100 <= addr <= 0x1FF:
            self.stack[addr - 0x100] = value
            return
        if addr < 0x40:
            # All $00-$3F TIA writes go to write registers; the read-only
            # INPT latches live at $38-$3D and are ignored for writes.
            self.tia[addr] = value
            if addr == 0x02:                    # WSYNC: hold to next scanline
                rem = self.cycles % 76
                self.cycles += 76 - rem if rem else 76
            elif addr == 0x2C:                  # CXCLR: clear collision latches
                self.cxm0p = 0
                self.cxm1p = 0
            return
        if addr < 0x80:
            m = addr & 0x3F
            if 0x38 <= m <= 0x3D:
                return                          # INPT reads are read-only
            self.tia[m] = value
            if m == 0x2C:                       # CXCLR (mirrored): clear latches
                self.cxm0p = 0
                self.cxm1p = 0
            return
        if 0x280 <= addr <= 0x29F:
            if addr == 0x296:                   # TIM64T: 64 cycles/tick
                self.timer = value * 64
                self.riot[addr - 0x280] = value
                return
            self.riot[addr - 0x280] = value
            return
        raise AssertionError(f"write to ${addr:04X}")

    def push(self, v):
        self.write(0x100 + self.sp, v)
        self.sp = (self.sp - 1) & 0xFF

    def pop(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.read(0x100 + self.sp)

    # ---- flags ----
    def set_nz(self, v):
        self.n = 1 if (v & 0x80) else 0
        self.z = 1 if (v & 0xFF) == 0 else 0

    # ---- addressing ----
    def fetch(self):
        v = self.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def imm(self):
        return self.fetch()

    def zp_addr(self):
        return self.fetch()

    def zpx_addr(self):
        return (self.fetch() + self.x) & 0xFF

    def abs_addr(self):
        lo = self.fetch()
        hi = self.fetch()
        return lo | (hi << 8)

    def absy_addr(self):
        return (self.abs_addr() + self.y) & 0xFFFF

    # ---- run ----
    def step(self):
        start = self.cycles
        op = self.fetch()
        self.steps += 1
        if self.steps > 2_000_000:
            raise RuntimeError("step limit exceeded (possible hang)")
        self.cycles += CYC.get(op, 0)
        extra = self.execute(op)
        self.cycles += extra
        if self.timer:
            self.timer = max(0, self.timer - (self.cycles - start))

    def execute(self, op):
        if op == 0x18:      # CLC
            self.c = 0
        elif op == 0x38:    # SEC
            self.c = 1
        elif op == 0x78:    # SEI
            self.i = 1
        elif op == 0xD8:    # CLD
            self.d = 0
        elif op == 0xEA:    # NOP
            pass
        elif op == 0x48:    # PHA
            self.push(self.a)
        elif op == 0x68:    # PLA
            self.a = self.pop()
            self.set_nz(self.a)
        elif op == 0xAA:    # TAX
            self.x = self.a
            self.set_nz(self.x)
        elif op == 0xA8:    # TAY
            self.y = self.a
            self.set_nz(self.y)
        elif op == 0x8A:    # TXA
            self.a = self.x
            self.set_nz(self.a)
        elif op == 0x98:    # TYA
            self.a = self.y
            self.set_nz(self.a)
        elif op == 0x9A:    # TXS
            self.sp = self.x
        elif op == 0xE8:    # INX
            self.x = (self.x + 1) & 0xFF
            self.set_nz(self.x)
        elif op == 0xC8:    # INY
            self.y = (self.y + 1) & 0xFF
            self.set_nz(self.y)
        elif op == 0xCA:    # DEX
            self.x = (self.x - 1) & 0xFF
            self.set_nz(self.x)
        elif op == 0x88:    # DEY
            self.y = (self.y - 1) & 0xFF
            self.set_nz(self.y)
        elif op == 0x0A:    # ASL (accumulator)
            self.c = (self.a >> 7) & 1
            self.a = (self.a << 1) & 0xFF
            self.set_nz(self.a)
        elif op in (0xA9, 0xA0, 0xA2):      # LDA/LDY/LDX #imm
            v = self.imm()
            if op == 0xA9:
                self.a = v
            elif op == 0xA0:
                self.y = v
            else:
                self.x = v
            self.set_nz(v)
        elif op in (0x69, 0xE9):            # ADC/SBC #imm
            v = self.imm()
            if op == 0x69:
                self.a, self.c, self.n, self.v, self.z = self._adc(v)
            else:
                self.a, self.c, self.n, self.v, self.z = self._sbc(v)
        elif op == 0x29:                    # AND #imm
            self.a &= self.imm()
            self.set_nz(self.a)
        elif op == 0x49:                    # EOR #imm
            self.a ^= self.imm()
            self.set_nz(self.a)
        elif op == 0x05:                    # ORA zp
            self.a |= self.read(self.zp_addr())
            self.set_nz(self.a)
        elif op == 0x09:                    # ORA #imm
            self.a |= self.imm()
            self.set_nz(self.a)
        elif op == 0xC9:                    # CMP #imm
            self._cmp(self.a, self.imm())
        elif op == 0xE0:                    # CPX #imm
            self._cmp(self.x, self.imm())
        elif op in (0xA5, 0xAD, 0xB9):      # LDA zp / abs / abs,Y
            if op == 0xA5:
                addr = self.zp_addr()
                extra = 0
            elif op == 0xAD:
                addr = self.abs_addr()
                extra = 0
            else:
                base = self.abs_addr()
                addr = (base + self.y) & 0xFFFF
                extra = 1 if (base & 0xFF) + self.y > 0xFF else 0
            self.a = self.read(addr)
            self.set_nz(self.a)
            return extra
        elif op == 0xB5:                    # LDA zp,X
            self.a = self.read(self.zpx_addr())
            self.set_nz(self.a)
        elif op in (0xA4, 0xAC):            # LDY zp / abs
            addr = self.zp_addr() if op == 0xA4 else self.abs_addr()
            self.y = self.read(addr)
            self.set_nz(self.y)
        elif op in (0xA6, 0xAE, 0xB6):      # LDX zp / abs / zp,Y
            if op == 0xA6:
                addr = self.zp_addr()
            elif op == 0xAE:
                addr = self.abs_addr()
            else:
                addr = (self.zp_addr() + self.y) & 0xFF
            self.x = self.read(addr)
            self.set_nz(self.x)
        elif op in (0x85, 0x8D, 0x99):      # STA zp / abs / abs,Y
            if op == 0x85:
                addr = self.zp_addr()
            elif op == 0x8D:
                addr = self.abs_addr()
            else:
                addr = self.absy_addr()
            self.write(addr, self.a)
        elif op == 0x95:                    # STA zp,X
            self.write(self.zpx_addr(), self.a)
        elif op in (0x84, 0x86):            # STY/STX zp
            addr = self.zp_addr()
            self.write(addr, self.y if op == 0x84 else self.x)
        elif op in (0xC6, 0xE6):            # DEC/INC zp
            addr = self.zp_addr()
            v = self.read(addr)
            v = (v - 1) & 0xFF if op == 0xC6 else (v + 1) & 0xFF
            self.write(addr, v)
            self.set_nz(v)
        elif op in (0xC5, 0xE5, 0x65):      # CMP/SBC/ADC zp
            addr = self.zp_addr()
            v = self.read(addr)
            if op == 0xC5:
                self._cmp(self.a, v)
            elif op == 0xE5:
                self.a, self.c, self.n, self.v, self.z = self._sbc(v)
            else:
                self.a, self.c, self.n, self.v, self.z = self._adc(v)
        elif op == 0xE4:                    # CPX zp
            self._cmp(self.x, self.read(self.zp_addr()))
        elif op == 0x24:                    # BIT zp
            v = self.read(self.zp_addr())
            self.z = 1 if (self.a & v) == 0 else 0
            self.n = (v >> 7) & 1
            self.v = (v >> 6) & 1
        elif op == 0x20:                    # JSR
            target = self.abs_addr()
            ret = self.pc
            self.push((ret >> 8) & 0xFF)
            self.push(ret & 0xFF)
            self.pc = target
        elif op == 0x4C:                    # JMP
            self.pc = self.abs_addr()
        elif op == 0x60:                    # RTS
            lo = self.pop()
            hi = self.pop()
            self.pc = (lo | (hi << 8) | 0x10000) & 0xFFFF
        elif op in (0xD0, 0xF0, 0xB0, 0x90, 0x30):  # BNE/BEQ/BCS/BCC/BMI
            rel = self.fetch()
            if rel & 0x80:
                rel -= 0x100
            taken = {0xD0: not self.z, 0xF0: self.z,
                     0xB0: self.c, 0x90: not self.c,
                     0x30: bool(self.n)}[op]
            if taken:
                old_pc = self.pc
                self.pc = (old_pc + rel) & 0xFFFF
                page = 1 if (old_pc & 0xFF00) != (self.pc & 0xFF00) else 0
                return 1 + page          # taken = +1, page crossing = +1
            return 0                    # not taken = base 2 cycles
        else:
            raise AssertionError(
                f"unhandled opcode ${op:02X} at ${self.pc-1:04X}")
        return 0

    def _cmp(self, reg, v):
        t = reg - v
        self.set_nz(t & 0xFF)
        self.c = 1 if reg >= v else 0

    def _adc(self, v):
        carry = self.c
        s = self.a + v + carry
        nv = 1 if ((~(self.a ^ v) & (self.a ^ s)) & 0x80) else 0
        return (s & 0xFF, 1 if s > 0xFF else 0,
                (s >> 7) & 1, nv, 1 if (s & 0xFF) == 0 else 0)

    def _sbc(self, v):
        carry = self.c
        s = self.a - v - (1 - carry)
        nv = 1 if (((self.a ^ v) & (self.a ^ s)) & 0x80) else 0
        return (s & 0xFF, 1 if s >= 0 else 0,
                (s >> 7) & 1, nv, 1 if (s & 0xFF) == 0 else 0)

    def reset(self):
        lo = self.read(VECTOR_RESET)
        hi = self.read(VECTOR_RESET + 1)
        self.pc = lo | (hi << 8)


def load_rom(path):
    data = Path(path).read_bytes()
    if len(data) < 4096:
        data += b"\x00" * (4096 - len(data))
    return data[:4096]
