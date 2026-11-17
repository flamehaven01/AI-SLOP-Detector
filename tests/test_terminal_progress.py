"""The scan's progress on a terminal (3.17): what is running, in a box that
goes away when the scan ends.

- nothing is written when the stream is not a terminal;
- the box names the phases, the files found per language, and the file count
  as it rises;
- drawing can never end a scan: a broken stream, or a console that cannot
  encode the box, stops the drawing only.
"""

from __future__ import annotations

import io

from slop_detector.renderer_terminal import Progress
from slop_detector.service.events import ScanEvent


class Tty(io.StringIO):
    def isatty(self):
        return True


def _events(names=("a.py", "b.py", "page.jsx")):
    yield ScanEvent("discovered", totals={"python": 2, "javascript": 1, "go": 0}, total=3)
    for index, name in enumerate(names, 1):
        language = "javascript" if name.endswith(".jsx") else "python"
        yield ScanEvent(
            "file_done",
            index=index,
            total=3,
            path=f"pkg/{name}",
            language=language,
            outcome="analyzed",
        )
    yield ScanEvent("aggregating", total=3)
    yield ScanEvent("completed")


def _feed(stream, events, **options):
    progress = Progress(stream, **options)
    for event in events:
        progress(event)
    return progress


def test_nothing_is_written_when_the_stream_is_not_a_terminal():
    quiet = io.StringIO()
    _feed(quiet, _events())
    assert quiet.getvalue() == ""


def test_the_box_names_the_phases_the_languages_and_the_rising_count():
    tty = Tty()
    ticks = iter(range(100))
    _feed(tty, _events(), clock=lambda: float(next(ticks)))  # every event is due for drawing
    shown = tty.getvalue()
    for words in ("Find files", "Analyze", "Score", "3 files", "Python 2", "JS/TS 1"):
        assert words in shown, words
    assert "Go" not in shown  # a language with no file is not named
    for count, name in (("1/3", "a.py"), ("2/3", "b.py"), ("3/3", "page.jsx")):
        assert count in shown and name in shown, (count, name)


def test_file_events_between_two_drawings_are_not_each_drawn():
    """A large scan sends thousands of events; the box is redrawn at most
    every tenth of a second, and the last count is still shown."""
    tty = Tty()
    names = [f"m{i}.py" for i in range(200)]
    events = [ScanEvent("discovered", totals={"python": 200}, total=200)]
    events += [
        ScanEvent(
            "file_done", index=i, total=200, path=f"pkg/{n}", language="python", outcome="analyzed"
        )
        for i, n in enumerate(names, 1)
    ]
    events += [ScanEvent("aggregating", total=200)]
    _feed(tty, events, clock=lambda: 0.0)  # no time passes: file events are not due
    shown = tty.getvalue()
    assert shown.count("/200") <= 3, shown.count("/200")
    assert "200/200" in shown  # the phase change draws the final count


def test_the_box_is_gone_when_the_scan_ends():
    for last in ("completed", "failed", "cancelled"):
        tty = Tty()
        progress = _feed(tty, list(_events())[:-1] + [ScanEvent(last)])
        assert progress.active is False, last


def test_a_broken_stream_stops_the_drawing_and_not_the_scan():
    class Broken(Tty):
        def write(self, text):
            raise OSError("closed")

    _feed(Broken(), _events())  # does not raise


def test_a_console_that_cannot_encode_the_box_still_gets_one():
    raw = io.BytesIO()

    class CpTty(io.TextIOWrapper):
        def isatty(self):
            return True

    for encoding in ("cp1252", "cp949", "ascii"):
        stream = CpTty(raw, encoding=encoding, errors="strict")
        ticks = iter(range(100))
        _feed(stream, _events(), clock=lambda: float(next(ticks)))
        stream.flush()
        assert b"Find files" in raw.getvalue(), encoding
        stream.detach()


def test_the_languages_line_uses_the_separator_of_this_console():
    """The text of the files found is made with the glyphs chosen for the
    console, not the default ones: on a console that gets the ASCII set, a
    two-cell dot made that line wrap, and every redraw left a line behind."""
    raw = io.BytesIO()

    class AsciiTty(io.TextIOWrapper):
        def isatty(self):
            return True

    stream = AsciiTty(raw, encoding="ascii", errors="strict")
    ticks = iter(range(100))
    progress = _feed(stream, _events(), clock=lambda: float(next(ticks)))
    stream.flush()
    shown = raw.getvalue().decode("ascii")
    assert "3 files - Python 2 - JS/TS 1" in shown, shown
    assert "3/3" in shown  # the drawing went on to the end
    assert progress.active is False
    stream.detach()
