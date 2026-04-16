"""YAML configuration loader for DNB pipelines.

Builds a complete pipeline from a config file without writing Python.

Usage:
    from dnb.config import build_pipeline
    pipeline = build_pipeline("config.yaml")
    events = pipeline.run_offline()
"""

from __future__ import annotations

import logging
from math import pi
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from dnb.core.types import PipelineConfig

logger = logging.getLogger(__name__)


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file (UTF-8 encoded)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"Config must be a YAML mapping, got {type(cfg).__name__}")
    return cfg


def build_pipeline_config(cfg: dict[str, Any]) -> PipelineConfig:
    """Build PipelineConfig from the 'pipeline' section."""
    p = cfg.get("pipeline", {})
    return PipelineConfig(
        sample_rate=float(p.get("sample_rate", 30_000.0)),
        n_channels=int(p.get("n_channels", 1)),
        buffer_duration=float(p.get("buffer_duration", 10.0)),
        chunk_duration=float(p.get("chunk_duration", 0.5)),
    )


def _parse_phase(value) -> float:
    """Parse a phase value — supports 'pi', '3pi/2', '0', '3.14', etc."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().lower().replace(" ", "")
        if s == "pi":
            return pi
        if s == "3pi/2" or s == "3*pi/2" or s == "1.5pi" or s == "1.5*pi":
            return 3 * pi / 2
        if s == "pi/2" or s == "pi*0.5":
            return pi / 2
        if s == "0" or s == "0.0":
            return 0.0
        return float(s)
    return float(value)


def build_modules(cfg: dict[str, Any]) -> list:
    """Build the module chain from config sections.

    Recognised: downsampler, wavelet, target_wave, amplitude_monitor, trigger, audio
    """
    from dnb.modules.amplitude_monitor import AmplitudeMonitor
    from dnb.modules.audio_stim import AudioStimulator
    from dnb.modules.downsampler import Downsampler
    from dnb.modules.stim_trigger import StimTrigger
    from dnb.modules.target_wave_detector import TargetWaveDetector
    from dnb.modules.wavelet import WaveletConvolution

    modules = []

    # Downsampler (optional, for live hardware)
    if "downsampler" in cfg:
        d = cfg["downsampler"]
        if d.get("enabled", True):
            modules.append(Downsampler(target_rate=float(d.get("target_rate", 500.0))))

    # Wavelet convolution (always present)
    w = cfg.get("wavelet", {})
    modules.append(WaveletConvolution(
        freq_min=float(w.get("freq_min", 0.5)),
        freq_max=float(w.get("freq_max", 30.0)),
        n_freqs=int(w.get("n_freqs", 10)),
        n_cycles_base=float(w.get("n_cycles_base", 3.0)),
    ))

    # Target wave detector (activation)
    tw = cfg.get("target_wave", {})
    modules.append(TargetWaveDetector(
        id=tw.get("id", "slow_wave"),
        freq_range=tuple(tw.get("freq_range", [0.5, 2.0])),
        detection_phase=_parse_phase(tw.get("detection_phase", 3 * pi / 2)),
        phase_tolerance=float(tw.get("phase_tolerance", 0.15)),
        amp_min=float(tw.get("amp_min", 50.0)),
        amp_max=float(tw.get("amp_max", 10000.0)),
        warmup_chunks=int(tw.get("warmup_chunks", 10)),
        # amp_smoothing is deprecated and ignored
    ))

    # Amplitude monitor (IED inhibition, optional)
    if "amplitude_monitor" in cfg:
        am = cfg["amplitude_monitor"]
        if am.get("enabled", True):
            kwargs = {
                "id": am.get("id", "ied_monitor"),
                "freq_range": tuple(am.get("freq_range", [80.0, 120.0])),
                "warmup_chunks": int(am.get("warmup_chunks", 20)),
                "baseline_chunks": int(am.get("baseline_chunks", 100)),
                "filter_order": int(am.get("filter_order", 4)),
            }
            if "threshold" in am:
                kwargs["threshold"] = float(am["threshold"])
            else:
                kwargs["adaptive_n_std"] = float(am.get("adaptive_n_std", 3.0))
            modules.append(AmplitudeMonitor(**kwargs))

    # Stim trigger
    tr = cfg.get("trigger", {})
    inh_id = tr.get("inhibition_detector_id")
    # Default to ied_monitor if amplitude_monitor is configured
    if inh_id is None and "amplitude_monitor" in cfg and cfg["amplitude_monitor"].get("enabled", True):
        inh_id = cfg.get("amplitude_monitor", {}).get("id", "ied_monitor")

    modules.append(StimTrigger(
        activation_detector_id=tr.get("activation_detector_id", "slow_wave"),
        inhibition_detector_id=inh_id,
        n_pulses=int(tr.get("n_pulses", 1)),
        stim_phase=_parse_phase(tr.get("stim_phase", 0.0)),
        backoff_s=float(tr.get("backoff_s", 5.0)),
        inhibition_cooldown_s=float(tr.get("inhibition_cooldown_s", 5.0)),
    ))

    # Audio (optional — only for offline playback, live uses StimScheduler)
    if "audio" in cfg:
        a = cfg["audio"]
        wav_path = a.get("wav_path")
        if wav_path and Path(wav_path).exists():
            from dnb.core.types import EventType
            trigger_names = a.get("trigger_on", ["STIM"])
            modules.append(AudioStimulator(
                wav_path=wav_path,
                trigger_on=tuple(EventType[n.upper()] for n in trigger_names),
                volume=float(a.get("volume", 1.0)),
            ))

    return modules


def build_source(cfg: dict[str, Any]):
    """Build a DataSource from config."""
    from dnb.sources.file import FileSource
    src = cfg.get("source", {})
    kind = src.get("type", "file").lower()

    if kind == "file":
        if not src.get("path"):
            raise ValueError("source.path required for file source")
        return FileSource(src["path"])
    elif kind == "nplay":
        from dnb.sources.live import NPlaySource
        return NPlaySource(protocol=src.get("protocol", "NPLAY"))
    elif kind == "cerebus":
        from dnb.sources.live import CerebusSource
        return CerebusSource(
            inst_addr=src.get("inst_addr", ""),
            client_addr=src.get("client_addr", "0.0.0.0"),
        )
    else:
        raise ValueError(f"Unknown source type: {kind}")


def build_pipeline(config_path: str | Path):
    """Build a complete Pipeline from a YAML config file."""
    from dnb.engine.pipeline import Pipeline
    cfg = load_config(config_path)
    return Pipeline(
        source=build_source(cfg),
        modules=build_modules(cfg),
        config=build_pipeline_config(cfg),
    )