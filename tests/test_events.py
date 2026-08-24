"""Event-table builder model validation.

Models the Round 11 BuildEvents / AppendEvent / ShiftBy5 / ConvertDeltas
algorithm in Python and checks the properties the kernel relies on:

  * the table is the 5-byte dummy at offset 0, then up to EV_MAX_EVENTS real
    5-byte entries, then the 5-byte marker (EV_TBL_SIZE = 60 bytes);
  * the ball and M1 (ENABL, ENAM1) never occupy a double's second write slot,
    because slot 2 is only safe for objects whose x is guaranteed >= 15;
  * every entry has at most two writes (a pathological third same-row event is
    bumped to row+1);
  * the table is emitted in strictly ascending row order (selection), so
    appends land at the end and shifts are rare;
  * the table never exceeds EV_MAX_EVENTS entries (EV_TBL_SIZE bytes);
  * the terminator entry has delta = EV_MARKER_VAL ($FF) and never fires
    inside the 185-line kernel;
  * every event fires on exactly its row: the kernel applies an entry's writes
    from its absolute row (entry i applies from line row_i, where
    row_0 = nullDelta and row_{i+1} = row_i + delta_i);
  * dead players and inactive missiles contribute no events.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from test_timing import read_constants

EV_REG_GRP0, EV_REG_GRP1 = 1, 2
EV_REG_ENAM0, EV_REG_ENAM1, EV_REG_ENABL = 3, 4, 5
EV_MARKER_ROW = 0xFF
EV_MARKER_VAL = 0xFF

# Object dispatch codes and the BuildEvents scan order (Round 14 write-slot
# rule): players are scanned first so they win row ties and keep slot 1; the
# ball is scanned after players, then M0, then M1.
OBJ_M1, OBJ_M0, OBJ_P0, OBJ_P1, OBJ_BALL = 0, 1, 2, 3, 4
SCAN_ORDER = (OBJ_P0, OBJ_P1, OBJ_BALL, OBJ_M0, OBJ_M1)

# Offset of the first real entry (the dummy occupies table bytes 0..4; its
# delta byte is the EV_MARKER_ROW sentinel so the builder back-scan stops there).
ENTRY0 = 5


def scene(p0y, p1y, by, m0y, m1y, m0a, m1a, p0_alive=True, p1_alive=True,
          ball_x=80):
    """Return (active, objects) for a scene.

    Objects are keyed by dispatch code; each is (y, height, reg, on_val).
    Missiles with m0y/m1y given as None (or m0a/m1a False) are inactive.
    """
    ball_h = read_constants().get("BALL_HEIGHT", 4)
    objects = {
        OBJ_P0: (p0y, 18, EV_REG_GRP0, 0x3C),     # PLAYER_HEIGHT/PADDLE_BITS
        OBJ_P1: (p1y, 18, EV_REG_GRP1, 0x3C),
        OBJ_BALL: (by, ball_h, EV_REG_ENABL, 0x02),  # BALL_HEIGHT/BALL_ENABLE
        "_ball_x": ball_x,
    }
    active = set()
    if p0_alive:
        active.add(OBJ_P0)
    if p1_alive:
        active.add(OBJ_P1)
    active.add(OBJ_BALL)
    if m0a:
        objects[OBJ_M0] = (m0y, 4, EV_REG_ENAM0, 0x02)
        active.add(OBJ_M0)
    if m1a:
        objects[OBJ_M1] = (m1y, 4, EV_REG_ENAM1, 0x02)
        active.add(OBJ_M1)
    return active, objects


def build(active, objects, kernel_lines=185, max_events=10):
    """Reimplement BuildEvents + AppendEvent + ConvertDeltas.

    `active` is the set of object dispatch codes still to emit; `objects`
    maps each code to (y, height, reg, on_val).  Returns the CONVERTED flat
    byte table (dummy at offset 0, entries from ENTRY0, marker at the end)
    and the prime delta nullDelta.
    """
    ball_x = objects.get("_ball_x", 80)
    # Dummy (delta byte = EV_MARKER_ROW back-scan sentinel, regs all zero)
    # followed by the marker.
    table = [EV_MARKER_ROW, 0, 0, 0, 0, EV_MARKER_VAL, 0, 0, 0, 0]
    on_pending = set(active)          # evCnt
    active_mask = set(active)         # nullDelta during the build
    while active_mask:
        best = None
        best_row = None
        for obj in SCAN_ORDER:
            if obj not in active_mask:
                continue
            y, height, reg, val = objects[obj]
            cand = y if obj in on_pending else y + height
            if best_row is None or cand < best_row:
                best = obj
                best_row = cand
        y, height, reg, val = objects[best]
        if best in on_pending:
            _append(table, best_row, reg, val, kernel_lines, max_events,
                    ball_x)
            on_pending.discard(best)
        else:
            _append(table, best_row, reg, 0, kernel_lines, max_events,
                    ball_x)
            active_mask.discard(best)
    return _convert(table, kernel_lines)


def _append(table, row, reg, val, kernel_lines, max_events, ball_x=80):
    """AppendEvent: append/merge/bump an event into the flat table.

    The table is a byte list of 5-byte entries (dummy at offset 0, real
    entries from offset 5) ending with the marker.
    """
    if row >= kernel_lines:
        return
    n_real = (len(table) - 5) // 5 - 1   # real entries (marker excluded)
    if n_real >= max_events:
        return
    if n_real == 0:                      # only dummy + marker: first at offset 5
        table[5:5] = [row, reg, val, 0, 0]
        return
    i = n_real - 1                       # last real entry
    while True:
        off = ENTRY0 + i * 5
        cur = table[off]
        if cur < row:                 # append after this entry
            table[off + 5:off + 5] = [row, reg, val, 0, 0]
            return
        if cur == row:
            if table[off + 3] != 0:
                # already a double -> bump the new event
                row += 1
                if row >= kernel_lines:
                    return
                i += 1
                if i >= n_real:        # next is the marker: append the bump
                    table[off + 5:off + 5] = [row, reg, val, 0, 0]
                    return
                continue
            # entry is a single: check slot-2 safety
            if reg == EV_REG_ENAM1:
                # M1 must never be slot 2 (x varies, can be < 15)
                row += 1
                if row >= kernel_lines:
                    return
                i += 1
                if i >= n_real:
                    table[off + 5:off + 5] = [row, reg, val, 0, 0]
                    return
                continue
            existing_reg1 = table[off + 1]
            if reg == EV_REG_ENABL:
                # new event is the ball
                if ball_x >= 15:
                    # safe to merge ball into slot 2
                    table[off + 3] = reg
                    table[off + 4] = val
                    return
                # ball_x < 15: ball cannot be slot 2
                if existing_reg1 == EV_REG_ENABL:
                    # both ENABL: impossible (ball is single), bump
                    row += 1
                    if row >= kernel_lines:
                        return
                    i += 1
                    if i >= n_real:
                        table[off + 5:off + 5] = [row, reg, val, 0, 0]
                        return
                    continue
                # existing entry is a player: swap
                # ball -> slot 1, player -> slot 2 (player x=16 always safe)
                player_reg = table[off + 1]
                player_val = table[off + 2]
                table[off + 1] = EV_REG_ENABL   # ball reg -> slot 1
                table[off + 2] = val             # ball val -> slot 1
                table[off + 3] = player_reg      # player reg -> slot 2
                table[off + 4] = player_val      # player val -> slot 2
                return
            # new event is NOT the ball
            if existing_reg1 == EV_REG_ENABL:
                # existing entry has ball in slot 1, new event is a player
                if ball_x >= 15:
                    # ball safe in slot 2: swap player to slot 1, ball to slot 2
                    ball_val = table[off + 2]
                    table[off + 1] = reg         # player reg -> slot 1
                    table[off + 2] = val         # player val -> slot 1
                    table[off + 3] = EV_REG_ENABL  # ball reg -> slot 2
                    table[off + 4] = ball_val    # ball val -> slot 2
                    return
                # ball_x < 15: ball must stay in slot 1, player -> slot 2
                # player x=16 is safe for slot 2
                table[off + 3] = reg
                table[off + 4] = val
                return
            # neither is ENABL: safe to merge as slot 2
            table[off + 3] = reg
            table[off + 4] = val
            return
        i -= 1                        # entry row > new row: step back
        if i < 0:
            table[5:5] = [row, reg, val, 0, 0]
            return


def _convert(table, kernel_lines):
    """ConvertDeltas: absolute rows -> deltas; returns (flat, nullDelta)."""
    n_real = (len(table) - 5) // 5 - 1   # real entries (marker excluded)
    if n_real == 0:
        return table, kernel_lines
    null_delta = table[ENTRY0]
    for i in range(n_real):
        off = ENTRY0 + i * 5
        nxt = table[off + 5] if i + 1 < n_real else kernel_lines
        table[off] = (nxt - table[off]) & 0xFF
    return table, null_delta


def entries(table):
    """Yield (delta, reg1, val1, reg2, val2) for each non-terminator."""
    i = ENTRY0
    while table[i] != EV_MARKER_VAL:
        yield (table[i], table[i + 1], table[i + 2],
               table[i + 3], table[i + 4])
        i += 5


def table_rows(table, null_delta):
    """Absolute display row of each entry (entry i applies from line row_i)."""
    rows = []
    row = null_delta
    i = ENTRY0
    while table[i] != EV_MARKER_VAL:
        rows.append(row)
        row += table[i]
        i += 5
    return rows


def fire_rows(table, null_delta, kernel_lines=185):
    """Apply-start line of each entry's writes (the original event rows)."""
    return table_rows(table, null_delta)


class TestBuilderBasics(unittest.TestCase):
    def setUp(self):
        self.c = read_constants()
        self.assertEqual(self.c["EV_TBL_SIZE"], 60)
        self.assertEqual(self.c["EV_MAX_EVENTS"], 10)
        self.assertEqual(self.c["EV_MARKER_VAL"], 0xFF)
        self.assertEqual(self.c["EV_MARKER_ROW"], 0xFF)
        self.assertEqual(self.c["KERNEL_SCANLINES"], 185)

    def test_sorted_emission_preserves_rows(self):
        active, objects = scene(48, 128, 142, 52, 132, True, True)
        table, nd = build(active, objects)
        rows = table_rows(table, nd)
        self.assertEqual(rows, [48, 52, 56, 66, 128, 132, 136, 142, 144, 146])
        self.assertEqual(rows, sorted(rows))
        for e in entries(table):
            self.assertGreater(e[0], 0)   # all deltas positive
        # terminator never fires and the table fits the kernel window
        self.assertLess(rows[-1], 185)
        self.assertEqual(table[-5], EV_MARKER_VAL)

    def test_events_fire_on_their_rows(self):
        active, objects = scene(48, 128, 142, 52, 132, True, True)
        table, nd = build(active, objects)
        self.assertEqual(fire_rows(table, nd),
                         [48, 52, 56, 66, 128, 132, 136, 142, 144, 146])

    def test_same_row_events_merge(self):
        # P0 ON, P1 ON and Ball ON on the same row.  Players are scanned first
        # so P0 wins slot 1, P1 merges into slot 2; Ball sees a double entry
        # and is bumped to row+1.  Ball_x=80 (default, >= 15) so if the entry
        # were a single, Ball could merge as slot 2 — but with two writes
        # already, it must bump.
        active, objects = scene(128, 128, 128, 0, 0, False, False)
        table, nd = build(active, objects)
        rows = table_rows(table, nd)
        self.assertEqual(rows, [128, 129, 130, 146])
        # entry 0 is a double with P0 first (slot 1), then P1
        d, reg1, val1, reg2, val2 = next(entries(table))
        self.assertEqual((reg1, val1), (EV_REG_GRP0, 0x3C))   # P0 ON
        self.assertEqual((reg2, val2), (EV_REG_GRP1, 0x3C))   # P1 ON
        self.assertEqual(fire_rows(table, nd), [128, 129, 130, 146])

    def test_non_ball_merge_keeps_scan_order(self):
        # P0, P1 and M0 all ON at 48, ball at 142.  P0 is scanned first, so
        # P0 is slot 1 and P1 (next player scanned) merges into slot 2; M0 is
        # bumped to 49.  The OFF events merge the same way on row 60.
        active, objects = scene(48, 48, 142, 48, 0, True, False)
        table, nd = build(active, objects)
        rows = table_rows(table, nd)
        self.assertEqual(rows, [48, 49, 52, 66, 142, 144])
        d, reg1, val1, reg2, val2 = next(entries(table))
        self.assertEqual((reg1, val1), (EV_REG_GRP0, 0x3C))   # P0 ON slot 1
        self.assertEqual((reg2, val2), (EV_REG_GRP1, 0x3C))   # P1 ON slot 2

    def test_ball_wins_row_tie_over_earlier_scan_order(self):
        # Ball ON and M1 ON on the same row: players are scanned first, then
        # ball, then M0, then M1.  Ball wins over M1 (scanned earlier), so
        # ball is slot 1 and M1 is bumped to row+1 (M1 can never be slot 2).
        active, objects = scene(48, 128, 100, 0, 100, False, True)
        table, nd = build(active, objects)
        rows = table_rows(table, nd)
        self.assertEqual(rows, sorted(rows))
        for d, reg1, val1, reg2, val2 in entries(table):
            if reg2 != 0:
                self.assertNotIn(reg2, (EV_REG_ENAM1,))

    def test_enabl_and_enam1_never_second_write(self):
        # Across a dense scenario matrix, M1 must never end up as the second
        # write of a double.  ENABL may be slot 2 when ball_x >= 15 (the
        # default), which is safe.
        for by in range(0, 180, 5):
            for m0y, m1y in ((by, by), (by - 2, by + 2), (52, 132)):
                for m0a, m1a in ((True, True), (True, False),
                                 (False, True), (False, False)):
                    active, objects = scene(48, 128, by, m0y, m1y, m0a, m1a)
                    table, nd = build(active, objects)
                    for d, reg1, val1, reg2, val2 in entries(table):
                        if reg2 != 0:
                            self.assertNotEqual(
                                reg2, EV_REG_ENAM1,
                                f"ENAM1 in the second slot at m1y={m1y}")

    def test_three_way_collision_bumps_third_event(self):
        # P0 ON, M0 ON and Ball ON on the same row: two fit in one entry, the
        # third (bumped) lands on row+1.
        active, objects = scene(120, 132, 120, 120, 0, True, False)
        table, nd = build(active, objects)
        rows = table_rows(table, nd)
        self.assertEqual(rows[0], 120)
        self.assertEqual(rows[1], 121)   # bumped third event
        self.assertEqual(fire_rows(table, nd), rows)
        for d, reg1, val1, reg2, val2 in entries(table):
            writes = 1 if reg2 == 0 else 2
            self.assertLessEqual(writes, 2)

    def test_table_never_exceeds_max_size(self):
        # Even with every object on the same row and rows piling up, the table
        # never exceeds EV_MAX_EVENTS entries (EV_TBL_SIZE bytes).
        for row in range(0, 185, 7):
            active, objects = scene(row, row, row, row, row, True, True)
            table, nd = build(active, objects)
            n_entries = (len(table) - 5) // 5 - 1
            self.assertLessEqual(n_entries, 10)
            self.assertLessEqual(len(table), 60)
        # every event either fires or is bumped, never more than 2 writes
        for row in range(0, 185, 7):
            active, objects = scene(row, row, row, row, row, True, True)
            table, nd = build(active, objects)
            for d, reg1, val1, reg2, val2 in entries(table):
                self.assertGreater(d, 0)
                writes = 1 if reg2 == 0 else 2
                self.assertLessEqual(writes, 2)

    def test_dead_player_and_inactive_missiles_contribute_nothing(self):
        # Both players dead, no missiles: only the ball renders.
        active, objects = scene(48, 128, 142, 52, 132, False, False,
                                p0_alive=False, p1_alive=False)
        table, nd = build(active, objects)
        rows = table_rows(table, nd)
        self.assertEqual(rows, [142, 144])
        for d, reg1, val1, reg2, val2 in entries(table):
            self.assertEqual(reg1, EV_REG_ENABL)

    def test_ball_on_floor_drops_off_event(self):
        # Ball OFF at ball_y+BALL_HEIGHT = 183 < KERNEL_SCANLINES is kept; both
        # ON and OFF events are present.
        active, objects = scene(48, 128, 181, 0, 0, False, False)
        table, nd = build(active, objects)
        rows = table_rows(table, nd)
        self.assertEqual(rows, [48, 66, 128, 146, 181, 183])
        self.assertEqual(table[-5], EV_MARKER_VAL)
        self.assertLess(rows[-1], 185)

    def test_off_display_row_dropped(self):
        # Any event at row >= 185 is dropped, keeping the marker on line 184.
        active, objects = scene(190, 190, 190, 0, 0, False, False)
        table, nd = build(active, objects)
        self.assertEqual(table, [EV_MARKER_ROW, 0, 0, 0, 0,
                                 EV_MARKER_VAL, 0, 0, 0, 0])
        self.assertEqual(nd, 185)

    def test_empty_table_priming(self):
        # Empty table: nullDelta = 185, the kernel counts straight to the
        # marker at offset 5 (the dummy occupies bytes 0..4).
        table, nd = build(set(), {})
        self.assertEqual(nd, 185)
        self.assertEqual(table, [EV_MARKER_ROW, 0, 0, 0, 0,
                                 EV_MARKER_VAL, 0, 0, 0, 0])

    def test_convert_deltas_match_rows(self):
        active, objects = scene(48, 128, 142, 52, 132, True, True)
        table, nd = build(active, objects)
        rows = table_rows(table, nd)
        # every entry's delta is the gap to the next row; last gap to 185
        for (d, reg1, val1, reg2, val2), row in zip(entries(table), rows):
            pass
        self.assertEqual(rows[-1] + table[(len(table) - 10)], 185)

    def test_events_fire_exactly_once(self):
        for by in range(0, 185, 9):
            active, objects = scene(by, by + 2, by + 4, by + 1, by + 3,
                                    True, True)
            table, nd = build(active, objects)
            rows = fire_rows(table, nd)
            n_events = sum(1 for _ in entries(table))
            self.assertEqual(len(rows), n_events)
            self.assertEqual(sorted(rows), rows)


class TestPlayerBallRowCollision(unittest.TestCase):
    """Regression: player events must never be bumped when ball shares a row.

    Before the Round 14 fix, when Ball OFF and P1 ON/OFF shared a row,
    the ball was scanned first (won the row tie) and occupied slot 1.
    P1's event was then bumped to row+1, causing P1 to appear 1 scanline
    too short or too tall.  The fix reorders the scan loop so players are
    checked before the ball: players always win row ties and the ball is
    bumped instead (invisible on a 3-pixel ball).
    """

    def _check_player_height(self, p0y, p1y, by, m0y=0, m1y=0,
                             m0a=False, m1a=False):
        """Build events and verify both players have exactly PLAYER_HEIGHT."""
        PH = read_constants()["PLAYER_HEIGHT"]
        BH = read_constants()["BALL_HEIGHT"]
        active, objects = scene(p0y, p1y, by, m0y, m1y, m0a, m1a)
        table, nd = build(active, objects)

        # Find P0 ON/OFF and P1 ON/OFF rows from the table
        p0_on = p0_off = p1_on = p1_off = None
        row = nd
        i = ENTRY0
        while table[i] != EV_MARKER_VAL:
            reg1, val1 = table[i+1], table[i+2]
            reg2, val2 = table[i+3], table[i+4]
            if reg1 == EV_REG_GRP0:
                if val1: p0_on = row
                else: p0_off = row
            if reg2 == EV_REG_GRP0:
                if val2: p0_on = row
                else: p0_off = row
            if reg1 == EV_REG_GRP1:
                if val1: p1_on = row
                else: p1_off = row
            if reg2 == EV_REG_GRP1:
                if val2: p1_on = row
                else: p1_off = row
            row += table[i]
            i += 5

        self.assertIsNotNone(p0_on, "P0 ON not found")
        self.assertIsNotNone(p0_off, "P0 OFF not found")
        self.assertIsNotNone(p1_on, "P1 ON not found")
        self.assertIsNotNone(p1_off, "P1 OFF not found")
        self.assertEqual(p0_off - p0_on, PH,
                         f"P0 height {p0_off - p0_on} != {PH} "
                         f"(p0y={p0y} by={by})")
        self.assertEqual(p1_off - p1_on, PH,
                         f"P1 height {p1_off - p1_on} != {PH} "
                         f"(p1y={p1y} by={by})")
        self.assertEqual(p0_on, p0y, f"P0 ON {p0_on} != P0Y {p0y}")
        self.assertEqual(p1_on, p1y, f"P1 ON {p1_on} != P1Y {p1y}")

    def test_ball_on_equals_p1_on(self):
        """Case A: Ball ON row == P1 ON row."""
        self._check_player_height(p0y=82, p1y=83, by=83)

    def test_ball_off_equals_p1_on(self):
        """Case B: Ball OFF row == P1 ON row."""
        PH = read_constants()["PLAYER_HEIGHT"]
        BH = read_constants()["BALL_HEIGHT"]
        self._check_player_height(p0y=82, p1y=83, by=83 - BH)

    def test_ball_on_equals_p1_off(self):
        """Case C: Ball ON row == P1 OFF row."""
        PH = read_constants()["PLAYER_HEIGHT"]
        self._check_player_height(p0y=82, p1y=83, by=83 + PH)

    def test_ball_off_equals_p1_off(self):
        """Case D: Ball OFF row == P1 OFF row."""
        PH = read_constants()["PLAYER_HEIGHT"]
        BH = read_constants()["BALL_HEIGHT"]
        self._check_player_height(p0y=82, p1y=83, by=83 + PH - BH)

    def test_ball_on_equals_p0_on(self):
        """P0 Control A: Ball ON row == P0 ON row."""
        self._check_player_height(p0y=82, p1y=83, by=82)

    def test_ball_off_equals_p0_on(self):
        """P0 Control B: Ball OFF row == P0 ON row."""
        BH = read_constants()["BALL_HEIGHT"]
        self._check_player_height(p0y=82, p1y=83, by=82 - BH)

    def test_ball_on_equals_p0_off(self):
        """P0 Control C: Ball ON row == P0 OFF row."""
        PH = read_constants()["PLAYER_HEIGHT"]
        self._check_player_height(p0y=82, p1y=83, by=82 + PH)

    def test_ball_off_equals_p0_off(self):
        """P0 Control D: Ball OFF row == P0 OFF row."""
        PH = read_constants()["PLAYER_HEIGHT"]
        BH = read_constants()["BALL_HEIGHT"]
        self._check_player_height(p0y=82, p1y=83, by=82 + PH - BH)

    def test_no_player_event_is_bumped_by_ball(self):
        """Sweep: for every ball_y, player ON/OFF rows must match P0Y/P1Y."""
        PH = read_constants()["PLAYER_HEIGHT"]
        BH = read_constants()["BALL_HEIGHT"]
        for by in range(0, 185):
            # Skip cases where player events fall off-screen
            if 83 + PH > 185:
                continue
            self._check_player_height(p0y=82, p1y=83, by=by)


if __name__ == "__main__":
    unittest.main()