"""Shared helpers for the Wizard Duel toolchain.

Everything is cross-platform (Python 3.8+) and never assumes Bash-only
utilities.  The public entry points are:

    python tools/build.py
    python tools/run.py
    python tools/test.py
    python tools/benchmark.py
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
BUILD_DIR = ROOT / "build"
TESTS_DIR = ROOT / "tests"
DOCS_DIR = ROOT / "docs"
ROM_NAME = "wizard-duel"

ROM_PATH = BUILD_DIR / f"{ROM_NAME}.bin"
LST_PATH = BUILD_DIR / f"{ROM_NAME}.lst"
SYM_PATH = BUILD_DIR / f"{ROM_NAME}.sym"

ROM_LIMIT = 4096          # bytes (4 KiB, no bankswitching)
RAM_LIMIT = 128           # bytes (RIOT RAM $80-$FF)
ROM_ORIGIN = 0xF000
ROM_END = 0xFFFF
RAM_ORIGIN = 0x80
RAM_END = 0xFF
VECTOR_RESET = 0xFFFC
VECTOR_BLOCK = 0xFFFA       # first byte of the 6502 vector block


def probe_dasm(path):
    """Deterministically verify that `path` is a functional DASM executable.

    DASM has no --version/-h option: invoking `dasm --version` makes DASM try
    to open a file named "--version", print a warning and exit 0, so it is a
    false positive.  With no arguments DASM prints its short help text
    (documented behavior) and exits non-zero, which is a reliable probe.
    """
    try:
        result = subprocess.run([path], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not execute dasm: {exc}"
    out = (result.stdout or "") + (result.stderr or "")
    if "Usage: dasm" in out or "DASM" in out:
        return True, "ok"
    return False, f"did not behave like DASM (output: {out.strip()[:200]})"


def probe_stella(path):
    """Deterministically verify that `path` is a functional Stella executable.

    Stella supports a real `-help` option that works without a video device.
    """
    try:
        result = subprocess.run([path, "-help"], capture_output=True, text=True,
                                timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not execute stella: {exc}"
    out = (result.stdout or "") + (result.stderr or "")
    if "Stella" in out and "Usage: stella" in out:
        return True, "ok"
    return False, f"did not behave like Stella (output: {out.strip()[:200]})"


def tool(name, what, probe=None):
    """Return the absolute path to a required executable or exit cleanly.

    `probe(executable)` is an optional deterministic functional check that
    must return (ok: bool, message: str).  Presence in PATH alone is not
    enough; the tool must actually work.
    """
    path = shutil.which(name)
    if path is None:
        print(f"ERROR: {name.upper()} was not found.\n", file=sys.stderr)
        print(f"Install {name.upper()} and ensure the `{name}` executable is "
              f"available in PATH.\n", file=sys.stderr)
        print(f"Required for:\n  {what}\n", file=sys.stderr)
        sys.exit(2)
    if probe is not None:
        ok, message = probe(path)
        if not ok:
            print(f"ERROR: {name.upper()} failed verification.\n",
                  file=sys.stderr)
            print(f"{message}\n", file=sys.stderr)
            print(f"Install a working {name.upper()} and try again.\n",
                  file=sys.stderr)
            print(f"Required for:\n  {what}\n", file=sys.stderr)
            sys.exit(2)
    return path


def run(cmd, **kwargs):
    """Run a command and return a CompletedProcess with text output."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def stella_rominfo(rom_path, stella_bin=None):
    """Run `stella -rominfo <rom>` and return the CompletedProcess.

    NOTE: unlike `stella -help`, `-rominfo` initializes SDL and therefore
    requires a video device.  On headless Linux (e.g. CI) this transparently
    retries through `xvfb-run -a` when that helper is installed.
    """
    stella_bin = stella_bin or tool("stella", "ROM metadata validation")
    cmd = [stella_bin, "-rominfo", str(rom_path)]
    result = run(cmd)
    if (result.returncode != 0 and os.name == "posix"
            and not os.environ.get("DISPLAY") and shutil.which("xvfb-run")):
        result = run(["xvfb-run", "-a"] + cmd)
    return result


def parse_symbols(sym_path=SYM_PATH):
    """Parse a DASM symbol file into {name: address}."""
    symbols = {}
    if not sym_path.exists():
        return symbols
    for line in sym_path.read_text().splitlines():
        # DASM .sym format: "symbol  address  (segment)"
        parts = line.split()
        if len(parts) >= 2:
            try:
                symbols[parts[0]] = int(parts[1], 16)
            except ValueError:
                continue
    return symbols


def parse_listing(lst_path=LST_PATH):
    """Parse a DASM listing into a list of emitted (address, bytes) rows.

    Returns a list of dicts with 'addr' (int or None) and 'bytes' (bytes
    object or None).  Lines that emit no data are skipped.
    """
    rows = []
    if not lst_path.exists():
        return rows
    for line in lst_path.read_text().splitlines():
        # Format: <src> <addr> <hex bytes> <mnemonic> ...
        m = re.match(r"^\s*\d+\s+([0-9a-f]{4})\s+((?:[0-9a-f]{2}\s)*)\s+(\S+)", line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        hexs = m.group(2).strip()
        if not hexs:
            continue
        try:
            data = bytes(int(h, 16) for h in hexs.split())
        except ValueError:
            continue
        rows.append({"addr": addr, "bytes": data})
    return rows


def _resolve_constant_expr(expr, consts):
    """Resolve a numeric DS-size expression to an int, or None.

    Handles decimal/$hex/%binary literals, identifiers resolved against
    `consts`, and the + - * / operators with standard precedence (the only
    constructs used by the DS directives and constants.inc).
    """
    expr = expr.strip()
    if not expr:
        return None

    def atom(tok):
        if tok.startswith("$"):
            return int(tok[1:], 16)
        if tok.startswith("%"):
            return int(tok[1:], 2)
        if re.fullmatch(r"\d+", tok):
            return int(tok, 10)
        return consts.get(tok)

    tokens = re.findall(r"\$[0-9a-fA-F]+|%[01]+|\d+|[A-Za-z_]\w*|[()+*/-]", expr)
    if not tokens:
        return None
    # Convert to [value, op, value, op, ...] via a shunting-yard evaluation.
    # Only + - * / and parentheses appear; handle with two precedence levels.
    ops = {"+": lambda a, b: a + b,
           "-": lambda a, b: a - b,
           "*": lambda a, b: a * b,
           "/": lambda a, b: a // b}
    precedence = {"+": 1, "-": 1, "*": 2, "/": 2}
    values = []
    opstack = []

    def apply_op():
        op = opstack.pop()
        b = values.pop()
        a = values.pop()
        values.append(ops[op](a, b))

    for tok in tokens:
        if tok == "(":
            opstack.append(tok)
        elif tok == ")":
            while opstack and opstack[-1] != "(":
                apply_op()
            if not opstack or opstack.pop() != "(":
                return None
        elif tok in ops:
            while (opstack and opstack[-1] != "("
                   and precedence[opstack[-1]] >= precedence[tok]):
                apply_op()
            opstack.append(tok)
        else:
            v = atom(tok)
            if v is None:
                return None
            values.append(v)
    while opstack:
        if opstack[-1] == "(":
            return None
        apply_op()
    return values[0] if len(values) == 1 else None


def ram_usage(symbols=None):
    """Return (used_bytes, available_bytes) for RIOT RAM.

    Usage is derived from the DS (define storage) directives in the listing
    VARS segment.  Counting every symbol whose value falls in $80-$FF is not
    valid because many EQU constants have such values.  DS sizes may be
    symbolic (e.g. ``DS EV_TBL_SIZE``), which are resolved against the EQU
    constants in constants.inc.
    """
    used = 0
    if lst_path := LST_PATH:
        consts = {}
        for line in (SRC_DIR / "constants.inc").read_text().splitlines():
            m = re.match(r"^\s*(\w+)\s*=\s*([^;]+)", line)
            if m and re.fullmatch(r"[A-Za-z_]\w*", m.group(1)):
                value = _resolve_constant_expr(m.group(2), consts)
                if value is not None:
                    consts[m.group(1)] = value
        for line in LST_PATH.read_text().splitlines():
            # Symbolic sizes render as "00 00 00 00*<name> DS <expr>"; the
            # expression may span multiple tokens (e.g. "EV_MAX_EVENTS * 3"),
            # so capture everything up to the trailing ';' comment.
            m = re.match(
                r"^\s*\d+\s+U([0-9a-f]{4})\s+[0-9a-f]{2}(?:\s+[0-9a-f]{2})*\*?\s+\S+\s+DS\s+([^;]+)",
                line)
            if not m:
                m = re.match(
                    r"^\s*\d+\s+U([0-9a-f]{4})\s+[0-9a-f]{2}\s+\S+\s+DS\s+(\d+)",
                    line)
            if not m:
                continue
            addr = int(m.group(1), 16)
            size = _resolve_constant_expr(m.group(2).strip(), consts)
            if size is None:
                continue
            if RAM_ORIGIN <= addr < RAM_ORIGIN + RAM_LIMIT:
                used += size
    return used, RAM_LIMIT - used


def rom_usage():
    """Return (used_bytes, available_bytes) for the 4 KiB ROM.

    "Used" is the high-water mark of emitted code/data below the interrupt
    vector block ($FFFA), so the $FF-filled padding counts as available.
    """
    rows = parse_listing()
    code_high = ROM_ORIGIN
    for row in rows:
        addr = row["addr"]
        if ROM_ORIGIN <= addr < VECTOR_BLOCK:
            code_high = max(code_high, addr + len(row["bytes"]) - 1)
    used = code_high - ROM_ORIGIN + 1
    return used, ROM_LIMIT - used


def require_build():
    """Fail with a clear message if the ROM has not been built."""
    if not ROM_PATH.exists():
        print("ERROR: ROM not found at " + str(ROM_PATH), file=sys.stderr)
        print("Run `python tools/build.py` first.", file=sys.stderr)
        sys.exit(2)