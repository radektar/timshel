"""Guardrails for downloader model metadata consistency."""

import re

from src.config.defaults import SUPPORTED_MODELS
from src.setup.checksums import CHECKSUMS, MODEL_ALIASES, SIZES, URLS


def _canonical(model: str) -> str:
    return MODEL_ALIASES.get(model, model)


def test_supported_models_have_download_metadata() -> None:
    """Every supported model must have URL, checksum, and expected size."""
    for model in SUPPORTED_MODELS:
        url = URLS.get(f"model_{model}")
        assert url is not None, f"Missing URL for model {model}"
        assert url.startswith("https://"), f"Non-HTTPS URL for model {model}"

        artifact = f"ggml-{_canonical(model)}.bin"
        assert artifact in CHECKSUMS, f"Missing checksum for {artifact}"
        assert artifact in SIZES, f"Missing size for {artifact}"


def test_model_checksums_use_supported_prefix_format() -> None:
    """Model checksums must be prefixed with supported hash algorithm."""
    sha1_re = re.compile(r"^sha1:[0-9a-f]{40}$")
    sha256_re = re.compile(r"^sha256:[0-9a-f]{64}$")

    for model in SUPPORTED_MODELS:
        artifact = f"ggml-{_canonical(model)}.bin"
        checksum = CHECKSUMS[artifact]
        assert isinstance(checksum, str)
        assert sha1_re.match(checksum) or sha256_re.match(
            checksum
        ), f"Invalid checksum format for {artifact}: {checksum}"
