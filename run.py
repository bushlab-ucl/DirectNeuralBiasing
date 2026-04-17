#!/usr/bin/env python3
"""Run the DNB pipeline.

Usage:
    python run.py -c config.yaml                    # live, auto-detect source
    python run.py -c config.yaml --source nplay     # live, force NPlay
    python run.py -c config.yaml --detect-only      # live, no stim
    python run.py -c config.yaml --offline          # offline from file
    python run.py -c config.yaml --offline --detect-only
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import dnb
from dnb.config import build_modules, build_pipeline_config, build_source, load_config
from dnb.core.types import Event, EventType, PipelineConfig
from dnb.engine.pipeline import Pipeline

logger = logging.getLogger("dnb.run")


# ── Logging ──────────────────────────────────────────────────────────────

def setup_logging(level=logging.INFO):
    fmt = logging.Formatter(
        "%(asctime)s  %(name)-28s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    root = logging.getLogger("dnb")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


# ── Event logger ─────────────────────────────────────────────────────────

class EventLogger:
    """Logs events to JSONL (crash-safe) and accumulates for .npz save."""

    def __init__(self, output_dir: Path, session_name: str):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session_name = session_name
        self._events: list[Event] = []

        self._log_path = output_dir / f"{session_name}_events.jsonl"
        self._log_file = open(self._log_path, "w")
        logger.info("Event log: %s", self._log_path)

    def log(self, event: Event) -> None:
        self._events.append(event)

        record = {
            "type": event.event_type.name,
            "timestamp": event.timestamp,
            "channel_id": event.channel_id,
        }
        # TWave metadata keys
        for key in ("pulse_index", "n_pulses", "frequency", "amplitude",
                     "phase_now", "dt_to_stim_ms",
                     "detection_time", "power", "active"):
            if key in event.metadata:
                record[key] = event.metadata[key]

        self._log_file.write(json.dumps(record) + "\n")
        self._log_file.flush()

    def save_npz(self) -> Path | None:
        if not self._events:
            logger.info("No events to save.")
            return None

        npz_path = self.output_dir / f"{self.session_name}_events.npz"
        np.savez(
            str(npz_path),
            event_types=np.array([e.event_type.name for e in self._events]),
            timestamps=np.array([e.timestamp for e in self._events]),
            channel_ids=np.array([e.channel_id for e in self._events]),
            durations=np.array([e.duration for e in self._events]),
        )
        logger.info("Saved %d events to %s", len(self._events), npz_path)
        return npz_path

    def close(self):
        if self._log_file and not self._log_file.closed:
            self._log_file.close()

    @property
    def event_count(self) -> int:
        return len(self._events)

    def summary(self) -> str:
        if not self._events:
            return "No events."
        by_type: dict[str, int] = {}
        for e in self._events:
            by_type[e.event_type.name] = by_type.get(e.event_type.name, 0) + 1
        parts = [f"{name}: {count}" for name, count in sorted(by_type.items())]
        return f"{len(self._events)} events ({', '.join(parts)})"


# ── Apply CLI overrides to config ────────────────────────────────────────

def apply_overrides(cfg: dict, args: argparse.Namespace) -> None:
    """Apply CLI overrides to the loaded config dict (in-place)."""
    if args.detect_only:
        if "trigger" not in cfg:
            cfg["trigger"] = {}
        cfg["trigger"]["n_pulses"] = 0
        logger.info("--detect-only: n_pulses=0")

    if args.channel is not None:
        if "pipeline" not in cfg:
            cfg["pipeline"] = {}
        cfg["pipeline"]["channel_index"] = args.channel
        logger.info("--channel: %d", args.channel)


# ── Source construction ──────────────────────────────────────────────────

def build_source_live(cfg: dict, source_override: str | None = None):
    """Build a live source with auto-detection."""
    src_cfg = cfg.get("source", {})
    source_type = source_override or src_cfg.get("type", "auto")
    source_type = source_type.lower()

    if source_type == "file":
        raise ValueError(
            "source.type is 'file' — use --offline, or change to nplay/cerebus."
        )

    if source_type in ("nplay", "auto"):
        try:
            from dnb.sources.live import NPlaySource
            source = NPlaySource(protocol=src_cfg.get("protocol", "NPLAY"))
            logger.info("Source: NPlay")
            return source
        except ImportError as e:
            if source_type == "nplay":
                raise ImportError("pycbsdk not installed.") from e
            logger.info("NPlay not available, trying Cerebus...")

    if source_type in ("cerebus", "auto"):
        try:
            from dnb.sources.live import CerebusSource
            source = CerebusSource(
                inst_addr=src_cfg.get("inst_addr", ""),
                client_addr=src_cfg.get("client_addr", "0.0.0.0"),
            )
            logger.info("Source: Cerebus")
            return source
        except ImportError as e:
            if source_type == "cerebus":
                raise ImportError("pycbsdk not installed.") from e

    raise RuntimeError(f"No live source available (tried: {source_type}).")


# ── Status printer ───────────────────────────────────────────────────────

class StatusPrinter:
    def __init__(self, event_logger: EventLogger, interval_s: float = 10.0):
        self._event_logger = event_logger
        self._interval_s = interval_s
        self._last_print = time.perf_counter()
        self._chunk_count = 0
        self._start_time = time.perf_counter()

    def on_chunk(self):
        self._chunk_count += 1
        now = time.perf_counter()
        if now - self._last_print >= self._interval_s:
            elapsed = now - self._start_time
            print(
                f"  [{elapsed:7.1f}s] chunks={self._chunk_count:6d}  "
                f"{self._event_logger.summary()}",
                flush=True,
            )
            self._last_print = now


# ── Run modes ────────────────────────────────────────────────────────────

def run_live(cfg: dict, args: argparse.Namespace):
    """Run the pipeline live with StimScheduler for audio timing."""
    from dnb.modules.stim_scheduler import StimScheduler

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_name = args.source or cfg.get("source", {}).get("type", "auto")
    session_name = f"dnb_{source_name}_{timestamp}"

    output_dir = Path(args.output_dir)
    event_logger = EventLogger(output_dir, session_name)
    status = StatusPrinter(event_logger)

    source = build_source_live(cfg, args.source)
    modules = build_modules(cfg)
    pipeline_config = build_pipeline_config(cfg)

    pipeline = Pipeline(
        source=source,
        modules=modules,
        config=pipeline_config,
    )

    # Register event logger
    pipeline.on_event(None, event_logger.log)

    # Set up StimScheduler for audio (only if n_pulses > 0)
    n_pulses = cfg.get("trigger", {}).get("n_pulses", 1)
    scheduler = None
    audio_cfg = cfg.get("audio", {})
    wav_path = audio_cfg.get("wav_path")

    if n_pulses > 0 and wav_path:
        scheduler = StimScheduler(
            wav_path=wav_path,
            volume=float(audio_cfg.get("volume", 1.0)),
        )
        pipeline.on_event("STIM", scheduler.on_stim_event)

    print()
    print("=" * 60)
    print("  DNB LIVE SESSION")
    print("=" * 60)
    print(f"  Source:       {source_name}")
    print(f"  n_pulses:     {n_pulses}")
    print(f"  Audio:        {'yes' if scheduler else 'no'}")
    print(f"  Log file:     {event_logger._log_path}")
    print("=" * 60)
    print("  Ctrl+C to stop")
    print()

    try:
        pipeline._setup()
        pipeline._running = True

        # Set time mapping for scheduler
        t_start = time.perf_counter()
        if scheduler:
            scheduler.set_time_offset(0.0, t_start)
            scheduler.start()

        original_handler = signal.getsignal(signal.SIGINT)

        def _shutdown(signum, frame):
            logger.info("SIGINT — stopping pipeline...")
            pipeline._running = False

        signal.signal(signal.SIGINT, _shutdown)

        try:
            while pipeline._running:
                chunk = pipeline._source.read_chunk()
                if chunk is None:
                    time.sleep(0.001)
                    continue
                result = pipeline._process_chunk(chunk)
                if result is not None:
                    status.on_chunk()
        finally:
            elapsed = time.perf_counter() - t_start
            signal.signal(signal.SIGINT, original_handler)
            if scheduler:
                scheduler.stop()
            pipeline._teardown()

    except Exception:
        logger.exception("Pipeline error")
    finally:
        npz_path = event_logger.save_npz()
        event_logger.close()

        print()
        print("=" * 60)
        print("  SESSION COMPLETE")
        print("=" * 60)
        print(f"  {event_logger.summary()}")
        if npz_path:
            print(f"  Events saved: {npz_path}")
        print(f"  Log file:     {event_logger._log_path}")
        print("=" * 60)
        print()


def run_offline(cfg: dict, args: argparse.Namespace):
    """Run the pipeline on a saved file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)

    # Build pipeline from the (already-modified) cfg dict, not from disk
    source = build_source(cfg)
    modules = build_modules(cfg)
    pipeline_config = build_pipeline_config(cfg)

    pipeline = Pipeline(
        source=source,
        modules=modules,
        config=pipeline_config,
    )

    event_logger = EventLogger(output_dir, f"dnb_offline_{timestamp}")
    pipeline.on_event(None, event_logger.log)

    events = pipeline.run_offline()
    event_logger.save_npz()
    event_logger.close()

    detections = [e for e in events if e.event_type == EventType.SLOW_WAVE]
    stims = [e for e in events if e.event_type == EventType.STIM]
    print(f"\nOffline complete: {len(detections)} detections, {len(stims)} stims")

    # Print timing summary
    if stims and detections:
        delays = []
        for s in stims:
            if s.metadata.get("pulse_index") == 1:
                det_t = s.metadata.get("detection_time", s.timestamp)
                delays.append((s.timestamp - det_t) * 1000)
        if delays:
            print(f"Detection\u2192Stim delay: {np.mean(delays):.0f} \u00b1 {np.std(delays):.0f} ms")


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DNB pipeline runner")
    parser.add_argument("--config", "-c", required=True, help="YAML config file")
    parser.add_argument("--offline", action="store_true", help="Offline batch mode")
    parser.add_argument(
        "--source", "-s", choices=["nplay", "cerebus", "auto"],
        default=None, help="Force source type",
    )
    parser.add_argument("--detect-only", action="store_true", help="n_pulses=0")
    parser.add_argument("--channel", type=int, default=None, help="Hardware channel index")
    parser.add_argument("--output-dir", "-o", default="./output", help="Output directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    logger.info("DNB v%s", dnb.__version__)

    cfg = load_config(args.config)

    # Apply CLI overrides to the config dict BEFORE building anything
    apply_overrides(cfg, args)

    # Auto-detect offline mode if source is file
    source_type = cfg.get("source", {}).get("type", "auto").lower()
    if source_type == "file" and not args.offline:
        logger.info("source.type is 'file' \u2014 switching to offline mode automatically")
        args.offline = True

    if args.offline:
        run_offline(cfg, args)
    else:
        run_live(cfg, args)


if __name__ == "__main__":
    main()