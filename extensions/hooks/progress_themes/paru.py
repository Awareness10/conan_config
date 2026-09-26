"""pacman/paru download line, flush right (the default theme).

cmake/3.31.12 unpacking conan_package.tgz    43.0 MiB  17.2 MiB/s 00:01 [######------]  44%
"""

from ._common import BLUE, BOLD, DIM, GREEN, Line, duration, human


def _scope(scope):
    """paru colors packages as bold name + green version: `cmake` `/` `3.31.12`."""
    name, _, version = scope.partition("/")
    parts = [(name, BOLD)]
    if version:
        parts += [("/", None), (version, BOLD + GREEN)]
    return [*parts, (" ", None)]


def layout(st):
    left = [(" ", None), *(_scope(st.scope) if st.scope else [])]
    left += [(st.verb, DIM), (" ", None), (st.name, None)]
    right = []
    if st.detail:
        right.append(("detail", [(st.detail, None), (" ", None)]))
    if st.total:
        right.append(("size", [(f"{human(st.total):>10}", None), (" ", None)]))
    if st.rate:
        right.append(("rate", [(f"{human(st.rate) + '/s':>12}", None), (" ", None)]))
    seconds = st.elapsed if st.finished or st.eta is None else st.eta
    right.append(("time", [(duration(seconds), None), (" ", None)]))
    pct_color = BOLD + GREEN if st.finished else BOLD

    def bar(cells):
        filled = round(cells * st.fraction)
        return [
            ("[", None),
            ("#" * filled, BOLD + BLUE),
            ("-" * (cells - filled), DIM),
            ("]", None),
            (f" {int(st.fraction * 100):3d}%", pct_color),
        ]

    return Line(left, bar, right, flush_right=True)
