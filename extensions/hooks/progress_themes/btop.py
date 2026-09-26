"""btop-style meter: `■■■■■■····` with a per-cell color gradient, labels in muted colors.

cmake/3.31.12 > unpacking conan_package.tgz  ■■■■■■■■■■■■  44%  18.9 MiB / 43.0 MiB  17.2 MiB/s  eta 00:01
"""

from ._common import BOLD, Line, duration, gradient, human, rgb

_GRADIENT = [(0x16, 0x8F, 0xE8), (0x77, 0xCA, 0x9B), (0xB5, 0xE6, 0x85)]
_GREY = (0x6C, 0x6C, 0x6C)
_EMPTY = (0x3A, 0x3A, 0x3A)
_NAME = (0x18, 0xC2, 0xE8)


def layout(st):
    grey = rgb(*_GREY)
    left = [(" ", None)]
    if st.scope:
        left += [(st.scope, BOLD), (" > ", grey)]
    left += [(st.verb, grey), (" ", None), (st.name, rgb(*_NAME))]
    right = []
    if st.detail:
        right.append(("detail", [("  ", None), (st.detail, grey)]))
    elif st.total:
        right.append(
            ("size", [("  ", None), (f"{human(st.done)} / {human(st.total)}", None)])
        )
    if st.finished:
        done = gradient(_GRADIENT, 1)
        right.append(("time", [("  done in ", grey), (f"{st.elapsed:.1f}s", done)]))
    elif st.rate:
        right.append(("rate", [("  ", None), (f"{human(st.rate)}/s", grey)]))
        if st.eta is not None:
            right.append(("time", [("  eta ", grey), (duration(st.eta), None)]))

    def bar(cells):
        filled = round(cells * st.fraction)
        meter = [
            ("■", gradient(_GRADIENT, i / max(cells - 1, 1))) for i in range(filled)
        ]
        return [
            ("  ", None),
            *meter,
            ("■" * (cells - filled), rgb(*_EMPTY)),
            (f" {int(st.fraction * 100):3d}%", BOLD + gradient(_GRADIENT, st.fraction)),
        ]

    return Line(left, bar, right, reserve=55, max_cells=30)
