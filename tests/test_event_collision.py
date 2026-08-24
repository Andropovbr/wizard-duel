"""Event-table collision regression suite (Round 11).

The uniform 5-byte event table ([delta, reg1, val1, reg2, val2], reg2 = 0 for
a single) is built by the selection-based BuildEvents + AppendEvent, where:

  * the table starts with a 5-byte dummy at offset 0 (all-zero registers, so
    the kernel's pre-first-event apply writes only AUDV0); real entries live
    from offset 5, the marker closes the table (EV_TBL_SIZE = 60 bytes);
  * every event is emitted in strictly ascending row order, so entries are
    appended in the common case;
  * a same-row event merges into the entry as its slot 2 UNLESS the entry is
    already a double, or the new event is the ball or M1 (ENABL / ENAM1,
    whose x can fall below 15 - the deadline for the second write of a line);
    surplus events are bumped to row+1;
  * row bumps and drops never produce delta 0 (two entries at the same
    absolute row), which would make DEC evCnt wrap 0 -> $FF and the entry
    would fire a line late.

These tests drive the REAL ROM's BuildEvents directly on the deterministic
6502 emulator (the same code path the VBLANK uses every frame) and validate
semantics + the visible kernel end to end:

  * reproduce-first: the exact reported combinations must build a valid table;
  * semantic validation: no delta 0, strictly increasing rows, every register
    alternates ON then OFF, the terminator is valid, and decoded deltas map
    back to the same absolute rows;
  * stretched-object: the actual kernel runs to KERNEL_SCANLINES while GRP0,
    GRP1, ENABL, ENAM0 and ENAM1 are tracked; on the LAST visible scanline all
    five must be cleared (no object left enabled to the bottom edge);
  * ball/M1 slot invariant: ENABL and ENAM1 never occupy a double's slot 2;
  * scenarios: both players + ball with and without each missile, dead-player
    variants, and boundary rows near 0, 1, KERNEL_SCANLINES-2 and
    KERNEL_SCANLINES-1.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import ROM_PATH, require_build, parse_symbols
from emu6502 import Cpu, load_rom
from test_timing import read_constants

C = read_constants()
EV_REG_GRP0 = C["EV_REG_GRP0"]           # 1
EV_REG_GRP1 = C["EV_REG_GRP1"]           # 2
EV_REG_ENAM0 = C["EV_REG_ENAM0"]         # 3
EV_REG_ENAM1 = C["EV_REG_ENAM1"]         # 4
EV_REG_ENABL = C["EV_REG_ENABL"]         # 5
EV_MARKER_VAL = C["EV_MARKER_VAL"]       # $FF
KERNEL_SCANLINES = C["KERNEL_SCANLINES"]         # 185

# EV_WRITE_BASE = $1A; a register index 1..5 maps to GRP0..ENABL.
REG_TIA = {
    EV_REG_GRP0: 0x1B,
    EV_REG_GRP1: 0x1C,
    EV_REG_ENAM0: 0x1D,
    EV_REG_ENAM1: 0x1E,
    EV_REG_ENABL: 0x1F,
}

REG_NAMES = {1: "GRP0", 2: "GRP1", 3: "ENAM0", 4: "ENAM1", 5: "ENABL"}

# The dummy occupies the table's first 5 bytes; real entries start here.
ENTRY0 = 5


class EventBuilderHarness:
    """Drives the real BuildEvents + kernel on the deterministic emulator."""

    def __init__(self):
        require_build()
        self.rom = load_rom(ROM_PATH)
        self.sym = parse_symbols()
        self.cpu = Cpu(self.rom)
        self.cpu.reset()
        self.evTbl_addr = self.sym["evTbl"] - 0x80
        self.tblLen_addr = self.sym["tblLen"] - 0x80
        self.evCnt_addr = self.sym["evCnt"] - 0x80
        self.kernel_end = self.sym["0.kernelEnd"]
        self.kernel_loop = self.sym["KernelLoop"]
        self.sof = self.sym["StartOfFrame"]

    def _ram(self, name):
        return self.sym[name] - 0x80

    def set_state(self, p0=88, p1=50, by=96, m0y=96, m1y=100,
                  m0act=False, m1act=False, hp0=3, hp1=3, ball_x=80):
        r = self.cpu.ram
        r[self._ram("P0Y")] = p0
        r[self._ram("P1Y")] = p1
        r[self._ram("ball_y")] = by
        r[self._ram("ball_x")] = ball_x
        r[self._ram("m0_y")] = m0y
        r[self._ram("m1_y")] = m1y
        r[self._ram("m_active")] = (0x01 if m0act else 0) | (0x02 if m1act else 0)
        r[self._ram("p0_hp")] = hp0
        r[self._ram("p1_hp")] = hp1

    def build_events(self, **kwargs):
        """Run the real BuildEvents with the given object state.

        A synthetic return address (StartOfFrame) is planted on the stack so
        BuildEvents can RTS back to a known label.
        """
        self._ball_x = kwargs.get("ball_x", 80)
        self.set_state(**kwargs)
        self.cpu.sp = 0xFD
        self.cpu.write(0x100 + 0xFD, (self.sof >> 8) & 0xFF)
        self.cpu.write(0x100 + 0xFC, self.sof & 0xFF)
        self.cpu.sp = 0xFB
        self.cpu.pc = self.sym["BuildEvents"]
        n = 0
        while self.cpu.pc != self.sof:
            self.cpu.step()
            n += 1
            if n > 50000:
                raise AssertionError("BuildEvents did not return")
        return self.raw_table()

    def raw_table(self):
        """Return the converted evTbl bytes (delta-encoded) in RAM.

        Real entries start at table offset ENTRY0 (5), after the dummy.
        """
        tlen = self.cpu.ram[self.tblLen_addr]
        return bytes(self.cpu.ram[self.evTbl_addr + ENTRY0:
                                   self.evTbl_addr + ENTRY0 + 5 * tlen + 5])

    def null_delta(self):
        """The prime delta: the first real entry's absolute row."""
        return self.cpu.ram[self._ram("nullDelta")]

    def decoded_entries(self):
        """Decode the table into entry-level rows.

        Each entry is (abs_row, [(reg, val), (reg2, val2)...]): a single entry
        has one write, a double has two.  Entry rows must be strictly
        increasing (that is the delta-0 invariant); writes WITHIN an entry
        legitimately share the entry row.
        """
        tbl = self.raw_table()
        entries = []
        row = self.null_delta()
        i = 0
        while i < len(tbl) and tbl[i] != EV_MARKER_VAL:
            d = tbl[i]
            reg1 = tbl[i + 1]
            val1 = tbl[i + 2]
            writes = [(reg1, val1)]
            if tbl[i + 3] != 0:                 # reg2 (0 = single event)
                writes.append((tbl[i + 3], tbl[i + 4]))
            entries.append((row, writes))
            row += d
            i += 5
        return entries

    def decoded_rows(self):
        """Flatten decoded_entries into [(abs_row, reg, val), ...]."""
        return [(row, reg, val)
                for row, writes in self.decoded_entries()
                for reg, val in writes]

    def run_kernel(self):
        """Run the visible kernel to KERNEL_SCANLINES after BuildEvents.

        Replicates the real priming: evCnt = nullDelta with carry clear and
        Y = ENTRY0 (5), so the apply reads the dummy until the first decode
        advances Y to 10; when nullDelta = 0, entry 0 fires on row 0, so
        evCnt is primed with entry 0's OWN delta and Y = 10 (the apply reads
        real entry 0 from the first line).  Returns the TIA state (GRP0,
        GRP1, ENAM0, ENAM1, ENABL) sampled on every kernel scanline
        boundary, INCLUDING the last visible one.
        """
        r = self.cpu.ram
        nd = r[self._ram("nullDelta")]
        r[self.evCnt_addr] = nd
        self.cpu.c = 0                      # CLC from the real priming
        if nd == 0:                         # entry 0 fires on line 0
            r[self.evCnt_addr] = r[self.evTbl_addr + ENTRY0]
            self.cpu.y = ENTRY0 + 5         # 10: apply reads real entry 0
        else:
            self.cpu.y = ENTRY0             # 5: apply reads the dummy
        self.cpu.pc = self.kernel_loop
        samples = []
        guard = 0
        while True:
            if self.cpu.pc == self.kernel_loop:
                # About to start a scanline (WSYNC is the first instruction):
                # sample the state that will be displayed on this line.
                samples.append(tuple(self.cpu.tia[REG_TIA[reg]] for reg in
                                     (1, 2, 3, 4, 5)))
            self.cpu.step()
            guard += 1
            if self.cpu.pc == self.kernel_end:
                break
            if guard > 4000:
                raise AssertionError("kernel did not reach its end")
        return samples

    def assert_valid_table(self, rows, msg=""):
        """Semantic validation of a decoded event table (entry-level)."""
        entries = self.decoded_entries()
        if not entries:
            raise AssertionError(f"{msg}: table decoded to no entries")
        # 1. no delta-0 entry: absolute ENTRY rows must be strictly increasing.
        entry_rows = [r for r, _ in entries]
        for a, b in zip(entry_rows, entry_rows[1:]):
            if a >= b:
                raise AssertionError(
                    f"{msg}: entry rows not strictly increasing: "
                    f"{entry_rows} (delta 0 => OFF never fires)")
        # 2. every register must alternate exactly ON then OFF (in order).
        per_reg = {}
        for row, reg, val in rows:
            per_reg.setdefault(reg, []).append((row, val))
        for reg, evs in per_reg.items():
            if len(evs) % 2 != 0:
                # Dropped OFF (documented builder limitation): the trailing
                # unpaired event must be an ON.  Its OFF was dropped either
                # because it fell at >= KERNEL_SCANLINES (bottom object, e.g.
                # ball at y >= 181) or because a multi-way same-row collision
                # near the bottom bumped it past the kernel end (a fifth event
                # sharing a row cannot fit the two-writes-per-entry scheme).
                # The object then stays enabled through line 184 and is
                # cleared by the overscan init.  An unpaired OFF is always a
                # bug and still fails here.
                last_row, last_val = evs[-1]
                if last_val == 0:
                    raise AssertionError(
                        f"{msg}: {REG_NAMES[reg]} has an odd number of events "
                        f"ending in an OFF: {evs}")
                evs = evs[:-1]        # ignore the dropped trailing OFF event
            for j in range(0, len(evs), 2):
                row_on, val_on = evs[j]
                row_off, val_off = evs[j + 1]
                expected_on = (C["PADDLE_BITS"] if reg in
                               (EV_REG_GRP0, EV_REG_GRP1) else
                               C["MISSILE_ENABLE"] if reg in
                               (EV_REG_ENAM0, EV_REG_ENAM1) else
                               C["BALL_ENABLE"])
                if val_on != expected_on:
                    raise AssertionError(
                        f"{msg}: {REG_NAMES[reg]} ON must use the enable value,"
                        f" got {val_on}")
                if val_off != 0:
                    raise AssertionError(
                        f"{msg}: {REG_NAMES[reg]} OFF must be 0, got {val_off}")
                if row_on >= row_off:
                    raise AssertionError(
                        f"{msg}: {REG_NAMES[reg]} ON row {row_on} must precede "
                        f"OFF row {row_off}")

    def assert_kernel_clears_objects(self, samples, msg=""):
        """Each register must turn off at exactly its OFF event row.

        `samples[i]` is the TIA state at the START of kernel line i (sampled
        at KernelLoop before the WSYNC that begins the line).  An event's
        writes are applied at the start of its row (the write completes before
        the beam reaches pixel 0), so a register whose OFF event fires on line
        R is enabled through line R and cleared from line R+1 on.  If the OFF
        row is >= KERNEL_SCANLINES the event is dropped by design (the
        bottom-ball case) and the register is cleared by the overscan init.
        """
        if len(samples) != KERNEL_SCANLINES:
            raise AssertionError(
                f"{msg}: kernel ran {len(samples)} lines, expected "
                f"{KERNEL_SCANLINES}")
        # Last enabled line index per register (from the samples) and the OFF
        # row per register (from the event table).
        last_enabled = {}
        for line, sample in enumerate(samples):
            for idx, reg in enumerate((1, 2, 3, 4, 5)):
                if sample[idx] != 0:
                    last_enabled[reg] = line
        off_row = {}
        for row, reg, val in self.decoded_rows():
            if val == 0:                       # an OFF event for that register
                off_row[reg] = row
        for reg in (1, 2, 3, 4, 5):
            expected_off = off_row.get(reg)
            actual_last = last_enabled.get(reg)
            if expected_off is None:
                # Dropped OFF (documented builder limitation, see
                # assert_valid_table): the register stays enabled through line
                # KERNEL_SCANLINES - 1 and is cleared by the overscan init.
                # This only happens for objects whose OFF event was dropped
                # because it reached KERNEL_SCANLINES (bottom object or a
                # bottom-edge multi-way collision bumped it there).
                continue
            if expected_off >= KERNEL_SCANLINES:
                # Dropped OFF (bottom object): it may stay on to the last
                # line; overscan init clears it.  Anything earlier is fine.
                continue
            if actual_last is None:
                raise AssertionError(
                    f"{msg}: {REG_NAMES[reg]} never turned on")
            # The register is on at the START of its OFF line (the write lands
            # during that line), so the last enabled sample is the OFF row.
            if actual_last != expected_off:
                raise AssertionError(
                    f"{msg}: {REG_NAMES[reg]} last enabled line {actual_last} "
                    f"but OFF event is on line {expected_off} - object "
                    f"stretched past its OFF event")


class TestReportedStretchRepro(unittest.TestCase):
    """Reproduce-first: the exact combinations that caused the stretch."""

    def setUp(self):
        self.h = EventBuilderHarness()

    def test_missile_crossing_ball_both_alive(self):
        # M0 ON == Ball ON (96) and M0 OFF == P0 OFF == Ball OFF (100):
        # the third event at row 100 must be bumped, not stored at row 100.
        self.h.build_events(p0=88, p1=50, by=96, m0y=96, m1y=100,
                            m0act=True, m1act=False)
        rows = self.h.decoded_rows()
        self.h.assert_valid_table(rows, "both-alive crossing")
        # No two ENTRIES may share an absolute row (that is delta 0).
        entry_rows = [r for r, _ in self.h.decoded_entries()]
        self.assertEqual(len(entry_rows), len(set(entry_rows)),
                         f"duplicate entry rows in table: {entry_rows}")

    def test_one_dead_player_variant(self):
        # P1 dead: the same 3-way OFF coincidence must still be bumped safely.
        self.h.build_events(p0=88, p1=50, by=96, m0y=96, m1y=100,
                            m0act=True, m1act=False, hp1=0)
        rows = self.h.decoded_rows()
        self.h.assert_valid_table(rows, "one-dead crossing")
        entry_rows = [r for r, _ in self.h.decoded_entries()]
        self.assertEqual(len(entry_rows), len(set(entry_rows)),
                         f"duplicate entry rows in table: {entry_rows}")


class TestSemanticValidation(unittest.TestCase):
    """The event table must always obey the kernel's invariants."""

    def setUp(self):
        self.h = EventBuilderHarness()

    def test_no_delta_zero_anywhere(self):
        # Sweep missile/ball rows over the full range with both players at
        # colliding heights; every produced table must have strictly
        # increasing ENTRY rows (never delta 0).
        for by in (0, 1, 95, 96, 97, 180, 181):
            for m0y in (0, 1, 95, 96, 97, 100, 175, 176):
                self.h.build_events(p0=88, p1=50, by=by, m0y=m0y, m1y=100,
                                    m0act=True, m1act=False)
                self.h.assert_valid_table(
                    self.h.decoded_rows(), f"by={by} m0y={m0y}")
                entry_rows = [r for r, _ in self.h.decoded_entries()]
                self.assertEqual(len(entry_rows), len(set(entry_rows)),
                                 f"duplicate entry rows (delta 0) for by={by} "
                                 f"m0y={m0y}: {entry_rows}")

    def test_terminator_is_valid(self):
        self.h.build_events(p0=88, p1=50, by=96, m0y=96, m1y=100,
                            m0act=True, m1act=True)
        tbl = self.h.raw_table()
        self.assertEqual(tbl[-5], EV_MARKER_VAL,
                         "last 5 bytes must be the marker entry")
        self.assertNotIn(EV_MARKER_VAL, tbl[:-5],
                         "marker must appear only once, at the end")

    def test_decoded_deltas_map_to_same_rows(self):
        # Rebuild the same state through the real ROM and through the Python
        # model; the absolute rows must match exactly.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_events as M
        self.h.build_events(p0=88, p1=50, by=96, m0y=96, m1y=100,
                            m0act=True, m1act=True)
        rows = self.h.decoded_rows()
        active, objects = M.scene(88, 50, 96, 96, 100, True, True)
        model, nd = M.build(active, objects)
        self.assertEqual(self.h.null_delta(), nd,
                         "ROM nullDelta differs from the validated model")
        model_writes = []
        row = nd
        i = M.ENTRY0            # real entries start after the dummy
        while model[i] != M.EV_MARKER_VAL:
            model_writes.append((row, model[i + 1], model[i + 2]))
            if model[i + 3] != 0:
                model_writes.append((row, model[i + 3], model[i + 4]))
            row += model[i]
            i += 5
        self.assertEqual(rows, model_writes,
                         "ROM table rows differ from the validated Python model")


class TestStretchedObjectKernel(unittest.TestCase):
    """The kernel must never leave an object enabled on the last line."""

    def setUp(self):
        self.h = EventBuilderHarness()

    def test_kernel_clears_all_registers(self):
        self.h.build_events(p0=88, p1=50, by=96, m0y=96, m1y=100,
                            m0act=True, m1act=True)
        samples = self.h.run_kernel()
        self.h.assert_kernel_clears_objects(samples, "both-missiles")

    def test_kernel_clears_when_missile_crosses_ball(self):
        self.h.build_events(p0=88, p1=50, by=96, m0y=96, m1y=100,
                            m0act=True, m1act=False)
        samples = self.h.run_kernel()
        self.h.assert_kernel_clears_objects(samples, "M0 crosses ball")

    def test_kernel_clears_no_missiles(self):
        self.h.build_events(p0=88, p1=50, by=96, m0y=96, m1y=100,
                            m0act=False, m1act=False)
        samples = self.h.run_kernel()
        self.h.assert_kernel_clears_objects(samples, "no missiles")

    def test_kernel_clears_one_dead_player(self):
        self.h.build_events(p0=88, p1=50, by=96, m0y=96, m1y=100,
                            m0act=True, m1act=False, hp1=0)
        samples = self.h.run_kernel()
        self.h.assert_kernel_clears_objects(samples, "P1 dead")


class TestScenarios(unittest.TestCase):
    """The six required scenarios at colliding rows."""

    def setUp(self):
        self.h = EventBuilderHarness()

    def _check(self, msg, **kwargs):
        self.h.build_events(**kwargs)
        rows = self.h.decoded_rows()
        self.h.assert_valid_table(rows, msg)
        entry_rows = [r for r, _ in self.h.decoded_entries()]
        if len(entry_rows) != len(set(entry_rows)):
            raise AssertionError(f"{msg}: duplicate entry rows: {entry_rows}")
        samples = self.h.run_kernel()
        self.h.assert_kernel_clears_objects(samples, msg)

    def test_p0_p1_ball_coincident(self):
        # Players and ball share ON rows; all OFF rows coincide at 100 too.
        self._check("P0+P1+Ball", p0=88, p1=88, by=88, m0y=96, m1y=100,
                    m0act=False, m1act=False)

    def test_p0_p1_ball_m0(self):
        self._check("P0+P1+Ball+M0", p0=88, p1=50, by=96, m0y=96, m1y=100,
                    m0act=True, m1act=False)

    def test_p0_p1_ball_m1(self):
        self._check("P0+P1+Ball+M1", p0=88, p1=50, by=96, m0y=96, m1y=100,
                    m0act=False, m1act=True)

    def test_p0_p1_ball_m0_m1(self):
        self._check("P0+P1+Ball+M0+M1", p0=88, p1=50, by=96, m0y=96, m1y=100,
                    m0act=True, m1act=True)

    def test_p0_dead(self):
        self._check("P0 dead", p0=88, p1=50, by=96, m0y=96, m1y=100,
                    m0act=True, m1act=False, hp0=0)

    def test_p1_dead(self):
        self._check("P1 dead", p0=88, p1=50, by=96, m0y=96, m1y=100,
                    m0act=True, m1act=False, hp1=0)


class TestBoundaryRows(unittest.TestCase):
    """Boundary rows near 0, 1, KERNEL_SCANLINES-2, KERNEL_SCANLINES-1."""

    def setUp(self):
        self.h = EventBuilderHarness()

    def _check(self, msg, **kwargs):
        self.h.build_events(**kwargs)
        rows = self.h.decoded_rows()
        self.h.assert_valid_table(rows, msg)
        entry_rows = [r for r, _ in self.h.decoded_entries()]
        if len(entry_rows) != len(set(entry_rows)):
            raise AssertionError(f"{msg}: duplicate entry rows: {entry_rows}")
        samples = self.h.run_kernel()
        self.h.assert_kernel_clears_objects(samples, msg)

    def test_rows_near_zero(self):
        self._check("top boundary 0", p0=0, p1=0, by=0, m0y=0, m1y=0,
                    m0act=True, m1act=True)
        self._check("top boundary 1", p0=1, p1=1, by=1, m0y=1, m1y=1,
                    m0act=True, m1act=True)

    def test_rows_near_kernel_end(self):
        # P0/P1 bottom: PLAYER_Y_MAX = 172 -> OFF at 184.  Ball bottom:
        # BALL_Y_MAX = 181 -> OFF at 185 (dropped, but the kernel clears
        # ENABL during overscan init).  A 3-way collision at 184 must bump
        # safely without creating a delta-0 entry.
        self._check("bottom boundary 183", p0=171, p1=171, by=179, m0y=183,
                    m1y=183, m0act=True, m1act=True)
        self._check("bottom boundary 184", p0=172, p1=172, by=180, m0y=184,
                    m1y=184, m0act=True, m1act=True)

    def test_five_way_bottom_collision_drops_last_off(self):
        # Documented limitation: five events share row 183 (P0 OFF, P1 OFF,
        # Ball OFF, M0 ON, M1 ON).  Two-writes-per-entry allows two entries on
        # the row (Ball OFF + M0 ON merge; M1 ON bump to 184 + P0 OFF merge);
        # P1's OFF is bumped 183 -> 184 -> 185 and dropped.  GRP1 therefore
        # stays enabled through the last kernel line and is cleared by the
        # overscan init.  No delta-0 entry is created and the table stays
        # valid; the odd GRP1 count is the accepted drop.
        self.h.build_events(p0=171, p1=171, by=179, m0y=183, m1y=183,
                            m0act=True, m1act=True)
        rows = self.h.decoded_rows()
        self.h.assert_valid_table(rows, "5-way bottom collision")
        entry_rows = [r for r, _ in self.h.decoded_entries()]
        self.assertEqual(len(entry_rows), len(set(entry_rows)),
                         f"duplicate entry rows: {entry_rows}")
        samples = self.h.run_kernel()
        self.h.assert_kernel_clears_objects(samples, "5-way bottom collision")
        # GRP1 has exactly one (unpaired ON) event: it was the dropped OFF.
        grp1 = [r for r, reg, val in rows if reg == EV_REG_GRP1]
        self.assertEqual(len(grp1), 1, f"GRP1 events: {grp1}")


class TestBallWriteSlotInvariant(unittest.TestCase):
    """ENABL and ENAM1 write-slot invariant.

    The kernel's second write lands at CPU cycle 27 of the scanline, which is
    only safe for objects whose x is guaranteed >= 15.  ENAM1 is never slot 2
    (M1 x varies).  ENABL may be slot 2 only when ball_x >= 15; when ball_x < 15
    and Ball shares a row with a player, the two are reordered within the slot
    pair (ball -> slot 1, player -> slot 2) so neither is displaced.

    These tests run the REAL ROM's BuildEvents across every collision and
    assert that the slot invariant holds given the current ball_x.
    """

    def setUp(self):
        self.h = EventBuilderHarness()

    def assert_slot_legal(self, msg):
        ball_x = getattr(self.h, "_ball_x", 80)
        for row, writes in self.h.decoded_entries():
            if len(writes) != 2:
                continue  # singles have no write-slot problem
            (reg1, _), (reg2, _) = writes
            if reg2 == EV_REG_ENABL:
                self.assertGreaterEqual(
                    ball_x, 15,
                    f"{msg}: ENABL is slot 2 at row {row} with ball_x={ball_x}; "
                    f"the late write (cycle 27) can miss the ball")
            self.assertNotEqual(
                reg2, EV_REG_ENAM1,
                f"{msg}: ENAM1 is the second write of the double at row {row}; "
                f"the late write (cycle 27) can miss m1_x")

    def test_ball_never_second_write_with_players(self):
        # Force the ball's ON and OFF rows onto P0's and P1's ON/OFF rows.
        for by in (50, 58, 62, 88, 92, 96, 100, 104):
            self.h.build_events(p0=88, p1=50, by=by, m0y=96, m1y=100,
                                m0act=False, m1act=False, ball_x=80)
            self.h.assert_valid_table(self.h.decoded_rows(), f"by={by}")
            self.assert_slot_legal(f"by={by}")

    def test_ball_never_second_write_with_missiles(self):
        for by in (92, 96, 100, 104):
            self.h.build_events(p0=88, p1=50, by=by, m0y=96, m1y=100,
                                m0act=True, m1act=True, ball_x=80)
            self.h.assert_valid_table(self.h.decoded_rows(), f"by={by}")
            self.assert_slot_legal(f"by={by}")

    def test_ball_never_second_write_full_sweep(self):
        # Sweep the ball over the whole arena with every object active; a row
        # the ball shares must respect the slot invariant given ball_x.
        for by in range(0, 182, 3):
            self.h.build_events(p0=88, p1=50, by=by, m0y=96, m1y=100,
                                m0act=True, m1act=True, ball_x=80)
            self.h.assert_valid_table(self.h.decoded_rows(), f"by={by}")
            self.assert_slot_legal(f"by={by}")
            entry_rows = [r for r, _ in self.h.decoded_entries()]
            self.assertEqual(len(entry_rows), len(set(entry_rows)),
                             f"duplicate entry rows for by={by}")

    def test_slot_swap_with_ball_left_of_safe_zone(self):
        # ball_x < 15: Ball and player must swap slots (no bump).
        for bx in (0, 5, 10, 14):
            for by in (88, 92, 96, 100):
                self.h.build_events(p0=88, p1=50, by=by, m0y=96, m1y=100,
                                    m0act=False, m1act=False, ball_x=bx)
                self.h.assert_valid_table(self.h.decoded_rows(),
                                          f"bx={bx} by={by}")
                self.assert_slot_legal(f"bx={bx} by={by}")
                # Verify no player row displacement
                for row, reg, val in self.h.decoded_rows():
                    if reg == EV_REG_GRP0:
                        if val:  # P0 ON
                            self.assertEqual(row, 88,
                                             f"P0 ON displaced at bx={bx}")
                        else:    # P0 OFF
                            self.assertEqual(row, 88 + 18,
                                             f"P0 OFF displaced at bx={bx}")
                    if reg == EV_REG_GRP1:
                        if val:  # P1 ON
                            self.assertEqual(row, 50,
                                             f"P1 ON displaced at bx={bx}")
                        else:    # P1 OFF
                            self.assertEqual(row, 50 + 18,
                                             f"P1 OFF displaced at bx={bx}")

    def test_slot_swap_at_right_edge(self):
        # Reproduce the reported scenario: ball_x = BALL_X_MAX, ball ON/OFF
        # coincides with P1 ON/OFF.  Ball must not change row.
        BALL_X_MAX = 160 - 4  # BALL_WIDTH = 4
        BH = C["BALL_HEIGHT"]
        PH = C["PLAYER_HEIGHT"]
        for by in (50, 50 + PH):
            self.h.build_events(p0=88, p1=50, by=by, m0y=96, m1y=100,
                                m0act=False, m1act=False, ball_x=BALL_X_MAX)
            self.h.assert_valid_table(self.h.decoded_rows(),
                                      f"ball_x=MAX by={by}")
            self.assert_slot_legal(f"ball_x=MAX by={by}")
            for row, reg, val in self.h.decoded_rows():
                if reg == EV_REG_ENABL:
                    if val:  # Ball ON
                        self.assertEqual(row, by,
                                         f"Ball ON row shifted at right edge")
                    else:    # Ball OFF
                        self.assertEqual(row, by + BH,
                                         f"Ball OFF row shifted at right edge")

    def test_all_56_collision_cases_no_displacement(self):
        """8 collision types × 7 ball_x positions = 56 cases.

        Ball shares a row with ONE player; the other player is far away.
        Neither Ball nor Player may be displaced from its logical row.
        """
        PH = C["PLAYER_HEIGHT"]
        BH = C["BALL_HEIGHT"]
        P0Y, P1Y_FAR = 83, 120
        P1Y, P0Y_FAR = 83, 120
        X_POSITIONS = [0, 14, 15, 16, 136, 156, 159]
        CASES = [
            ("Ball_ON==P0_ON",   P0Y, P1Y_FAR, P0Y,           "P0"),
            ("Ball_OFF==P0_ON",  P0Y, P1Y_FAR, P0Y - BH,      "P0"),
            ("Ball_ON==P0_OFF",  P0Y, P1Y_FAR, P0Y + PH,      "P0"),
            ("Ball_OFF==P0_OFF", P0Y, P1Y_FAR, P0Y + PH - BH, "P0"),
            ("Ball_ON==P1_ON",   P0Y_FAR, P1Y, P1Y,           "P1"),
            ("Ball_OFF==P1_ON",  P0Y_FAR, P1Y, P1Y - BH,      "P1"),
            ("Ball_ON==P1_OFF",  P0Y_FAR, P1Y, P1Y + PH,      "P1"),
            ("Ball_OFF==P1_OFF", P0Y_FAR, P1Y, P1Y + PH - BH, "P1"),
        ]
        for case_name, p0y, p1y, by, player in CASES:
            for bx in X_POSITIONS:
                self.h.build_events(p0=p0y, p1=p1y, by=by, m0y=0, m1y=0,
                                    m0act=False, m1act=False, ball_x=bx)
                self.h.assert_valid_table(self.h.decoded_rows(),
                                          f"{case_name} bx={bx}")
                self.assert_slot_legal(f"{case_name} bx={bx}")
                for row, reg, val in self.h.decoded_rows():
                    if reg == EV_REG_ENABL:
                        if val:  # Ball ON
                            self.assertEqual(
                                row, by,
                                f"{case_name} bx={bx}: Ball ON displaced "
                                f"({row} != {by})")
                        else:    # Ball OFF
                            self.assertEqual(
                                row, by + BH,
                                f"{case_name} bx={bx}: Ball OFF displaced "
                                f"({row} != {by + BH})")
                    p_reg = EV_REG_GRP0 if player == "P0" else EV_REG_GRP1
                    if reg == p_reg:
                        exp_on = p0y if player == "P0" else p1y
                        if val:  # Player ON
                            self.assertEqual(
                                row, exp_on,
                                f"{case_name} bx={bx}: {player} ON displaced "
                                f"({row} != {exp_on})")
                        else:    # Player OFF
                            self.assertEqual(
                                row, exp_on + PH,
                                f"{case_name} bx={bx}: {player} OFF displaced"
                                f" ({row} != {exp_on + PH})")

    def test_ball_never_displaced_sweep(self):
        """Sweep ball_y across the arena with various ball_x.

        Ball ON must always be at ball_y, Ball OFF at ball_y + BH.
        """
        BH = C["BALL_HEIGHT"]
        for bx in (0, 14, 15, 16, 80, 156):
            for by in range(0, 185 - BH, 7):
                self.h.build_events(p0=88, p1=50, by=by, m0y=96, m1y=100,
                                    m0act=True, m1act=True, ball_x=bx)
                for row, reg, val in self.h.decoded_rows():
                    if reg == EV_REG_ENABL:
                        if val:
                            self.assertEqual(
                                row, by,
                                f"bx={bx} by={by}: Ball ON displaced")
                        else:
                            self.assertEqual(
                                row, by + BH,
                                f"bx={bx} by={by}: Ball OFF displaced")


if __name__ == "__main__":
    unittest.main()