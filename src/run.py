#!/usr/bin/env python3
"""Run the DNB pipeline from a YAML config file.

Usage:
    python run.py --config config.yaml
    python run.py --config config.yaml --offline
    python run.py --config config.yaml --validate annotations.csv
    python run.py --config config.yaml --snr-sweep

This is the main entry point for running pipelines without writing
Python code.  All parameters are read from the config file.
"""

import argparse
import logging
import sys
from pathlib import Path

import dnb
from dnb.config import build_pipeline, load_config, build_pipeline_config
from dnb.io.writer import ResultWriter
from dnb.logging_config import setup_logging

logger = logging.getLogger("dnb.run")


def main():
    parser = argparse.ArgumentParser(
        description="DNB pipeline runner — configure via YAML",
    )
    parser.add_argument(
        "--config", "-c", required=True,
        help="Path to YAML config file",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Run in offline (batch) mode on a file source",
    )
    parser.add_argument(
        "--validate", metavar="ANNOTATIONS_CSV",
        help="Validate detections against ground truth annotations CSV",
    )
    parser.add_argument(
        "--snr-sweep", action="store_true",
        help="Run synthetic validation at varying SNR levels",
    )
    parser.add_argument(
        "--output-dir", "-o", default="./output",
        help="Directory for output files (default: ./output)",
    )
    parser.add_argument(
        "--log-dir", default="./logs",
        help="Directory for log files (default: ./logs)",
    )
    args = parser.parse_args()

    log_path = setup_logging(log_dir=args.log_dir)
    logger.info("DNB v%s — config-driven runner", dnb.__version__)

    # --- SNR sweep mode ---
    if args.snr_sweep:
        cfg = load_config(args.config)
        val_cfg = cfg.get("validation", {})
        snr_levels = val_cfg.get("snr_levels", [1.0, 2.0, 3.0, 5.0, 10.0])

        from dnb.validation.synthetic import run_snr_sweep, save_debug_figures

        logger.info("Running SNR sweep: %s", snr_levels)
        results = run_snr_sweep(
            snr_levels=snr_levels,
            output_dir=args.output_dir,
        )

        try:
            paths = save_debug_figures(results, output_dir=args.output_dir)
            for p in paths:
                logger.info("Figure: %s", p)
        except Exception:
            logger.exception("Could not generate figures (matplotlib missing?)")

        print("\nSNR Sweep Results:")
        print(f"{'SNR':>6} {'Prec':>6} {'Recall':>6} {'F1':>6} {'TP':>4} {'FP':>4} {'FN':>4}")
        for r in results:
            print(f"{r.snr:6.1f} {r.precision:6.3f} {r.recall:6.3f} "
                  f"{r.f1:6.3f} {r.true_positives:4d} {r.false_positives:4d} "
                  f"{r.false_negatives:4d}")
        return

    # --- Build and run pipeline ---
    pipeline = build_pipeline(args.config)

    # Set up result writer
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    writer = ResultWriter(output_dir)
    pipeline.on_event(None, writer.on_event)

    if args.offline:
        logger.info("Running offline...")
        events = pipeline.run_offline()
        writer.save_events()
        logger.info("Detected %d events", len(events))

        # --- Ground truth validation ---
        if args.validate:
            from dnb.core.types import EventType
            from dnb.validation.ground_truth import load_annotations, validate

            cfg = load_config(args.config)
            val_cfg = cfg.get("validation", {})
            time_tol = val_cfg.get("time_tolerance_s", 0.05)

            annotations = load_annotations(args.validate)
            stim1_events = [e for e in events if e.event_type == EventType.STIM1]

            report = validate(
                stim1_events, annotations,
                time_tolerance=time_tol,
            )
            print(report.summary())
            report.save(output_dir / "validation_report.json")
            report.save_npz(output_dir / "validation_report.npz")
    else:
        logger.info("Running online (Ctrl+C to stop)...")
        try:
            pipeline.run_online()
        except KeyboardInterrupt:
            pass
        finally:
            writer.save_events()

    if log_path:
        print(f"\nLog file: {log_path}")


if __name__ == "__main__":
    main()
