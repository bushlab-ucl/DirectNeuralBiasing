#!/usr/bin/env python3
"""
DirectNeuralBiasing CLI Grid Search Tool
========================================

A command-line tool for running an exhaustive grid search to find optimal 
parameters for neural biasing applications.

USAGE:
    python grid_search_cli.py search [--patients 2,3,4,6,7] [--workers 5] [--metric f1] [--no-plots]
    python grid_search_cli.py analyze [--top 20] [--metric f1]
    python grid_search_cli.py best [--metric f1]
    python grid_search_cli.py summary

COMMANDS:
    search   - Run a full grid search over the defined parameter space.
    analyze  - Analyze results from the CSV and show top parameter combinations.
    best     - Display the best parameter set and its performance.
    summary  - Interactively browse detailed summaries of individual trials.

SEARCH OPTIONS:
    --patients   Comma-separated patient IDs to include (default: 2,3,4,6,7).
    --workers    Number of parallel workers for patient processing (default: 4).
    --metric     Optimization objective to determine the 'best' trial (default: f1).
                 • f1        - Balance precision and recall (traditional ML metric).
                 • precision - Minimize false positives (recommended for clinical use).
                 • recall    - Minimize false negatives.
                 • balanced  - Simple average of precision and recall.
    --no-plots   Skip generating event plots for the top trials to speed up execution.

PARAMETER GRID:
    The search space is defined in the `PARAM_GRID` dictionary within this script.

OUTPUT FILES:
    results/grid_search_summary.csv     - Complete results for every parameter combination.
    results/best_grid_params.json       - The best parameter configuration found.
    results/trial_summaries/*.json      - Detailed per-trial analysis.
    plots/trial_*/patient_*/*.png       - Event plots for the top N trials.
"""

import argparse
import json
import os
import tempfile
import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd
import yaml
import matplotlib.pyplot as plt
import scipy.signal as sig
from tqdm.auto import tqdm

# Assuming direct_neural_biasing library is in the same directory or installed
try:
    import direct_neural_biasing as dnb
except ImportError:
    print("Error: The 'direct_neural_biasing' library is required.")
    print("Please ensure the library is installed or accessible in your Python path.")
    exit(1)

# ───────────────────────── Configuration ───────────────────────────

# --- Core Settings ---
DATA_FS = 30_000.0
TOLERANCE_MS = 125
CTX_MS = 1000  # ± ms context for plots
DATA_DIR = Path("data")
RESULTS_DIR = Path("results")
PLOTS_DIR = Path("plots")

# --- Parameter Grid for Exhaustive Search ---
# This dictionary defines the search space for the grid search.
PARAM_GRID = {
    "z_score_threshold": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
    "check_sinusoidness": [True, False],
    "f_low": [0.25],
    "f_high": [4.0],
    "min_wave_ms": [250.0],
    "max_wave_ms": [1000],
    "z_ied_threshold": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
    "refrac_ms": [2000.0, 2500.0, 3000.0],
    "sinusoidness_threshold": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9] # Only used when check_sinusoidness is True
}

# PARAM_GRID = {
#     "z_score_threshold": [2.5, 3.0], # Varying this parameter for the test
#     "check_sinusoidness": [False],
#     "f_low": [0.25],
#     "f_high": [4.0],
#     "min_wave_ms": [250.0],
#     "max_wave_ms": [1200],
#     "z_ied_threshold": [3.0],
#     "refrac_ms": [2500.0],
#     "sinusoidness_threshold": [0.0] # Not used when check_sinusoidness is False
# }

# --- Patient Metadata ---
PATIENT_METADATA = {
    2: {'mrk_fs': 512.0},
    3: {'mrk_fs': 1024.0},
    4: {'mrk_fs': 1024.0},
    6: {'mrk_fs': 1024.0},
    7: {'mrk_fs': 1024.0},
}

# --- Metrics ---
OPTIMIZATION_METRICS = {
    "f1": "F1 Score (harmonic mean of precision & recall)",
    "precision": "Precision (minimizes false positives)",
    "recall": "Recall (minimizes false negatives)",
    "balanced": "Balanced (precision + recall)/2"
}
DEFAULT_METRIC = "f1"

# ────────────────────────── Data Loading ───────────────────────────

def _parse_mrk(p: Path) -> np.ndarray:
    """Parse marker file and return marker indices."""
    with p.open() as f:
        next(f)  # Skip header
        return np.asarray([int(l.split()[0]) for l in f if l.split()], dtype=int)

def _mrk_to_30k(idx: np.ndarray, mrk_fs: float) -> np.ndarray:
    """Convert marker indices from a given sample rate to 30kHz."""
    return (idx * DATA_FS / mrk_fs).astype(int)

def load_patient_data_for_eval(pid: int) -> Tuple[np.ndarray, Dict[int, int]]:
    """Load full patient EEG data and ground truth markers."""
    sig_full = np.load(DATA_DIR / f"Patient{pid}EEG.npy")[0]
    
    try:
        mrk_fs = PATIENT_METADATA[pid]['mrk_fs']
    except KeyError:
        raise ValueError(f"Marker sample rate for Patient {pid} not defined in PATIENT_METADATA.")

    mrk = _parse_mrk(DATA_DIR / f"Patient{pid:02d}_OfflineMrk.mrk")
    gt = dict(zip(_mrk_to_30k(mrk, mrk_fs), mrk))
    
    return sig_full, gt

# ───────────────────── Configuration Generation ────────────────────

BASE_CFG = {
    "processor": {"verbose": False, "fs": DATA_FS, "channel": 1, "enable_debug_logging": False},
    "filters": {
        "bandpass_filters": [
            {"id": "slow_wave_filter", "f_low": 0.25, "f_high": 4.0},
            {"id": "ied_filter", "f_low": 80.0, "f_high": 120.0}
        ]
    },
    "detectors": {
        "wave_peak_detectors": [
            {"id": "slow_wave_detector", "filter_id": "slow_wave_filter", "z_score_threshold": 2.5, "sinusoidness_threshold": 0.7, "check_sinusoidness": True, "wave_polarity": "downwave", "min_wave_length_ms": 250.0, "max_wave_length_ms": 1000.0},
            {"id": "ied_detector", "filter_id": "ied_filter", "z_score_threshold": 3.0, "sinusoidness_threshold": 0.0, "check_sinusoidness": False, "wave_polarity": "upwave"}
        ]
    },
    "triggers": {
        "pulse_triggers": [{"id": "pulse_trigger", "activation_detector_id": "slow_wave_detector", "inhibition_detector_id": "ied_detector", "inhibition_cooldown_ms": 2500.0, "pulse_cooldown_ms": 2500.0}]
    }
}

def make_cfg(params: dict) -> dict:
    """Generate a full configuration dictionary from a set of parameters."""
    cfg = deepcopy(BASE_CFG)
    sw_det = cfg["detectors"]["wave_peak_detectors"][0]
    ied_det = cfg["detectors"]["wave_peak_detectors"][1]
    trigger = cfg["triggers"]["pulse_triggers"][0]
    sw_filter = cfg["filters"]["bandpass_filters"][0]

    sw_det["z_score_threshold"] = params["z_score_threshold"]
    sw_det["sinusoidness_threshold"] = params["sinusoidness_threshold"]
    sw_det["check_sinusoidness"] = params["check_sinusoidness"]
    sw_filter["f_low"] = params["f_low"]
    sw_filter["f_high"] = params["f_high"]
    sw_det["min_wave_length_ms"] = params["min_wave_ms"]
    sw_det["max_wave_length_ms"] = params["max_wave_ms"]
    ied_det["z_score_threshold"] = params["z_ied_threshold"]
    trigger["inhibition_cooldown_ms"] = params["refrac_ms"]
    trigger["pulse_cooldown_ms"] = params["refrac_ms"]
    
    return cfg

# ────────────────────────── Evaluation ─────────────────────────────

def eval_patient(proc, sig_data, gt_map, desc: str, position: int = 0):
    """Evaluate a processor on a signal against ground truth markers."""
    tol = int(TOLERANCE_MS / 1000 * DATA_FS)
    gt_idx = np.fromiter(gt_map.keys(), dtype=int)
    matched = np.zeros(gt_idx.size, dtype=bool)
    tp, fp = 0, 0
    events = []
    
    # Use a tqdm progress bar for chunk processing
    bar = tqdm(range(0, len(sig_data), 4096), leave=False, desc=desc, unit="chunk", position=position, ncols=80)

    for off in bar:
        out, _ = proc.run_chunk(sig_data[off:off+4096].tolist())
        for o in out:
            if o.get("detectors:slow_wave_detector:detected") != 1:
                continue
            
            det = int(o.get("detectors:slow_wave_detector:wave_start_index", -1))
            if gt_idx.size > 0:
                i = np.abs(gt_idx - det).argmin()
                if abs(gt_idx[i] - det) <= tol and not matched[i]:
                    matched[i] = True
                    tp += 1
                    events.append(("TP", det, gt_idx[i]))
                else:
                    fp += 1
                    events.append(("FP", det, None))
            else: # No ground truth events, all detections are FPs
                fp += 1
                events.append(("FP", det, None))

        bar.set_postfix(tp=tp, fp=fp)
        
    fn_idx = gt_idx[~matched]
    events.extend([("FN", None, x) for x in fn_idx])
    bar.close()
    
    return tp, fp, len(fn_idx), events

# ───────────────────────── Worker Function ─────────────────────────

def process_patient_task(args: Tuple[int, int, str, int]) -> Dict[str, Any]:
    """Worker function to process a single patient for a given trial."""
    trial_num, pid, cfg_path, position = args
    
    proc = dnb.PySignalProcessor.from_config_file(cfg_path)
    sig, gt = load_patient_data_for_eval(pid)
    desc = f"P{pid} (Trial {trial_num})"
    
    tp, fp, fn, events = eval_patient(proc, sig, gt, desc, position)
    
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0
    
    return {
        'pid': pid, 'tp': tp, 'fp': fp, 'fn': fn, 
        'prec': prec, 'rec': rec, 'events': events, 'gt_total': len(gt)
    }

# ────────────────────────── Plotting ───────────────────────────────

def plot_event(sig_raw: np.ndarray, center: int, gt_idx_all: np.ndarray, 
               title: str, save_path: Path, f_low: float, f_high: float):
    """Plot raw and filtered signal around an event and save to file."""
    if center is None or center >= len(sig_raw): return

    ctx = int(CTX_MS / 1000 * DATA_FS)
    L, R = max(0, center - ctx), min(len(sig_raw), center + ctx)
    
    if R - L < 20: return # Skip if window is too small

    # Design Butterworth band-pass filter
    nyq = 0.5 * DATA_FS
    try:
        b, a = sig.butter(N=2, Wn=[f_low / nyq, f_high / nyq], btype="bandpass", analog=False)
        filt = sig.filtfilt(b, a, sig_raw[L:R])
    except ValueError: # Handle cases where filter design fails (e.g., bad frequencies)
        filt = np.full(R - L, np.nan)

    t = (np.arange(L, R) - center) / DATA_FS * 1000  # ms axis
    
    plt.figure(figsize=(12, 4))
    plt.plot(t, sig_raw[L:R], color="lightgray", lw=0.8, label="Raw Signal", alpha=0.7)
    if not np.all(np.isnan(filt)):
        plt.plot(t, filt, color="C0", lw=1.2, label=f"Filtered ({f_low}-{f_high}Hz)")
    
    plt.axvline(0, c="r", lw=2, label="Detection/Event Center")
    
    # Show ground truth markers within the window
    in_win = (gt_idx_all >= L) & (gt_idx_all < R)
    if np.any(in_win):
        plt.vlines((gt_idx_all[in_win] - center) / DATA_FS * 1000,
                   *plt.ylim(), colors="green", linestyles="--", linewidths=2, label="GT Markers")
    
    plt.title(title, fontsize=14, fontweight='bold')
    plt.xlabel("Time (ms)")
    plt.ylabel("Amplitude")
    plt.legend(loc="upper right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()

def create_event_plots(trial_number: int, params: dict, results_per_patient: list):
    """Create plots for all events in a given trial."""
    combo_dir = PLOTS_DIR / f"trial_{trial_number:05d}"
    
    with (combo_dir / "parameters.json").open('w') as f:
        json.dump(params, f, indent=2)
    
    for result in results_per_patient:
        pid, events = result['pid'], result['events']
        sig_full, gt_map_full = load_patient_data_for_eval(pid)
        gt_idx_full = np.fromiter(gt_map_full.keys(), dtype=int)
        
        patient_dir = combo_dir / f"patient_{pid}"
        
        f_low, f_high = params.get('f_low', 0.25), params.get('f_high', 4.0)

        # Plot a sample of events to avoid excessive file generation
        tp_events = [(e[1], e[2]) for e in events if e[0] == 'TP'][:10] # Max 10 plots
        fp_events = [e[1] for e in events if e[0] == 'FP'][:10]
        fn_events = [e[2] for e in events if e[0] == 'FN'][:10]

        for i, (det, gt) in enumerate(tp_events):
            plot_event(sig_full, det, gt_idx_full, f"TP #{i+1} - P{pid} T{trial_number}", patient_dir / f"TP_{i+1:03d}.png", f_low, f_high)
        for i, det in enumerate(fp_events):
            plot_event(sig_full, det, gt_idx_full, f"FP #{i+1} - P{pid} T{trial_number}", patient_dir / f"FP_{i+1:03d}.png", f_low, f_high)
        for i, gt in enumerate(fn_events):
            plot_event(sig_full, gt, gt_idx_full, f"FN #{i+1} - P{pid} T{trial_number}", patient_dir / f"FN_{i+1:03d}.png", f_low, f_high)
            
    print(f"    Plots saved for Trial {trial_number} (sample of up to 10 per category).")

# ───────────────────────── Summary Generation ──────────────────────

def create_trial_summary(trial_number: int, params: dict, results_per_patient: list):
    """Create a detailed JSON summary file for a single trial."""
    summary_dir = RESULTS_DIR / "trial_summaries"
    summary_dir.mkdir(exist_ok=True)
    summary_file = summary_dir / f"trial_{trial_number:05d}_summary.json"
    
    patient_details = {}
    for result in results_per_patient:
        pid = result['pid']
        patient_details[pid] = {
            'tp_count': int(result['tp']), 'fp_count': int(result['fp']),
            'fn_count': int(result['fn']), 'gt_total': int(result['gt_total']),
            'precision': float(result['prec']), 'recall': float(result['rec']),
        }
    
    total_tp = sum(r['tp'] for r in results_per_patient)
    total_fp = sum(r['fp'] for r in results_per_patient)
    total_fn = sum(r['fn'] for r in results_per_patient)
    
    prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
    
    summary_data = {
        'trial_number': int(trial_number),
        'parameters': params,
        'overall_statistics': {
            'true_positives': int(total_tp), 'false_positives': int(total_fp),
            'false_negatives': int(total_fn), 'precision': float(prec),
            'recall': float(rec), 'f1_score': float(f1),
        },
        'patient_details': patient_details,
    }
    
    with summary_file.open('w') as f:
        json.dump(summary_data, f, indent=2)

# ───────────────────────── Grid Search Execution ───────────────────

def run_grid_search(patient_ids: List[int], max_workers: int, create_plots: bool, metric: str, start_trial: int = 0):
    """Run the full grid search for parameter optimization."""
    # Generate all parameter combinations with conditional logic for sinusoidness
    param_combinations = []
    
    # Create a grid for all other parameters
    other_params_grid = {k: v for k, v in PARAM_GRID.items() if k != 'sinusoidness_threshold'}
    keys, values = zip(*other_params_grid.items())
    
    for v in itertools.product(*values):
        base_params = dict(zip(keys, v))
        
        # Now handle the conditional parameter
        if base_params['check_sinusoidness']:
            # If checking, iterate through all sinusoidness thresholds
            for st in PARAM_GRID['sinusoidness_threshold']:
                new_params = base_params.copy()
                new_params['sinusoidness_threshold'] = st
                param_combinations.append(new_params)
        else:
            # If not checking, set threshold to 0.0 and add only one combo
            new_params = base_params.copy()
            new_params['sinusoidness_threshold'] = 0.0
            param_combinations.append(new_params)

    total_trials = len(param_combinations)

    # Skip trials before start_trial
    if start_trial > 0:
        param_combinations = param_combinations[start_trial:]
        print(f"Resuming from trial {start_trial}")

    print("=" * 60)
    print("Starting Grid Search")
    print(f"Testing on patients: {patient_ids}")
    print(f"Using {max_workers} parallel workers")
    print(f"Total parameter combinations: {total_trials}")
    if start_trial > 0:
        print(f"Starting from trial: {start_trial}")
        print(f"Remaining trials to process: {len(param_combinations)}")
    print("=" * 60)

    all_results = []
    
    # Load existing results if resuming
    summary_csv_path = RESULTS_DIR / "grid_search_summary.csv"
    if start_trial > 0 and summary_csv_path.exists():
        existing_df = pd.read_csv(summary_csv_path)
        all_results = existing_df.to_dict('records')
        print(f"Loaded {len(all_results)} existing results")

    main_bar = tqdm(enumerate(param_combinations, start=start_trial), 
                   total=total_trials, 
                   initial=start_trial,
                   desc="Grid Search Progress")

    for trial_num, params in main_bar:
        cfg = make_cfg(params)
        with tempfile.NamedTemporaryFile(mode='w+', suffix=".yaml", delete=False) as tmp:
            yaml.dump(cfg, tmp)
            cfg_path = tmp.name
        
        tasks = [(trial_num, pid, cfg_path, i + 1) for i, pid in enumerate(patient_ids)]
        patient_results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {executor.submit(process_patient_task, task): task for task in tasks}
            for future in as_completed(future_to_task):
                try:
                    patient_results.append(future.result())
                except Exception as e:
                    task = future_to_task[future]
                    print(f"\nError processing patient {task[1]} in trial {trial_num}: {e}")

        os.remove(cfg_path)
        patient_results.sort(key=lambda x: x['pid'])
        
        # Aggregate and store results for this trial
        total_tp = sum(r['tp'] for r in patient_results)
        total_fp = sum(r['fp'] for r in patient_results)
        total_fn = sum(r['fn'] for r in patient_results)
        
        prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
        balanced = (prec + rec) / 2

        trial_result = {
            'trial': trial_num, 'tp': total_tp, 'fp': total_fp, 'fn': total_fn,
            'precision': prec, 'recall': rec, 'f1': f1, 'balanced': balanced,
            **params
        }
        all_results.append(trial_result)

        # Create detailed summary for this trial
        create_trial_summary(trial_num, params, patient_results)
        
        # Save results after each trial (for resumability)
        df_results = pd.DataFrame(all_results)
        df_results.to_csv(summary_csv_path, index=False, float_format="%.4f")
        
        main_bar.set_postfix(tp=total_tp, fp=total_fp, fn=total_fn, f1=f1)

    # --- Finalization ---
    print("\nGrid search completed!")
    df_results = pd.DataFrame(all_results)
    
    # Save all results to a single CSV
    summary_csv_path = RESULTS_DIR / "grid_search_summary.csv"
    df_results.to_csv(summary_csv_path, index=False, float_format="%.4f")
    print(f"Full grid search summary saved to {summary_csv_path}")

    # Create plots for the top N trials
    if create_plots and not df_results.empty:
        print("\nGenerating plots for top 10 trials...")
        top_10_trials = df_results.sort_values(by=metric, ascending=False).head(10)
        
        for _, row in top_10_trials.iterrows():
            trial_num = int(row['trial'])
            # We need to re-run the trial to get the event details for plotting
            # This is a trade-off for not storing all event data in memory
            # A bit inefficient but necessary for this structure
            print(f"  Re-evaluating trial {trial_num} to generate plots...")
            params = row[list(PARAM_GRID.keys())].to_dict()
            
            cfg = make_cfg(params)
            with tempfile.NamedTemporaryFile(mode='w+', suffix=".yaml", delete=False) as tmp:
                yaml.dump(cfg, tmp)
                cfg_path = tmp.name

            tasks = [(trial_num, pid, cfg_path, i + 1) for i, pid in enumerate(patient_ids)]
            patient_results_for_plot = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for res in executor.map(process_patient_task, tasks):
                    patient_results_for_plot.append(res)
            
            os.remove(cfg_path)
            create_event_plots(trial_num, params, patient_results_for_plot)

# ────────────────────────── Analysis & CLI ─────────────────────────

def analyze_results(top_n: int, metric: str):
    """Analyze grid search results from the CSV file."""
    summary_csv_path = RESULTS_DIR / "grid_search_summary.csv"
    if not summary_csv_path.exists():
        print(f"Results file not found: {summary_csv_path}. Run a search first.")
        return

    df = pd.read_csv(summary_csv_path)
    if df.empty:
        print("Results file is empty.")
        return

    df_sorted = df.sort_values(by=metric, ascending=False, na_position='last')
    
    print(f"\nTOP {top_n} TRIALS (sorted by '{metric}')\n")
    
    display_cols = ['trial', 'tp', 'fp', 'fn', 'precision', 'recall', 'f1'] + list(PARAM_GRID.keys())
    # Ensure all display columns exist in the dataframe
    display_cols = [col for col in display_cols if col in df_sorted.columns]
    
    print(df_sorted[display_cols].head(top_n).to_string(float_format="%.3f", index=False))

def show_best_params(metric: str):
    """Show the best parameter set from the grid search results."""
    summary_csv_path = RESULTS_DIR / "grid_search_summary.csv"
    best_json_path = RESULTS_DIR / "best_grid_params.json"
    if not summary_csv_path.exists():
        print(f"Results file not found: {summary_csv_path}. Run a search first.")
        return

    df = pd.read_csv(summary_csv_path)
    if df.empty:
        print("Results file is empty.")
        return

    best_trial = df.sort_values(by=metric, ascending=False).iloc[0]
    best_params = best_trial[list(PARAM_GRID.keys())].to_dict()

    with best_json_path.open("w") as f:
        json.dump(best_params, f, indent=2)

    print(f"\nBEST PARAMETER SET (saved to {best_json_path})")
    print(f"Sorted by: {metric}")
    print("-" * 40)
    print(f"  Trial Number: {int(best_trial['trial'])}")
    print(f"  F1 Score:  {best_trial['f1']:.4f}")
    print(f"  Precision: {best_trial['precision']:.4f}")
    print(f"  Recall:    {best_trial['recall']:.4f}")
    print(f"  TP: {int(best_trial['tp'])}, FP: {int(best_trial['fp'])}, FN: {int(best_trial['fn'])}")
    print("\nParameters:")
    print(json.dumps(best_params, indent=2))

def show_trial_summaries():
    """Interactively browse detailed trial summaries from JSON files."""
    summary_dir = RESULTS_DIR / "trial_summaries"
    if not summary_dir.exists():
        print("No trial summaries found. Run a search first.")
        return

    summary_files = sorted(summary_dir.glob("trial_*_summary.json"))
    if not summary_files:
        print("No summary files found in the directory.")
        return

    print(f"\nFound {len(summary_files)} trial summaries:")
    for i, file_path in enumerate(summary_files):
        with file_path.open() as f:
            data = json.load(f)
        stats = data['overall_statistics']
        print(f"{i+1:3d}. Trial {data['trial_number']:<5} | F1: {stats['f1_score']:.3f}, P: {stats['precision']:.3f}, R: {stats['recall']:.3f}")

    try:
        choice = input(f"\nEnter number (1-{len(summary_files)}) to view details, or Enter to exit: ").strip()
        if not choice: return
        
        idx = int(choice) - 1
        if 0 <= idx < len(summary_files):
            with summary_files[idx].open() as f:
                print("\n" + f.read())
        else:
            print("Invalid choice.")
    except (ValueError, KeyboardInterrupt):
        print("\nExiting.")

def main():
    """Main function to parse CLI arguments and run commands."""
    parser = argparse.ArgumentParser(description="DirectNeuralBiasing Grid Search CLI", formatter_class=argparse.RawTextHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", help="Available commands", required=True)
    
    # --- Search Command ---
    p_search = subparsers.add_parser("search", help="Run a full grid search.")
    p_search.add_argument("--patients", default="2,3,4,6,7", help="Comma-separated patient IDs.")
    p_search.add_argument("--workers", type=int, default=4, help="Number of parallel workers.")
    p_search.add_argument("--no-plots", action="store_true", help="Skip generating plots for top trials.")
    p_search.add_argument("--metric", default=DEFAULT_METRIC, choices=OPTIMIZATION_METRICS.keys(), help=f"Metric to sort results by (default: {DEFAULT_METRIC}).")
    p_search.add_argument("--start-trial", type=int, default=0, help="Trial number to start from (for resuming interrupted searches).")

    # --- Analyze Command ---
    p_analyze = subparsers.add_parser("analyze", help="Analyze results and show top trials.")
    p_analyze.add_argument("--top", type=int, default=20, help="Number of top results to show.")
    p_analyze.add_argument("--metric", default=DEFAULT_METRIC, choices=OPTIMIZATION_METRICS.keys(), help=f"Metric to sort results by (default: {DEFAULT_METRIC}).")

    # --- Best Command ---
    p_best = subparsers.add_parser("best", help="Show the single best parameter set.")
    p_best.add_argument("--metric", default=DEFAULT_METRIC, choices=OPTIMIZATION_METRICS.keys(), help=f"Metric to determine the best trial (default: {DEFAULT_METRIC}).")

    # --- Summary Command ---
    subparsers.add_parser("summary", help="Interactively browse detailed trial summaries.")


    args = parser.parse_args()
    
    # Ensure output directories exist
    RESULTS_DIR.mkdir(exist_ok=True)
    PLOTS_DIR.mkdir(exist_ok=True)
    
    if args.command == "search":
        patient_ids = [int(x.strip()) for x in args.patients.split(",")]
        run_grid_search(patient_ids, args.workers, not args.no_plots, args.metric, args.start_trial)
    elif args.command == "analyze":
        analyze_results(args.top, args.metric)
    elif args.command == "best":
        show_best_params(args.metric)
    elif args.command == "summary":
        show_trial_summaries()

if __name__ == "__main__":
    main()
