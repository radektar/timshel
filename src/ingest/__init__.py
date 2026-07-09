"""Ingest layer — bring already-transcribed text into the pipeline.

Pure parsing only: turn a txt/md/vtt file into an :class:`ImportedDoc`
(text + metadata) and a content fingerprint. Orchestration (locking, dedup,
summarize→render→index) lives on :class:`src.transcriber.Transcriber` via
``import_text_file`` — this package stays free of transcriber/AppKit imports
so it is trivially testable.

v1 handles txt/md and WebVTT (the export format Zoom/Meet/Teams/Otter all
emit). PDF and platform-specific JSON are deferred (see Docs/future/ingest-plan.md).
"""

from src.ingest.adapters import ImportedDoc, SUPPORTED_SUFFIXES, parse
from src.ingest.fingerprint import text_fingerprint

__all__ = ["ImportedDoc", "SUPPORTED_SUFFIXES", "parse", "text_fingerprint"]
