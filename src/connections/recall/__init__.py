"""Local, no-LLM recall engine — "ask your whole corpus".

Pipeline: chunk (with provenance) -> embed (local, swappable provider) -> store
(sqlite-vec) -> hybrid retrieve (BM25 + dense, RRF). Search never calls an LLM and
never leaves the Mac; the only optional cloud step is an explicit "synthesize these
results" escalation handled outside this package.

Kept import-light: importing this package must not pull the embedding backend
(fastembed/llama.cpp) — those load lazily inside the provider.
"""
