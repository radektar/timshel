"""TimshelTranscriber (app_core wrapper) forwards to the inner Transcriber.

Regression: the wrapper's ``import_text_file`` lacked the ``status`` kwarg the
menu passes, so every bundled import crashed with "unexpected keyword argument
'status'". Unit tests that mock the whole transcriber never caught it — these
exercise the REAL wrapper signature against the real inner API surface.
"""

import inspect

from src.app_core import TimshelTranscriber
from src.transcriber import Transcriber


def _wrapper_with_inner(inner) -> TimshelTranscriber:
    app = TimshelTranscriber(setup_signals=False)
    app.transcriber = inner
    return app


class _RecordingInner:
    def __init__(self):
        self.calls = {}

    def import_text_file(self, source, status=None):
        self.calls["import_text_file"] = {"source": source, "status": status}
        if status is not None:
            status["duplicate"] = False
        return True

    def reload_paths(self):
        self.calls["reload_paths"] = True


def test_import_text_file_forwards_status():
    inner = _RecordingInner()
    app = _wrapper_with_inner(inner)
    st: dict = {}
    assert app.import_text_file("note.md", status=st) is True
    assert inner.calls["import_text_file"]["status"] is st
    assert st == {"duplicate": False}


def test_reload_paths_forwards():
    inner = _RecordingInner()
    app = _wrapper_with_inner(inner)
    app.reload_paths()
    assert inner.calls.get("reload_paths") is True


def test_wrapper_signature_matches_inner():
    """The wrapper must accept every param the inner import_text_file accepts."""
    inner_params = set(inspect.signature(Transcriber.import_text_file).parameters)
    wrapper_params = set(
        inspect.signature(TimshelTranscriber.import_text_file).parameters
    )
    assert inner_params <= wrapper_params, (
        f"wrapper missing params: {inner_params - wrapper_params}"
    )
