"""Checksums, URLs, and versions for dependencies."""

# Wersje zależności
VERSIONS = {
    "whisper": "1.1.0",
    "whisper_distribution": "static",
    "ffmpeg": "6.1",
    "models": "ggerganov/whisper.cpp@main",
}

# SHA256 checksums (verified from deps-v1.0.0 release)
CHECKSUMS = {
    # Verified from deps-v1.1.0 release assets.
    "whisper-bundled-arm64.tar.gz": "0da3355a879260d23c2e31e082e36de1d19d9d25fb8045771b3bc679f6c1dc22",
    "whisper-cli": "ddb643d77e6d479ee9e1b7beafa2a9f174c58ab048db2f412bf85fc1ff3e5362",
    "ffmpeg-arm64": "b68f795f7fb4528daf697f57a2b6780846a1ae762a71907e994442ad103ee88f",
    "ggml-tiny.bin": "sha1:bd577a113a864445d4c299885e0cb97d4ba92b5f",
    "ggml-base.bin": "sha1:465707469ff3a37a2b9b8d8f89f2f99de7299dac",
    "ggml-small.bin": "sha256:1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
    "ggml-medium.bin": "sha1:fd9727b6e1217c2f614f9b698455c4ffd82463b4",
    "ggml-large-v3.bin": "sha1:ad82bf6a9043ceed055076d0fd39f5f186ff8062",
    # CoreML encoders — required by whisper-cli built with WHISPER_COREML=ON
    "ggml-base-encoder.mlmodelc.zip": "sha256:7e6ab77041942572f239b5b602f8aaa1c3ed29d73e3d8f20abea03a773541089",
    "ggml-small-encoder.mlmodelc.zip": "sha256:de43fb9fed471e95c19e60ae67575c2bf09e8fb607016da171b06ddad313988b",
    "ggml-medium-encoder.mlmodelc.zip": "sha256:79b0b8d436d47d3f24dd3afc91f19447dd686a4f37521b2f6d9c30a642133fbd",
}

# URLs dla pobierania
URLS = {
    "whisper": "https://github.com/radektar/timshel/releases/download/deps-v1.1.0/whisper-cli",
    "ffmpeg": "https://github.com/radektar/timshel/releases/download/deps-v1.1.0/ffmpeg-arm64",
    "model_tiny": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
    "model_base": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
    "model_small": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
    "model_medium": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
    "model_large": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin",
    # CoreML encoders
    "model_base_encoder": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base-encoder.mlmodelc.zip",
    "model_small_encoder": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-encoder.mlmodelc.zip",
    "model_medium_encoder": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium-encoder.mlmodelc.zip",
}

# Aliasy modeli UI -> canonical filename suffix
MODEL_ALIASES = {
    "large": "large-v3",
}

# Oczekiwane rozmiary plików (w bajtach) - verified from release
SIZES = {
    # Verified from deps-v1.1.0 release assets.
    "whisper-bundled-arm64.tar.gz": 1_294_021,  # ~1.2MB
    "whisper-cli": 3_138_072,  # ~3.0MB
    "ffmpeg-arm64": 80_269_896,  # ~76MB
    "ggml-tiny.bin": 78_643_200,  # ~75MiB
    "ggml-base.bin": 148_897_792,  # ~142MiB
    "ggml-small.bin": 487_601_967,  # ~465MB
    "ggml-medium.bin": 1_610_612_736,  # ~1.5GiB
    "ggml-large-v3.bin": 3_113_041_920,  # ~2.9GiB
    # CoreML encoder zips (verified from HuggingFace LFS)
    "ggml-base-encoder.mlmodelc.zip": 37_922_638,   # ~36MB
    "ggml-small-encoder.mlmodelc.zip": 163_083_239,  # ~156MB
    "ggml-medium-encoder.mlmodelc.zip": 567_829_413,  # ~541MB
}

