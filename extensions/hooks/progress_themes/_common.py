"""Helpers shared by the progress themes: colors, number formatting and line fitting."""

import os
from dataclasses import dataclass, field

BOLD, DIM, RESET = "\x1b[1m", "\x1b[2m", "\x1b[0m"
BLUE, GREEN = "\x1b[34m", "\x1b[32m"

_TRUECOLOR = os.getenv("COLORTERM", "").lower() in ("truecolor", "24bit")


def rgb(r, g, b):
    """24-bit color if the terminal says it supports it, else the nearest xterm-256 color."""
    if _TRUECOLOR:
        return f"\x1b[38;2;{r};{g};{b}m"
    cube = [round(c / 255 * 5) for c in (r, g, b)]
    return f"\x1b[38;5;{16 + 36 * cube[0] + 6 * cube[1] + cube[2]}m"


def gradient(stops, t):
    """Color at position t (0..1) along a list of (r, g, b) stops."""
    t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    a, b = stops[i], stops[i + 1]
    return rgb(*(round(x + (y - x) * f) for x, y in zip(a, b, strict=True)))


def human(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


@dataclass
class Line:
    """What a theme draws.

    left: (text, sgr) segments. right: (kind, segments) groups, dropped whole when the
    terminal is too narrow ("detail" first, then from the end). bar(cells) returns the bar
    segments for that many cells. flush_right lays the line out as `left ... right bar`
    (pacman), otherwise `left bar right`. reserve/max_cells size the bar.
    """

    left: list
    bar: object
    right: list = field(default_factory=list)
    flush_right: bool = False
    reserve: int = 42
    max_cells: int = 40


def _width(segments):
    return sum(len(text) for text, _ in segments)


def _flat(groups):
    return [seg for _, segments in groups for seg in segments]


def left_width(line):
    return _width(line.left)


def render(line, st, width, color, pad_left=0):
    """The line as a string no wider than `width`, with or without colors.

    pad_left widens the left part to that many columns, so the bars of stacked lines
    start in the same column.
    """
    left = line.left
    if pad_left > _width(left):
        left = [*left, (" " * (pad_left - _width(left)), None)]
    if st.cells is None:  # fixed per line, so the bar doesn't jitter as numbers change
        st.cells = max(10, min(line.max_cells, width - _width(left) - line.reserve))
    bar = line.bar(st.cells)
    right = line.right

    def fits():
        return _width(left + _flat(right) + bar) + 2 <= width

    if not fits():
        right = [group for group in right if group[0] != "detail"]
    while right and not fits():
        right = right[:-1]
    right = _flat(right)

    if line.flush_right:
        fill = max(1, width - _width(left + right + bar))
        segments = [*left, (" " * fill, None), *right, *bar]
    else:
        segments = [*left, (" ", None), *bar, *right]
    return "".join(
        f"{sgr}{text}{RESET}" if sgr and color else text for text, sgr in segments
    )
