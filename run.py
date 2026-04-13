#!/usr/bin/env python3
"""Run the DNB pipeline from a YAML config file.

Usage:
    python run.py --config config.yaml                    # online (live)
    python run.py --config config.yaml --offline          # offline (file)
    python run.py --config config.yaml --snr-sweep        # synthetic validation
"""

import argparse
import logging
import sys

import dnb
from dnb.config import build_pipeline, load_config

logger = logging.getLogger("dnb.run")


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


def main():
    parser = argparse.ArgumentParser(description="DNB pipeline runner")
    parser.add_argument("--config", "-c", required=True, help="YAML config file")
    parser.add_argument("--offline", action="store_true", help="Offline batch mode")
    parser.add_argument("--snr-sweep", action="store_true", help="Synthetic SNR sweep")
    parser.add_argument("--output-dir", "-o", default="./output")
    args = parser.parse_args()

    setup_logging()
    logger.info("DNB v%s", dnb.__version__)

    if args.snr_sweep:
        from math import pi
        from dnb import Pipeline, FileSource, PipelineConfig, EventType
        from dnb.modules import WaveletConvolution, TargetWaveDetector, StimTrigger
        from dnb.validation.synthetic import generate_synthetic_recording, save_synthetic
        from dnb.validation.ground_truth import validate, Annotation
        from pathlib import Path

        cfg = load_config(args.config)
        snr_levels = cfg.get("validation", {}).get("snr_levels", [1.0, 2.0, 3.0, 5.0, 10.0])
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'SNR':>6} {'Prec':>6} {'Recall':>6} {'F1':>6} {'TP':>4} {'FP':>4} {'FN':>4}")
        for snr in snr_levels:
            sig, gt, actual = generate_synthetic_recording(
                n_channels=1, duration_s=120.0, sample_rate=1000.0,
                n_slow_waves=15, n_ieds=0, snr=snr, seed=int(snr * 1000),
            )
            p = save_synthetic(output_dir / f"synthetic_snr{snr:.1f}.npz", sig, 1000.0, gt)

            pipe = Pipeline(
                source=FileSource(str(p)),
                modules=[
                    WaveletConvolution(freq_min=0.5, freq_max=30, n_freqs=10),
                    TargetWaveDetector(id="slow_wave", freq_range=(0.5, 2.0),
                                       target_phase=pi, phase_tolerance=0.3,
                                       amp_min=50.0, warmup_chunks=3),
                    StimTrigger(activation_detector_id="slow_wave",
                                inhibition_detector_id=None,
                                n_pulses=1, backoff_s=3.0),
                ],
                config=PipelineConfig(sample_rate=1000, n_channels=1, chunk_duration=0.5),
            )
            dets = pipe.run_offline()
            detections = [e for e in dets if e.event_type == EventType.SLOW_WAVE]
            sw = [e for e in gt if e.metadata.get("type") == "SW"]
            anns = [Annotation(timestamp=e.timestamp, channel=e.channel_id, event_type="SW") for e in sw]
            r = validate(detections, anns, time_tolerance=0.5)
            m = r.metrics
            print(f"{actual:6.1f} {m['precision']:6.3f} {m['recall']:6.3f} "
                  f"{m['f1']:6.3f} {m['true_positives']:4.0f} {m['false_positives']:4.0f} "
                  f"{m['false_negatives']:4.0f}")
        return

    pipeline = build_pipeline(args.config)

    if args.offline:
        events = pipeline.run_offline()
        logger.info("Detected %d events", len(events))
    else:
        logger.info("Running online (Ctrl+C to stop)...")
        try:
            pipeline.run_online()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()