"""Helpers for loading neural data files.

Supports .npz (native DNB format) and provides stubs for .nev/.ns5
(Blackrock native formats) which require additional dependencies.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


def load_npz(path: str | Path) -> dict[str, NDArray]:
    """Load a DNB-format .npz file.

    Expected keys: 'continuous', 'sample_rate'.
    Optional keys: 'channel_ids', 'timestamps'.

    Returns:
        Dictionary with numpy arrays.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    data = dict(np.load(str(path), allow_pickle=False))
    required = {"continuous", "sample_rate"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys in {path.name}: {missing}")

    logger.info(
        "Loaded %s: %d channels, %d samples, %.0f Hz",
        path.name,
        data["continuous"].shape[0],
        data["continuous"].shape[1],
        float(data["sample_rate"]),
    )
    return data


def load_blackrock(path: str | Path) -> dict[str, NDArray]:
    """Load Blackrock .nev or .ns5 files.

    Requires the brpylib package (Blackrock Python I/O library).

    Returns:
        Dictionary with 'continuous', 'sample_rate', 'channel_ids'.

    Raises:
        NotImplementedError: Placeholder until full implementation.
    """
    raise NotImplementedError(
        f"Blackrock file loading not yet implemented for: {path}. "
        "Install brpylib and contribute the integration."
    )