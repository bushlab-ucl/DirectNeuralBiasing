"""YAML configuration loader for DNB pipelines.

Loads pipeline parameters from a YAML file so the pipeline can be
configured without editing Python code.  Supports all PipelineConfig
fields and all module constructor parameters.

Usage:
    from dnb.config import load_config, build_pipeline
    pipeline = build_pipeline("config.yaml")
    pipeline.run_online()

Or load just the config dict:
    cfg = load_config("config.yaml")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from dnb.core.types import PipelineConfig

logger = logging.getLogger(__name__)


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file and return the raw dict.

    Args:
        path: Path to the YAML config file.

    Returns:
        Parsed configuration dictionary.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the file is not valid YAML.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not isinstance(cfg, dict):
        raise ValueError(f"Config file must contain a YAML mapping, got {type(cfg).__name__}")

    logger.info("Loaded config from %s", path)
    return cfg


def build_pipeline_config(cfg: dict[str, Any]) -> PipelineConfig:
    """Build a PipelineConfig from the 'pipeline' section of a config dict.

    Args:
        cfg: Full config dict (with optional 'pipeline' key).

    Returns:
        PipelineConfig populated from the YAML values.
    """
    p = cfg.get("pipeline", {})

    channel_ids = None
    if "channel_ids" in p:
        channel_ids = np.array(p["channel_ids"], dtype=np.int32)

    return PipelineConfig(
        sample_rate=float(p.get("sample_rate", 30_000.0)),
        n_channels=int(p.get("n_channels", 83)),
        channel_ids=channel_ids,
        buffer_duration=float(p.get("buffer_duration", 10.0)),
        chunk_duration=float(p.get("chunk_duration", 0.2)),
    )


def build_modules(cfg: dict[str, Any]) -> list:
    """Build the module chain from config.

    Reads module-specific sections from the config dict and constructs
    the corresponding module objects.  Modules are returned in pipeline
    order.

    Recognised sections:
        downsampler, wavelet, power, slow_wave, detector, audio

    Args:
        cfg: Full config dict.

    Returns:
        List of configured Module instances.
    """
    from dnb.modules.audio_stim import AudioStimulator
    from dnb.modules.detector import EventDetector
    from dnb.modules.downsampler import Downsampler
    from dnb.modules.power import PowerEstimator
    from dnb.modules.slow_wave import SlowWaveDetector
    from dnb.modules.wavelet import WaveletConvolution

    modules = []

    # --- Downsampler (must come first if present) ---
    if "downsampler" in cfg:
        d = cfg["downsampler"]
        if d.get("enabled", True):
            modules.append(Downsampler(
                target_rate=float(d.get("target_rate", 500.0)),
                buffer_duration=float(d.get("buffer_duration",
                                            cfg.get("pipeline", {}).get("buffer_duration", 10.0))),
            ))

    # --- Channel selection ---
    # A single selected channel, applied to wavelet + detector
    pipeline_cfg = cfg.get("pipeline", {})
    channel = pipeline_cfg.get("channel")
    channels = [channel] if channel is not None else None

    # --- Wavelet ---
    if "wavelet" in cfg:
        w = cfg["wavelet"]
        modules.append(WaveletConvolution(
            freq_min=float(w.get("freq_min", 0.5)),
            freq_max=float(w.get("freq_max", 30.0)),
            n_freqs=int(w.get("n_freqs", 10)),
            n_cycles_base=float(w.get("n_cycles_base", 3.0)),
            channels=w.get("channels", channels),
        ))
    else:
        # Default wavelet for slow wave detection
        modules.append(WaveletConvolution(
            freq_min=0.5, freq_max=30.0, n_freqs=10,
            channels=channels,
        ))

    # --- Power estimator ---
    if cfg.get("power", {}).get("enabled", True):
        bands = cfg.get("power", {}).get("bands")
        if bands:
            bands = {name: tuple(limits) for name, limits in bands.items()}
        modules.append(PowerEstimator(bands=bands))

    # --- Slow wave detector ---
    if "slow_wave" in cfg:
        sw = cfg["slow_wave"]
        freq_range = tuple(sw.get("freq_range", [0.5, 2.0]))
        hf_freq_range = tuple(sw.get("hf_freq_range", [10.0, 40.0]))

        modules.append(SlowWaveDetector(
            target_phase=float(sw.get("target_phase", 0.0)),
            phase_tolerance=float(sw.get("phase_tolerance", 0.15)),
            freq_range=freq_range,
            hf_freq_range=hf_freq_range,
            amp_min=float(sw.get("amp_min", 50.0)),
            amp_max=float(sw.get("amp_max", 10000.0)),
            hf_ratio_max=float(sw.get("hf_ratio_max", 0.5)),
            backoff_s=float(sw.get("backoff_s", 5.0)),
            stim2_delay_s=float(sw.get("stim2_delay_s", 0.6)),
            stim2_window_s=float(sw.get("stim2_window_s", 2.0)),
            warmup_chunks=int(sw.get("warmup_chunks", 10)),
            channels=sw.get("channels", channels),
            amp_smoothing=int(sw.get("amp_smoothing", 5)),
            event_window_s=float(sw.get("event_window_s", 1.0)),
        ))

    # --- Event detector (optional, for non-SW detection) ---
    if "detector" in cfg:
        det = cfg["detector"]
        from dnb.core.types import EventType
        et_name = det.get("event_type", "THRESHOLD_CROSSING")
        modules.append(EventDetector(
            event_type=EventType[et_name.upper()],
            freq_range=tuple(det.get("freq_range", [80.0, 250.0])),
            threshold_std=float(det.get("threshold_std", 3.0)),
            min_duration=float(det.get("min_duration", 0.02)),
            channels=det.get("channels", channels),
            cooldown=float(det.get("cooldown", 0.1)),
            warmup_chunks=int(det.get("warmup_chunks", 5)),
            ema_alpha=float(det.get("ema_alpha", 0.01)),
        ))

    # --- Audio stimulator ---
    if "audio" in cfg:
        a = cfg["audio"]
        wav_path = a.get("wav_path")
        if wav_path and Path(wav_path).exists():
            from dnb.core.types import EventType
            trigger_names = a.get("trigger_on", ["STIM1"])
            trigger_on = tuple(EventType[n.upper()] for n in trigger_names)
            modules.append(AudioStimulator(
                wav_path=wav_path,
                trigger_on=trigger_on,
                volume=float(a.get("volume", 1.0)),
            ))
        else:
            logger.info("Audio file not found or not specified — audio stim disabled")

    return modules


def build_source(cfg: dict[str, Any]):
    """Build a DataSource from config.

    Recognised source types: file, nplay, cerebus.

    Args:
        cfg: Full config dict (reads the 'source' section).

    Returns:
        A DataSource instance.
    """
    from dnb.sources.file import FileSource

    src_cfg = cfg.get("source", {})
    kind = src_cfg.get("type", "file").lower()

    if kind == "file":
        path = src_cfg.get("path")
        if not path:
            raise ValueError("source.path is required for file source")
        return FileSource(path)

    elif kind == "nplay":
        from dnb.sources.nplay import NPlaySource
        return NPlaySource(
            protocol=src_cfg.get("protocol", "NPLAY"),
            startup_delay=float(src_cfg.get("startup_delay", 2.0)),
        )

    elif kind == "cerebus":
        from dnb.sources.cerebus import CerebusSource
        return CerebusSource(
            inst_addr=src_cfg.get("inst_addr", ""),
            client_addr=src_cfg.get("client_addr", "0.0.0.0"),
            startup_delay=float(src_cfg.get("startup_delay", 2.0)),
        )

    else:
        raise ValueError(f"Unknown source type: {kind}")


def build_pipeline(config_path: str | Path):
    """Build a complete Pipeline from a YAML config file.

    This is the main entry point for config-driven pipeline creation.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        A configured Pipeline ready to run.

    Example:
        pipeline = build_pipeline("config.yaml")
        events = pipeline.run_offline()
    """
    from dnb.engine.pipeline import Pipeline

    cfg = load_config(config_path)
    pipeline_config = build_pipeline_config(cfg)
    source = build_source(cfg)
    modules = build_modules(cfg)

    return Pipeline(source=source, modules=modules, config=pipeline_config)
