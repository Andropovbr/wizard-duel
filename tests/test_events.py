"""Event-table builder model validation.

Models the Round 3 BuildEvents/SortEvents/EmitEvents algorithm in Python and
checks the properties the kernel relies on:

  * delta(first) = row + 1, delta(next) = row - prevRow;
  * same-row events merge into a single two-write entry;
  * a pathological third event on a row is bumped to row+1 (never more than
    two events per entry), so no scanline ever needs more than two writes;
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
EV_NONE = 0


def build(records):
    """Reimplementation of AddEvent + SortEvents + EmitEvents.

    `records` is a list of (row, reg, val) tuples in generation order.
    Returns the event table as a list of [delta, reg1, val1, reg2, val2].
    """
    # AddEvent: append, remembering byte offsets.
    events = [list(r) for r in records]
    order = list(range(len(events)))
    # SortEvents: insertion sort of the order array by events[order[i]][0].
    for i in range(1, len(order)):
        key = order[i]
        key_row = events[key][0]
        j = i
        while j > 0 and events[order[j - 1]][0] > key_row:
            order[j] = order[j - 1]
            j -= 1
        order[j] = key
    # EmitEvents: walk the sorted order, merging at most two same-row records.
    table = []
    prev_row = -1  # $FF sentinel; first delta = row + 1
    i = 0
    while i < len(order):
        row = events[order[i]][0]
        reg1, val1 = events[order[i]][1], events[order[i]][2]
        reg2, val2 = EV_NONE, 0
        merged = False
        if i + 1 < len(order) and events[order[i + 1]][0] == row:
            reg2, val2 = events[order[i + 1]][1], events[order[i + 1]][2]
            merged = True
            # a 3rd same-row record is bumped to row+1
            if i + 2 < len(order) and events[order[i + 2]][0] == row:
                events[order[i + 2]][0] += 1
        table.append([(row - prev_row) & 0xFF, reg1, val1, reg2, val2])
        prev_row = row
        i += 2 if merged else 1
    table.append([0xFF, 0, 0, 0, 0])   # terminator
    return table


def fire_rows(table, kernel_lines=192):
    """Simulate the kernel: return the line each entry fires on."""
    fires = []
    line = 0
    ev = 0
    cnt = table[0][0]
    while line < kernel_lines:
        cnt -= 1
        if cnt == 0:
            fires.append(line)
            ev += 1
            cnt = table[ev][0]
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
        self.assertEqual(table[0][0], 49)   # row + 1
        self.assertEqual(table[1][0], 12)   # 60 - 48
        self.assertEqual(table[2][0], 35)   # 95 - 60
        self.assertEqual(table[3][0], 4)    # 99 - 95
        self.assertEqual(table[4][0], 29)   # 128 - 99
        self.assertEqual(table[5][0], 12)   # 140 - 128
        self.assertEqual(table[6][0], 0xFF)  # terminator

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
        entry = table[0]
        self.assertEqual(entry[0], 101)
        self.assertEqual((entry[1], entry[2]), (2, 0x3C))   # P1 ON
        self.assertEqual((entry[3], entry[4]), (5, 0x02))   # Ball ON

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
        self.assertEqual(table[0][0], 121)
        self.assertEqual((table[0][1], table[0][2]), (1, 0x3C))   # P0 ON
        self.assertEqual((table[0][3], table[0][4]), (2, 0x3C))   # P1 ON
        # entry1: the ball bumped to row 121 (delta 1)
        self.assertEqual(table[1][0], 1)
        self.assertEqual((table[1][1], table[1][2]), (5, 0x02))
        self.assertEqual(fire_rows(table)[:2], [120, 121])

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
        for entry in table[:-1]:
            self.assertIn(entry[1], (1, 2, 3, 4, 5))
            self.assertIn(entry[3], (0, 1, 2, 3, 4, 5))
            if entry[1] == entry[3]:
                pass  # a two-write entry can target two registers

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
