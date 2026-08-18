"""Event-table builder model validation.

Models the Round 3.1 BuildEvents/InsertEvent/ConvertDeltas algorithm in
Python and checks the properties the kernel relies on:

  * delta(first) = row + 1, delta(next) = row - prevRow;
  * same-row events merge into a single two-write entry;
  * a pathological third event on a row is bumped to row+1 (never more than
    two events per entry), so no scanline ever needs more than two writes;
  * the table is variable-size and never exceeds EV_TBL_SIZE (31) bytes;
  * the terminator entry has delta = EV_TERMINATOR_DELTA ($FF), which can
    never fire inside the 192-line kernel;
  * every event fires on exactly its row (the kernel fires an entry when its
    delta has counted down).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from test_timing import read_constants

EV_REG_GRP0, EV_REG_GRP1 = 1, 2
EV_REG_ENAM0, EV_REG_ENAM1, EV_REG_ENABL = 3, 4, 5
EV_SINGLE_FLAG = 0x80
EV_TERMINATOR_DELTA = 0xFF
EV_TBL_SIZE = 31


def entry_size(tbl, i):
    """Return the size (3 single / 5 double) of the entry at index i."""
    return 3 if tbl[i + 1] & EV_SINGLE_FLAG else 5


def insert(tbl, row, reg, val):
    """Reimplementation of InsertEvent.

    `tbl` is a byte list holding ABSOLUTE rows, starting as [terminator].
    Entries: single [row, reg|flag, val] (3 bytes), double [row, reg1, val1,
    reg2, val2] (5 bytes).  Same-row singles merge into a double; a third
    same-row event is bumped to row+1 and the scan continues.
    """
    i = 0
    while True:
        cur = tbl[i]
        if cur == EV_TERMINATOR_DELTA or cur > row:
            # insert a new single entry before this one
            tbl[i:i] = [row, reg | EV_SINGLE_FLAG, val]
            return
        if cur < row:
            i += entry_size(tbl, i)
            continue
        # cur == row
        if tbl[i + 1] & EV_SINGLE_FLAG:
            # single on the row: merge the new event as its second write,
            # converting it to a double
            tbl[i + 3:i + 3] = [reg, val]
            tbl[i + 1] &= ~EV_SINGLE_FLAG
            return
        # already a double on the row: bump the new event to row+1
        row += 1
        i += 5


def convert(tbl):
    """Reimplementation of ConvertDeltas: replace rows with kernel deltas."""
    prev = -1  # $FF sentinel; first delta = row + 1
    i = 0
    while tbl[i] != EV_TERMINATOR_DELTA:
        row = tbl[i]
        tbl[i] = (row - prev) & 0xFF
        prev = row
        i += entry_size(tbl, i)


def build(records):
    """Reimplementation of BuildEvents: insert all records, then convert.

    `records` is a list of (row, reg, val) tuples in generation order.
    Returns the event table as a byte list ending with the terminator.
    """
    tbl = [EV_TERMINATOR_DELTA]
    for row, reg, val in records:
        insert(tbl, row, reg, val)
    convert(tbl)
    return tbl


def entries(table):
    """Yield (row_delta, reg1, val1, reg2, val2) for each non-terminator."""
    i = 0
    while table[i] != EV_TERMINATOR_DELTA:
        d = table[i]
        reg1 = table[i + 1] & ~EV_SINGLE_FLAG
        val1 = table[i + 2]
        if table[i + 1] & EV_SINGLE_FLAG:
            yield (d, reg1, val1, 0, 0)
            i += 3
        else:
            yield (d, reg1, val1, table[i + 3], table[i + 4])
            i += 5


def fire_rows(table, kernel_lines=192):
    """Simulate the kernel: return the line each entry fires on."""
    fires = []
    line = 0
    i = 0
    cnt = table[0]
    while line < kernel_lines:
        cnt -= 1
        if cnt == 0:
            fires.append(line)
            i += entry_size(table, i)
            if i >= len(table):
                return fires
            cnt = table[i]
        line += 1
    return fires


class TestBuilderBasics(unittest.TestCase):
    def setUp(self):
        self.c = read_constants()

    def test_players_and_ball_deltas(self):
        table = build([
            (48, EV_REG_GRP0, 0x3C),   # P0 ON
            (60, EV_REG_GRP0, 0x00),   # P0 OFF
            (128, EV_REG_GRP1, 0x3C),  # P1 ON
            (140, EV_REG_GRP1, 0x00),  # P1 OFF
            (95, EV_REG_ENABL, 0x02),  # Ball ON
            (99, EV_REG_ENABL, 0x00),  # Ball OFF
        ])
        # Sorted rows: 48, 60, 95, 99, 128, 140.
        self.assertEqual(table[0], 49)      # row + 1
        self.assertEqual(table[3], 12)      # 60 - 48
        self.assertEqual(table[6], 35)      # 95 - 60
        self.assertEqual(table[9], 4)       # 99 - 95
        self.assertEqual(table[12], 29)     # 128 - 99
        self.assertEqual(table[15], 12)     # 140 - 128
        self.assertEqual(table[18], EV_TERMINATOR_DELTA)

    def test_events_fire_on_their_rows(self):
        rows = [48, 60, 95, 99, 128, 140]
        table = build([(r, EV_REG_GRP0, 0) for r in rows])
        self.assertEqual(fire_rows(table), rows)

    def test_same_row_events_merge(self):
        table = build([
            (100, EV_REG_GRP1, 0x3C),   # P1 ON
            (100, EV_REG_ENABL, 0x02),  # Ball ON (same row)
            (104, EV_REG_ENABL, 0x00),
        ])
        # entry0 is a double: delta 101, P1 ON then Ball ON
        self.assertEqual(table[0], 101)
        self.assertEqual((table[1], table[2]), (2, 0x3C))   # P1 ON
        self.assertEqual((table[3], table[4]), (5, 0x02))   # Ball ON
        # entry1 (single): delta 4 = 104 - 100
        self.assertEqual(table[5], 4)
        self.assertEqual(table[6] & ~EV_SINGLE_FLAG, EV_REG_ENABL)
        self.assertEqual(fire_rows(table), [100, 104])

    def test_three_way_collision_bumps_third_event(self):
        # P0 ON, P1 ON and Ball ON on the same row: only two fit in one entry,
        # the third is bumped to row+1.
        table = build([
            (120, EV_REG_GRP0, 0x3C),
            (120, EV_REG_GRP1, 0x3C),
            (120, EV_REG_ENABL, 0x02),
            (132, EV_REG_GRP0, 0x00),
        ])
        # entry0: the two players on row 120 (delta 121), in generation order
        self.assertEqual(table[0], 121)
        self.assertEqual((table[1], table[2]), (1, 0x3C))   # P0 ON
        self.assertEqual((table[3], table[4]), (2, 0x3C))   # P1 ON
        # entry1: the ball bumped to row 121 (delta 1)
        self.assertEqual(table[5], 1)
        self.assertEqual((table[6] & ~EV_SINGLE_FLAG, table[7]), (5, 0x02))
        self.assertEqual(fire_rows(table), [120, 121, 132])

    def test_table_never_exceeds_max_size(self):
        # Worst case (all singles on distinct rows) is 10 * 3 + 1 = 31 bytes;
        # every merge shrinks the table, so EV_TBL_SIZE is a hard bound even
        # with pathological inputs.
        regs = [EV_REG_GRP0, EV_REG_GRP1, EV_REG_ENAM0, EV_REG_ENAM1,
                EV_REG_ENABL]
        worst = build([(r * 2, regs[r % 5], r) for r in range(1, 11)])
        self.assertLessEqual(len(worst), EV_TBL_SIZE)
        # and any single row piling up: all merges + bumps, still within bounds
        collision = build([(120, regs[r % 5], r) for r in range(1, 11)])
        self.assertLessEqual(len(collision), EV_TBL_SIZE)
        # row bumps must keep rows sorted (deltas stay positive)
        deltas = [e[0] for e in entries(collision)]
        self.assertTrue(all(d > 0 for d in deltas))

    def test_every_entry_at_most_two_writes(self):
        # Even with every object on the same row, no entry may hold three
        # writes: that would break the 76-cycle kernel budget.
        table = build([
            (120, EV_REG_GRP0, 0x3C),
            (120, EV_REG_GRP1, 0x3C),
            (120, EV_REG_ENAM0, 0x02),
            (120, EV_REG_ENAM1, 0x02),
            (120, EV_REG_ENABL, 0x02),
            (124, EV_REG_GRP0, 0x00),
            (124, EV_REG_GRP1, 0x00),
            (124, EV_REG_ENAM0, 0x00),
            (124, EV_REG_ENAM1, 0x00),
            (124, EV_REG_ENABL, 0x00),
        ])
        for d, reg1, val1, reg2, val2 in entries(table):
            self.assertIn(reg1, (1, 2, 3, 4, 5))
            self.assertIn(reg2, (0, 1, 2, 3, 4, 5))
            self.assertEqual(reg1 & EV_SINGLE_FLAG, 0)
            self.assertEqual(reg2 & EV_SINGLE_FLAG, 0)
        # every event fires exactly once (no event is dropped by a bump):
        # 5 events on row 120 + 5 on row 124 = 10 writes across the entries
        writes = 0
        for d, reg1, val1, reg2, val2 in entries(table):
            writes += 1 if reg2 == 0 else 2
        self.assertEqual(writes, 10)
        # merged entries fire on sorted rows, never more than one entry/line
        fires = fire_rows(table)
        self.assertEqual(len(fires), len(list(entries(table))))
        self.assertEqual(sorted(fires), fires)

    def test_terminator_never_fires(self):
        rows = [0, 40, 90, 191]
        table = build([(r, EV_REG_GRP0, 0) for r in rows])
        fires = fire_rows(table)
        self.assertEqual(len(fires), len(rows))   # terminator never fires
        self.assertEqual(fires[-1], 191)

    def test_event_firing_line_math(self):
        # With a single event at row R, delta = R+1 fires on line R.
        for row in (0, 1, 50, 191):
            table = build([(row, EV_REG_GRP0, 0)])
            self.assertEqual(fire_rows(table), [row])


if __name__ == "__main__":
    unittest.main()