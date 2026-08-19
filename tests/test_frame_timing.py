"""Frame-timing and event-table stability validation via the 6502 emulator.

Runs many full frames with aggressive fire-button input and checks the
deterministic frame loop properties the Round 3.1 kernel depends on:

  * every frame reaches StartOfFrame (the loop never hangs or crashes);
  * the event table never exceeds EV_TBL_SIZE bytes, even when both
    missiles are firing (the builder inserts directly into the table);
  * the kernel keeps firing every event (tblLen stays within bounds and
    the countdown bookkeeping stays coherent across frames).

Scanline counts themselves are validated from constants (262) and the kernel
cycle budget elsewhere; this test exercises the builder + kernel end to end
in a deterministic CPU model.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import ROM_PATH, require_build
from emu6502 import Cpu, load_rom
from test_events import EV_TBL_SIZE


class TestFrameStability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.rom = load_rom(ROM_PATH)
        from common import parse_symbols
        cls.sym = parse_symbols()
        cls.sof = cls.sym["StartOfFrame"]

    def setUp(self):
        self.cpu = Cpu(self.rom)
        self.cpu.reset()

    def _ram(self, name):
        return self.sym[name] - 0x80

    def run_frame(self, inject_at=None, inject_fn=None):
        """Run exactly one frame (returns cycles consumed).

        If the CPU is already at StartOfFrame (the state left by a previous
        call), the frame currently being entered is the one measured, so a
        call always returns exactly one frame's worth of cycles.

        If `inject_at` is a PC address, `inject_fn` is invoked every time the
        CPU reaches it during the frame (used to force game state right before
        BuildEvents consumes it).
        """
        start = self.cpu.cycles
        at_sof = self.cpu.pc == self.sof
        count = 0
        while count < 2:
            if inject_at is not None and self.cpu.pc == inject_at:
                inject_fn()          # inject before BuildEvents executes
            self.cpu.step()
            if self.cpu.pc == self.sof:
                count += 1
                if (at_sof and count == 1) or count == 2:
                    return self.cpu.cycles - start
        raise AssertionError("frame did not terminate")

    def test_loop_is_stable_over_many_frames(self):
        # Boot (latches read pressed), then released; nothing must fire.
        self.cpu.inpt[4] = 0x00
        self.cpu.inpt[5] = 0x00
        for _ in range(20):
            self.run_frame()

    def test_table_never_exceeds_max_with_aggressive_fire(self):
        # Alternate both fire buttons aggressively so M0 and M1 keep spawning
        # and despawning; the builder must keep the table within EV_TBL_SIZE.
        tlen = self._ram("tblLen")
        self.cpu.inpt[4] = 0xFF      # first frame is the boot sync frame
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        for i in range(60):
            p0 = (i // 4) % 2 == 0
            p1 = (i // 6) % 2 == 0
            self.cpu.inpt[4] = 0x00 if p0 else 0xFF
            self.cpu.inpt[5] = 0x00 if p1 else 0xFF
            self.run_frame()
            self.assertLessEqual(self.cpu.ram[tlen], EV_TBL_SIZE,
                                 f"tblLen exceeded EV_TBL_SIZE at frame {i}")
            self.assertGreaterEqual(self.cpu.ram[tlen], 1,
                                    f"tblLen empty at frame {i}")

    def test_missiles_actually_fire_and_despawn(self):
        # Sanity: pressing P0 spawns M0 and it later despawns, proving the
        # event pipeline drives real behavior across frames.
        m_active = self._ram("m_active")
        self.cpu.inpt[4] = 0xFF      # boot sync frame first (buttons released)
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        self.cpu.inpt[4] = 0x00      # now a real press
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        self.assertNotEqual(self.cpu.ram[m_active] & 0x01, 0,
                            "M0 must spawn after a P0 press")
        self.cpu.inpt[4] = 0xFF
        for _ in range(90):          # fly off the right edge and despawn
            self.run_frame()
        self.assertEqual(self.cpu.ram[m_active] & 0x01, 0,
                         "M0 must despawn after flying off-screen")
        # m0_x itself may wrap after despawn, but the active flag is the
        # source of truth the builder checks.

    def test_frame_never_slips_to_263_under_max_collision_stress(self):
        # Regression: before Round 4's fixed overscan (WSYNC countdown +
        # branchless ProcessCollisions), the heaviest VBLANK path slipped ~1%
        # of frames to 263 scanlines.  This reproduces that exact worst case
        # (both collision latches asserted every frame + alternating fire
        # presses, so both missiles re-spawn after every hit) and asserts
        # every frame is exactly 19912 cycles = 262 scanlines.
        #
        # Round 5 keeps the stress real: without topping HP the players would
        # die during the 3 boot frames and spend the 80 loop frames dead
        # (no missiles), silently weakening the worst case.  HP is therefore
        # re-filled to PLAYER_START_HP every loop frame so both missiles keep
        # spawning and hitting for the whole test.
        p0_hp = self._ram("p0_hp")
        p1_hp = self._ram("p1_hp")
        self.cpu.inpt[4] = 0xFF      # boot sync frames first
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        for _ in range(3):
            self.cpu.cxm0p = 0xC0
            self.cpu.cxm1p = 0xC0
            self.run_frame()
        for i in range(80):
            press = (i % 2 == 0)
            self.cpu.inpt[4] = 0x00 if press else 0xFF
            self.cpu.inpt[5] = 0x00 if press else 0xFF
            self.cpu.cxm0p = 0xC0    # M0 x P1 AND M0 x P0 latched
            self.cpu.cxm1p = 0xC0    # M1 x P0 AND M1 x P1 latched
            self.cpu.ram[p0_hp] = 3  # keep both players alive
            self.cpu.ram[p1_hp] = 3
            cycles = self.run_frame()
            self.assertEqual(cycles, 19912,
                             f"frame {i} ran {cycles} cycles "
                             f"({cycles / 76:.0f} scanlines), expected 262")

    def test_no_stretched_objects_when_missiles_cross_ball(self):
        # Round 7 regression: a third event colliding with a double table row
        # must be bumped to row+1.  Before the fix .insertSingle stored the
        # ORIGINAL stacked row, producing two entries at the same absolute row
        # -> delta 0 -> the kernel's DEC evCnt wrapped 0 -> $FF -> the OFF
        # event never fired and the object stayed enabled to the bottom edge
        # (vertical stretch).  The realistic trigger is both players alive at
        # the same row, both missiles flying, and the ball crossing the
        # missile rows (ball OFF + player OFF + missile OFF on one row, and
        # player ON + missile ON + missile ON on another).  Positions are
        # injected exactly when pc reaches BuildEvents (after VBLANK movement)
        # so the 3-way rows genuinely coincide, then the full frame - kernel
        # included - must run 262 scanlines and produce a delta-0-free table.
        EV_SINGLE_FLAG = 0x80
        EV_TERMINATOR_DELTA = 0xFF
        evTbl = self._ram("evTbl")
        tblLen = self._ram("tblLen")
        be = self.sym["BuildEvents"]
        p0_hp = self._ram("p0_hp")
        p1_hp = self._ram("p1_hp")
        self.cpu.inpt[4] = 0xFF      # boot sync frame first
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        for i in range(60):
            self.cpu.ram[p0_hp] = 3   # keep both players alive all the way
            self.cpu.ram[p1_hp] = 3
            cycles = self.run_frame(inject_at=be, inject_fn=self._align_players)
            self.assertEqual(cycles, 19912,
                             f"frame {i} ran {cycles} cycles "
                             f"({cycles / 76:.0f} scanlines), expected 262")
            # The kernel for frame i just rendered this table: it must contain
            # no delta-0 entry (two entries on the same absolute row).
            tlen = self.cpu.ram[tblLen]
            raw = bytes(self.cpu.ram[evTbl:evTbl + tlen])
            prev = -1
            j = 0
            rows_seen = []
            while j < len(raw) and raw[j] != EV_TERMINATOR_DELTA:
                d = raw[j]
                row = prev + d
                rows_seen.append(row)
                if raw[j + 1] & EV_SINGLE_FLAG:
                    j += 3
                else:
                    j += 5
                prev = row
            self.assertEqual(len(rows_seen), len(set(rows_seen)),
                             f"frame {i}: duplicate absolute row in evTbl "
                             f"(delta 0 -> stretched object): {rows_seen}")

    def _align_players(self):
        """Force the 3-way same-row collision state at BuildEvents time."""
        ram = self.cpu.ram
        ram[self._ram("P0Y")] = 88
        ram[self._ram("P1Y")] = 88
        ram[self._ram("ball_y")] = 96
        ram[self._ram("m0_y")] = 88
        ram[self._ram("m1_y")] = 88
        ram[self._ram("m_active")] = 0x03   # both missiles flying

    def test_frame_stays_262_while_players_dead(self):
        # Round 5: the hit-effects pass (HP damage + fire lock) is branchy.
        # A dead player (no P0/P1 events, fire locked, no more hits taken) is
        # the OTHER heavy path through ProcessHitEffects, so frame timing must
        # hold there too: 19912 cycles = 262 scanlines with both players dead.
        p0_hp = self._ram("p0_hp")
        p1_hp = self._ram("p1_hp")
        self.cpu.inpt[4] = 0xFF      # boot sync frame first
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        self.cpu.ram[p0_hp] = 0      # kill both players up front
        self.cpu.ram[p1_hp] = 0
        for i in range(60):
            press = (i % 2 == 0)
            self.cpu.inpt[4] = 0x00 if press else 0xFF
            self.cpu.inpt[5] = 0x00 if press else 0xFF
            self.cpu.cxm0p = 0xC0    # hits keep landing on the dead players
            self.cpu.cxm1p = 0xC0
            cycles = self.run_frame()
            self.assertEqual(cycles, 19912,
                             f"frame {i} ran {cycles} cycles "
                             f"({cycles / 76:.0f} scanlines), expected 262")

    def test_vblank_never_overruns_with_realistic_branch_timing(self):
        # Regression: before Round 6, VBLANK_TIMER_VALUE=69.  The emulator
        # folded every branch as 2 cycles, so the timer expiry (~4553 cycles)
        # always landed after VBLANK work (~4400) and WaitVBlank exited on the
        # timer, keeping 262 scanlines.  On real hardware taken branches cost 3
        # cycles, pushing worst-case VBLANK work to ~4919 cycles -- past the
        # T=69 expiry -- so the poll exited at the variable work end and frames
        # drifted to 263/264/265 scanlines (visible shake).
        #
        # Round 6 raised the timer to T=77 (expiry ~5065, margin ~160) and
        # shrunk the kernel 192 -> 185 so VBLANK could grow 57 -> 64 lines.
        # The emulator's CYC table models taken branches and page crossings so
        # this worst case (both missiles + both collision latches + alternating
        # fire, HP re-filled to keep both missiles alive) must stay at exactly
        # 19912 cycles = 262 scanlines every frame.
        p0_hp = self._ram("p0_hp")
        p1_hp = self._ram("p1_hp")
        self.cpu.inpt[4] = 0xFF      # boot sync frames first
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        for _ in range(3):
            self.cpu.cxm0p = 0xC0
            self.cpu.cxm1p = 0xC0
            self.run_frame()
        for i in range(80):
            press = (i % 2 == 0)
            self.cpu.inpt[4] = 0x00 if press else 0xFF
            self.cpu.inpt[5] = 0x00 if press else 0xFF
            self.cpu.cxm0p = 0xC0    # M0 x P1 AND M0 x P0 latched
            self.cpu.cxm1p = 0xC0    # M1 x P0 AND M1 x P1 latched
            self.cpu.ram[p0_hp] = 3  # keep both players alive
            self.cpu.ram[p1_hp] = 3
            cycles = self.run_frame()
            self.assertEqual(cycles, 19912,
                             f"frame {i} ran {cycles} cycles "
                             f"({cycles / 76:.0f} scanlines), expected 262")


if __name__ == "__main__":
    unittest.main()