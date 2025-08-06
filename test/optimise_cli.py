#!/usr/bin/env python3
#!/usr/bin/env python3
"""
DirectNeuralBiasing CLI Optuna Search Tool
==========================================

A command-line tool for running parameter optimization using Optuna with progressive 
data fractions and configurable optimization metrics for neural biasing applications.

USAGE:
    python optimise_cli.py search [--patients 2,3,4,6,7] [--workers 5] [--trials 100] [--metric precision] [--no-plots]
    python optimise_cli.py analyze [--top 20]
    python optimise_cli.py best
    python optimise_cli.py summary

COMMANDS:
    search   - Run Optuna hyperparameter search with progressive data evaluation
    analyze  - Analyze results and show top parameter combinations by chosen metric
    best     - Display the best parameter set and performance breakdown
    summary  - Browse detailed summaries of individual trials interactively

SEARCH OPTIONS:
    --patients   Comma-separated patient IDs to include (default: 2,3,4,6,7)
    --workers    Number of parallel workers for patient processing (default: 4)
    --trials     Number of Optuna trials to run (default: 100)
    --metric     Optimization objective (default: precision)
                 • precision - Minimize false positives (recommended for clinical use)
                 • recall    - Minimize false negatives 
                 • f1        - Balance precision and recall (traditional ML metric)
                 • balanced  - Simple average of precision and recall
    --no-plots   Skip generating event plots for faster execution

OPTIMIZATION STRATEGY:
    Uses progressive data fractions (10%, 25%, 100%) with Optuna's MedianPruner 
    to efficiently explore hyperparameter space. Trials performing poorly on 
    small data fractions are pruned early to focus computational resources on 
    promising parameter combinations.

OUTPUT FILES:
    results/optuna_study.db              - SQLite database with all trial data
    results/optuna_study_full_summary.csv - Complete trial results and metrics
    results/trial_summaries/*.json      - Detailed per-trial analysis
    results/best_optuna_params.json     - Best parameter configuration
    plots/trial_*/patient_*/*.png        - Event plots for top trials

EXAMPLES:
    # Optimize for minimal false positives (clinical deployment)
    python optimise_cli.py search --metric precision --trials 200
    
    # Quick test run on subset of patients
    python optimise_cli.py search --patients 2,3 --trials 50 --no-plots
    
    # Optimize for maximal sensitivity (research applications)  
    python optimise_cli.py search --metric recall --workers 8
    
    # View top 10 results
    python optimise_cli.py analyze --top 10
    
    # Get best parameters for deployment
    python optimise_cli.py best

PATIENT DATA REQUIREMENTS:
    data/Patient{N}EEG.npy              - EEG signal data (30kHz sampling)
    data/Patient{N:02d}_OfflineMrk.mrk  - Ground truth markers
    
    Note: Patient 2 uses 512Hz markers, patients 3,4,6,7 use 1024Hz markers
"""

import argparse
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml
import matplotlib.pyplot as plt
import scipy.signal as sig
from tqdm.auto import tqdm

import direct_neural_biasing as dnb
import optuna # New import for Optuna

# ─────────────────────—— Configuration ─────────────────────────────────────
# This will define the search space within Optuna's objective function
# DEFAULT_PARAM_GRID is now effectively replaced by Optuna's suggestion methods.

DATA_FS = 30_000.0
TOLERANCE_MS = 125
CTX_MS = 1000  # ± ms context for plots
DATA_DIR = Path("data")
RESULTS_DIR = Path("results")
PLOTS_DIR = Path("plots")
RESULTS_DIR.mkdir(exist_ok=True)
PLOTS_DIR.mkdir(exist_ok=True)

# NEW: Define patient-specific metadata
PATIENT_METADATA = {
    2: {'mrk_fs': 512.0},
    3: {'mrk_fs': 1024.0},
    4: {'mrk_fs': 1024.0},
    6: {'mrk_fs': 1024.0},
    7: {'mrk_fs': 1024.0},
}

# Define the data fractions for progressive evaluation
# DATA_FRACTIONS = [0.1, 0.25, 1.0]
DATA_FRACTIONS = [1.0]

# NEW: Optimization metrics configuration
OPTIMIZATION_METRICS = {
    "f1": "F1 Score (harmonic mean of precision & recall)",
    "precision": "Precision (minimizes false positives)", 
    "recall": "Recall (minimizes false negatives)",
    "balanced": "Balanced (precision + recall)/2"
}

DEFAULT_METRIC = "f1"  # Prioritize minimizing false positives

# Thread-safe CSV writer
csv_lock = threading.Lock()
# Thread-safe for Optuna study storage
storage_lock = threading.Lock()

# Global list to store all results for detailed summary creation later
# In an Optuna context, this would typically be handled by the database storage
# but for consistent summary generation, we can gather here.
all_trial_results = []
trial_results_lock = threading.Lock()


# ─────────────────────—— Data Loading ──────────────────────────────────────
def _parse_mrk(p: Path):
    """Parse marker file and return marker indices."""
    with p.open() as f:
        next(f)  # Skip header
        return np.asarray([int(l.split()[0]) for l in f if l.split()], int)

# UPDATED: Make the function generic
def _mrk_to_30k(idx: np.ndarray, mrk_fs: float):
    """Convert marker indices from a given sample rate to 30kHz."""
    return (idx * DATA_FS / mrk_fs).astype(int)

# UPDATED: This function now uses the metadata dictionary
def load_patient_data_for_eval(pid: int, frac: float) -> Tuple[np.ndarray, Dict[int, int]]:
    """Load patient EEG data and ground truth markers for a given fraction."""
    sig_full = np.load(DATA_DIR / f"Patient{pid}EEG.npy")[0]
    sig_slice = sig_full[: int(len(sig_full) * frac)]

    # ---> THE FIX <---
    # Look up the correct marker sample rate for this patient
    try:
        mrk_fs = PATIENT_METADATA[pid]['mrk_fs']
    except KeyError:
        raise ValueError(f"Marker sample rate for Patient {pid} not defined in PATIENT_METADATA.")

    mrk = _parse_mrk(DATA_DIR / f"Patient{pid:02d}_OfflineMrk.mrk")

    # Use the patient-specific sample rate for conversion
    gt = dict(zip(_mrk_to_30k(mrk, mrk_fs), mrk))
    gt = {k: v for k, v in gt.items() if k < len(sig_slice)}  # Drop markers beyond slice

    return sig_slice, gt


# ─────────────────────—— Configuration Generation ──────────────────────────
BASE_CFG = {
    "processor": {
        "verbose": False,
        "fs": DATA_FS,
        "channel": 1,
        "enable_debug_logging": False
    },
    "filters": {
        "bandpass_filters": [
            {"id": "slow_wave_filter", "f_low": 0.25, "f_high": 4.0},
            {"id": "ied_filter", "f_low": 80.0, "f_high": 120.0}
        ]
    },
    "detectors": {
        "wave_peak_detectors": [
            {
                "id": "slow_wave_detector",
                "filter_id": "slow_wave_filter",
                "z_score_threshold": 2.5,
                "sinusoidness_threshold": 0.7,
                "check_sinusoidness": True,
                "wave_polarity": "downwave",
                "min_wave_length_ms": 250.0,
                "max_wave_length_ms": 1000.0
            },
            {
                "id": "ied_detector",
                "filter_id": "ied_filter",
                "z_score_threshold": 3.0,
                "sinusoidness_threshold": 0.0,
                "check_sinusoidness": False,
                "wave_polarity": "upwave"
            }
        ]
    },
    "triggers": {
        "pulse_triggers": [{
            "id": "pulse_trigger",
            "activation_detector_id": "slow_wave_detector",
            "inhibition_detector_id": "ied_detector",
            "inhibition_cooldown_ms": 2500.0,
            "pulse_cooldown_ms": 2500.0 # This was missing in the original BASE_CFG in the paste
        }]
    }
}

def make_cfg(params: dict) -> dict:
    """Generate configuration from parameter dictionary."""
    cfg = deepcopy(BASE_CFG)
    det = cfg["detectors"]["wave_peak_detectors"][0] # Slow wave detector
    ied_det = cfg["detectors"]["wave_peak_detectors"][1] # IED detector
    trigger = cfg["triggers"]["pulse_triggers"][0] # Pulse trigger
    
    for k, v in params.items():
        if k == "z_score_threshold":
            det["z_score_threshold"] = v
        elif k == "sinusoidness_threshold":
            det["sinusoidness_threshold"] = v
        elif k == "check_sinusoidness":
            det["check_sinusoidness"] = v
        elif k == "f_low":
            cfg["filters"]["bandpass_filters"][0]["f_low"] = v
        elif k == "f_high":
            cfg["filters"]["bandpass_filters"][0]["f_high"] = v
        elif k == "min_wave_ms":
            det["min_wave_length_ms"] = v
        elif k == "max_wave_ms":
            det["max_wave_length_ms"] = v
        elif k == "z_ied_threshold":
            ied_det["z_score_threshold"] = v
        elif k == "refrac_ms":
            trigger["inhibition_cooldown_ms"] = v
            trigger["pulse_cooldown_ms"] = v # Assuming both cooldowns are linked to refrac_ms
    
    return cfg

# ─────────────────────—— Evaluation ────────────────────────────────────────
def eval_patient(proc, sig_data, gt_map, desc:str, position:int=0):
    tol = int(TOLERANCE_MS/1000*DATA_FS)
    gt_idx = np.fromiter(gt_map.keys(), int)
    matched = np.zeros(gt_idx.size,bool)
    tp=fp=0; events=[]
    bar = tqdm(range(0,len(sig_data),4096), leave=False, desc=desc, unit="chunk", position=position)

    for off in bar:
        out,_ = proc.run_chunk(sig_data[off:off+4096].tolist())
        for o in out:
            if o.get("detectors:slow_wave_detector:detected")!=1: continue
            det = int(o.get("detectors:slow_wave_detector:wave_start_index",-1))
            i = int(np.abs(gt_idx-det).argmin()) if gt_idx.size else None
            if i is not None and abs(gt_idx[i]-det)<=tol and not matched[i]:
                matched[i]=True; tp+=1; events.append(("TP",det,gt_idx[i]))
            else:
                fp+=1; events.append(("FP",det,None))
        bar.set_postfix(tp=tp, fp=fp)
    fn_idx = gt_idx[~matched]
    events.extend([("FN",None,x) for x in fn_idx])
    bar.close()
    return tp,fp,len(fn_idx),events

# ─────────────────────—— Worker Function ───────────────────────────────────
def process_patient_for_optuna(args):
    """Worker function to process a single patient for Optuna trials."""
    trial_number, params, pid, cfg_path, position, fraction = args
    
    # Create processor from config
    proc = dnb.PySignalProcessor.from_config_file(cfg_path)
    
    # Load patient data for the specific fraction
    sig, gt = load_patient_data_for_eval(pid, fraction)
    desc = f"P{pid} Trial{trial_number}"
    
    # Evaluate
    tp, fp, fn, events = eval_patient(proc, sig, gt, desc, position)
    
    # Calculate metrics
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    
    return {
        'trial_number': trial_number,
        'params': params,
        'pid': pid,
        'tp': tp,
        'fp': fp,
        'fn': fn,
        'prec': prec,
        'rec': rec,
        'events': events,
        'gt_total': len(gt),
        'fraction': fraction
    }

# ─────────────────────—— Plotting Functions ───────────────────────────────
def plot_event(sig_raw: np.ndarray, center: int, gt_idx_all: np.ndarray, 
               title: str, save_path: Path, f_low: float = 0.25, f_high: float = 4.0):
    """
    Plot raw and filtered signal around an event and save to file.
    """
    if center is None or center >= len(sig_raw):
        return
    
    ctx = int(CTX_MS / 1000 * DATA_FS)
    L, R = max(0, center - ctx), min(len(sig_raw), center + ctx)
    
    if R - L < 10 or np.allclose(sig_raw[L:R], 0, atol=1e-12):
        return
    
    # Design Butterworth band-pass filter
    nyq = 0.5 * DATA_FS
    b, a = sig.butter(
        N=2,
        Wn=[f_low / nyq, f_high / nyq],
        btype="bandpass",
        analog=False,
    )
    
    # Apply filter, handle short segments
    signal_chunk = sig_raw[L:R]
    if len(signal_chunk) > max(len(b), len(a)): # Ensure chunk is long enough for filtfilt
        filt = sig.filtfilt(b, a, signal_chunk)
    else:
        filt = np.full_like(signal_chunk, np.nan) # Set to NaN if too short

    t = (np.arange(L, R) - center) / DATA_FS * 1000  # ms axis
    
    plt.figure(figsize=(12, 4))
    plt.plot(t, sig_raw[L:R], color="lightgray", lw=0.8, label="raw", alpha=0.7)
    if not np.all(np.isnan(filt)): # Only plot if filtered signal is not all NaNs
        plt.plot(t, filt, color="C0", lw=1.2, label=f"filtered ({f_low}-{f_high}Hz)")
    
    plt.axvline(0, c="r", lw=2, label="detection/event")
    
    # GT markers inside window
    in_win = (gt_idx_all >= L) & (gt_idx_all < R)
    if np.any(in_win):
        plt.vlines((gt_idx_all[in_win] - center) / DATA_FS * 1000,
                   *plt.ylim(), colors="green", linestyles="--", linewidths=2, label="GT markers")
    
    plt.title(title, fontsize=14, fontweight='bold')
    plt.xlabel("time (ms)")
    plt.ylabel("amplitude")
    plt.legend(loc="upper right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    # Save plot
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()  # Close to free memory

def create_event_plots(trial_number: int, params: dict, results_per_patient: list):
    """Create plots for all events in this trial."""
    combo_dir = PLOTS_DIR / f"trial_{trial_number:05d}" # Using trial_number for directory name
    combo_dir.mkdir(exist_ok=True)
    
    # Save parameters for reference
    with (combo_dir / "parameters.json").open('w') as f:
        json.dump(params, f, indent=2)
    
    for result in results_per_patient:
        pid = result['pid']
        events = result['events']
        
        # Load patient data for plotting (use full data for consistent plotting base)
        # Note: This will load the full signal for plotting, even if evaluated on a fraction.
        # This gives a consistent visual context.
        sig_full, gt_map_full = load_patient_data_for_eval(pid, 1.0) 
        gt_idx_full = np.fromiter(gt_map_full.keys(), int)
        
        patient_dir = combo_dir / f"patient_{pid}"
        patient_dir.mkdir(exist_ok=True)
        
        # Separate events by type
        tp_events = [(e[1], e[2]) for e in events if e[0] == 'TP' and e[1] is not None]
        fp_events = [e[1] for e in events if e[0] == 'FP' and e[1] is not None]
        fn_events = [e[2] for e in events if e[0] == 'FN' and e[2] is not None]
        
        f_low_param = params.get('f_low', 0.25)
        f_high_param = params.get('f_high', 4.0)

        # Plot TPs
        for i, (det_idx, gt_idx_val) in enumerate(tp_events):
            title = f"TP #{i+1} - P{pid} T{trial_number} - Det@{det_idx} ↔ GT@{gt_idx_val}"
            save_path = patient_dir / f"TP_{i+1:03d}_det{det_idx}_gt{gt_idx_val}.png"
            plot_event(sig_full, det_idx, gt_idx_full, title, save_path, 
                       f_low_param, f_high_param)
        
        # Plot FPs
        for i, det_idx in enumerate(fp_events):
            title = f"FP #{i+1} - P{pid} T{trial_number} - Det@{det_idx} (no GT match)"
            save_path = patient_dir / f"FP_{i+1:03d}_det{det_idx}.png"
            plot_event(sig_full, det_idx, gt_idx_full, title, save_path,
                       f_low_param, f_high_param)
        
        # Plot FNs
        for i, gt_idx_val in enumerate(fn_events):
            title = f"FN #{i+1} - P{pid} T{trial_number} - Missed GT@{gt_idx_val}"
            save_path = patient_dir / f"FN_{i+1:03d}_gt{gt_idx_val}.png"
            plot_event(sig_full, gt_idx_val, gt_idx_full, title, save_path,
                       f_low_param, f_high_param)
        
        print(f"    📊 Plots saved for Patient {pid} (Trial {trial_number}): {len(tp_events)} TP, {len(fp_events)} FP, {len(fn_events)} FN")

# ─────────────────────—— Summary Generation ───────────────────────────────
def create_trial_summary(trial_number: int, params: dict, results_per_patient: list):
    """Create detailed summary file for an Optuna trial."""
    summary_dir = RESULTS_DIR / "trial_summaries"
    summary_dir.mkdir(exist_ok=True)
    
    summary_file = summary_dir / f"trial_{trial_number:05d}_summary.json"
    
    # Aggregate all events across patients
    all_tp_events = []
    all_fp_events = []
    all_fn_events = []
    
    patient_details = {}
    
    for result in results_per_patient:
        pid = result['pid']
        events = result['events']
        
        tp_events = [(int(e[1]), int(e[2])) for e in events if e[0] == 'TP' and e[1] is not None and e[2] is not None]  # (detection_idx, gt_idx)
        fp_events = [int(e[1]) for e in events if e[0] == 'FP' and e[1] is not None]  # detection_idx
        fn_events = [int(e[2]) for e in events if e[0] == 'FN' and e[2] is not None]  # missed_gt_idx
        
        all_tp_events.extend([(int(pid), int(det), int(gt)) for det, gt in tp_events])
        all_fp_events.extend([(int(pid), int(det)) for det in fp_events])
        all_fn_events.extend([(int(pid), int(gt)) for gt in fn_events])
        
        patient_details[pid] = {
            'tp_count': int(result['tp']),
            'fp_count': int(result['fp']),
            'fn_count': int(result['fn']),
            'gt_total': int(result['gt_total']),
            'precision': float(result['prec']),
            'recall': float(result['rec']),
            'tp_events': tp_events,  # [(detection_idx, gt_idx), ...]
            'fp_events': fp_events,  # [detection_idx, ...]
            'fn_events': fn_events   # [missed_gt_idx, ...]
        }
    
    # Overall statistics
    total_tp = sum(r['tp'] for r in results_per_patient)
    total_fp = sum(r['fp'] for r in results_per_patient)
    total_fn = sum(r['fn'] for r in results_per_patient)
    total_gt = sum(r['gt_total'] for r in results_per_patient)
    
    overall_prec = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0
    overall_rec = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0
    overall_f1 = 2 * overall_prec * overall_rec / (overall_prec + overall_rec) if overall_prec + overall_rec else 0
    
    summary_data = {
        'trial_number': int(trial_number),
        'parameters': params,
        'overall_statistics': {
            'total_patients': int(len(results_per_patient)),
            'total_ground_truth': int(total_gt),
            'true_positives': int(total_tp),
            'false_positives': int(total_fp),
            'false_negatives': int(total_fn),
            'precision': float(overall_prec),
            'recall': float(overall_rec),
            'f1_score': float(overall_f1),
            'specificity': None
        },
        'patient_details': patient_details,
        'event_indices': {
            'true_positives': all_tp_events,
            'false_positives': all_fp_events,
            'false_negatives': all_fn_events
        },
        'event_counts': {
            'tp_total': int(len(all_tp_events)),
            'fp_total': int(len(all_fp_events)),
            'fn_total': int(len(all_fn_events))
        }
    }
    
    # Save to JSON
    with summary_file.open('w') as f:
        json.dump(summary_data, f, indent=2)
    
    print(f"    📄 Detailed summary saved to {summary_file}")


# ─────────────────────—— Optuna Objective Function ─────────────────────────
def objective(trial: optuna.Trial, patient_ids: List[int], max_workers: int, optimization_metric: str = "precision"):
    # First, decide whether to check sinusoidness
    check_sinusoidness = trial.suggest_categorical("check_sinusoidness", [True, False])
    
    # Base parameters that are always used - 500trial-optuna-arxiv results
    # params = {
    #     "z_score_threshold": trial.suggest_float("z_score_threshold", 2.0, 4.5, step=0.5),
    #     "check_sinusoidness": check_sinusoidness,
    #     "f_low": trial.suggest_float("f_low", 0.2, 0.3, step=0.05),
    #     "f_high": trial.suggest_float("f_high", 3.5, 4.5, step=0.5),
    #     "min_wave_ms": trial.suggest_float("min_wave_ms", 100.0, 300.0, step=50.0),
    #     "max_wave_ms": trial.suggest_float("max_wave_ms", 800.0, 1200.0, step=100.0),
    #     "z_ied_threshold": trial.suggest_float("z_ied_threshold", 1.0, 3.0, step=0.5),
    #     "refrac_ms": trial.suggest_float("refrac_ms", 2000.0, 3000.0, step=250.0),
    # }

    # params = {
    #     "z_score_threshold": trial.suggest_float("z_score_threshold", 2.5, 2.5),
    #     "sinusoidness_threshold": trial.suggest_float("sinusoidness_threshold", 0.6, 0.6),
    #     "check_sinusoidness": trial.suggest_categorical("check_sinusoidness", [True,True]),
    #     "f_low": trial.suggest_float("f_low", 0.25, 0.25),
    #     "f_high": trial.suggest_float("f_high", 4.0, 4.0),
    #     "min_wave_ms": trial.suggest_float("min_wave_ms", 250, 250),
    #     "max_wave_ms": trial.suggest_float("max_wave_ms", 1000, 1000),
    #     "z_ied_threshold": trial.suggest_float("z_ied_threshold", 3.0, 3.0),
    #     "refrac_ms": trial.suggest_float("refrac_ms", 2500, 2500),
    # }
    
    # Based on 500-trial Optuna results analysis - focused on boundary exploration
    # Best performing configuration: check_sinusoidness=False, f_high=4.5, max_wave_ms=1200
    # F1=0.589 achieved with these parameters, hitting boundaries on f_high and max_wave_ms
    
    # Lock in the clear winners from Optuna analysis
    check_sinusoidness = False  # Definitively better than True
    
    params = {
        # Z-score: tight around your proven optimum of 2.5
        "z_score_threshold": trial.suggest_categorical("z_score_threshold", [2.25, 2.5, 2.75, 3.0]),
        
        "check_sinusoidness": check_sinusoidness,
        
        # Frequency: tight around 0.25, aggressive expansion beyond 4.5 boundary
        "f_low": trial.suggest_categorical("f_low", [0.225, 0.25, 0.275]),
        "f_high": trial.suggest_categorical("f_high", [4.0, 4.25, 4.5, 4.75, 5.0, 5.25]),
        
        # Wave length: lock min_wave_ms, explore beyond 1200ms boundary
        "min_wave_ms": 250.0,  # Consistently good across all trials
        "max_wave_ms": trial.suggest_categorical("max_wave_ms", [1100, 1200, 1300, 1400, 1500]),
        
        # IED: explore beyond your 3.0 boundary to reduce false positives
        "z_ied_threshold": trial.suggest_categorical("z_ied_threshold", [2.75, 3.0, 3.25, 3.5, 3.75]),
        
        # Refractory: moderate exploration around your proven 2500
        "refrac_ms": trial.suggest_categorical("refrac_ms", [2250.0, 2500.0, 2750.0, 3000.0]),
        
        # Since check_sinusoidness is always False, this doesn't matter
        "sinusoidness_threshold": 0.0
    }

    # Only suggest sinusoidness_threshold if check_sinusoidness is True
    if check_sinusoidness:
        params["sinusoidness_threshold"] = trial.suggest_float("sinusoidness_threshold", 0.3, 0.8, step=0.1)
    else:
        # Set a default value when sinusoidness checking is disabled
        # This value won't be used, but we need it for the config generation
        params["sinusoidness_threshold"] = 0.0  # or any default value
    
    # Generate config and temporary file
    cfg = make_cfg(params)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
        yaml.dump(cfg, tmp)
        cfg_path = tmp.name

    try:
        # NEW: Store results for ALL fractions, not just the last one
        all_fraction_results = []
        
        # Loop through data fractions for successive halving
        for i, fraction in enumerate(DATA_FRACTIONS):
            # Check if trial should be pruned based on early stopping
            if trial.should_prune():
                raise optuna.exceptions.TrialPruned()

            # Prepare tasks for all patients at current fraction
            tasks = []
            for j, pid in enumerate(patient_ids):
                tasks.append((trial.number, params, pid, cfg_path, j + 1, fraction))

            patient_results = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_task = {executor.submit(process_patient_for_optuna, task): task 
                                  for task in tasks}
                
                for future in as_completed(future_to_task):
                    try:
                        result = future.result()
                        patient_results.append(result)
                    except Exception as e:
                        task = future_to_task[future]
                        print(f"Error processing patient {task[2]} (Trial {trial.number}, Fraction {fraction}): {e}")

            # Sort results by patient ID
            patient_results.sort(key=lambda x: x['pid'])

            # Aggregate metrics for this fraction
            total_tp = sum(r['tp'] for r in patient_results)
            total_fp = sum(r['fp'] for r in patient_results)
            total_fn = sum(r['fn'] for r in patient_results)
            
            # If no ground truth or no detections, F1 can be undefined. Handle gracefully.
            if total_tp + total_fn == 0: # No GT events
                recall = 1.0 if total_tp == 0 else 0.0 # If no GT, and no TP, recall is 1. Otherwise 0.
            else:
                recall = total_tp / (total_tp + total_fn)
            
            if total_tp + total_fp == 0: # No detected events
                precision = 1.0 if total_tp == 0 else 0.0 # If no detected events, and no TP, precision is 1. Otherwise 0.
            else:
                precision = total_tp / (total_tp + total_fp)

            # Calculate all metrics
            f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
            balanced_score = (precision + recall) / 2 if (precision + recall) > 0 else 0.0
            
            # Choose which metric to optimize
            if optimization_metric == "f1":
                objective_value = f1_score
            elif optimization_metric == "precision":
                objective_value = precision
            elif optimization_metric == "recall":
                objective_value = recall
            elif optimization_metric == "balanced":
                objective_value = balanced_score
            else:
                raise ValueError(f"Unknown optimization metric: {optimization_metric}")

            print(f"Trial {trial.number} (Fraction: {fraction*100:.2f}%): "
                  f"F1={f1_score:.3f}, Prec={precision:.3f}, Rec={recall:.3f}, "
                  f"Optimizing={optimization_metric}({objective_value:.3f}), TP={total_tp}, FP={total_fp}, FN={total_fn}")
            
            # NEW: Save ALL metrics to Optuna user attributes for ALL fractions
            trial.set_user_attr(f"tp_frac_{fraction}", total_tp)
            trial.set_user_attr(f"fp_frac_{fraction}", total_fp)
            trial.set_user_attr(f"fn_frac_{fraction}", total_fn)
            trial.set_user_attr(f"precision_frac_{fraction}", precision)
            trial.set_user_attr(f"recall_frac_{fraction}", recall)
            trial.set_user_attr(f"f1_frac_{fraction}", f1_score)
            trial.set_user_attr(f"balanced_frac_{fraction}", balanced_score)
            trial.set_user_attr(f"objective_frac_{fraction}", objective_value)
            
            # Also store the optimization metric being used
            trial.set_user_attr("optimization_metric", optimization_metric)
            
            # Report the chosen metric to Optuna for pruning
            trial.report(objective_value, step=i)
            
            # Store results for all fractions
            all_fraction_results.append({
                'trial_number': trial.number,
                'params': params,
                'results_per_patient': patient_results,
                'f1_score': f1_score,
                'precision': precision,
                'recall': recall,
                'balanced_score': balanced_score,
                'objective_value': objective_value,
                'fraction': fraction
            })
        
        # Store final trial results (using last fraction for global storage)
        final_fraction_result = all_fraction_results[-1]  # Last fraction (0.25)
        with trial_results_lock:
            all_trial_results.append(final_fraction_result)
        
        # Return the objective value from the final fraction for optimization
        return final_fraction_result['objective_value']
        
    finally:
        os.remove(cfg_path)


# ─────────────────────—— Optuna Search Execution ───────────────────────────
def run_optuna_search(patient_ids: List[int], max_workers: int, n_trials: int, 
                      create_plots: bool = True, optimization_metric: str = DEFAULT_METRIC):
    """Run Optuna search for parameter optimization."""
    print(f"Starting Optuna search with {n_trials} trials")
    print(f"Testing on patients: {patient_ids}")
    print(f"Using {max_workers} workers")
    print(f"Progressive data fractions: {DATA_FRACTIONS}")
    print(f"Optimizing for: {optimization_metric} - {OPTIMIZATION_METRICS[optimization_metric]}")

    study_name = "dnb_optimization"
    # Use SQLite for storage to allow resuming studies and concurrent access if needed (though not fully parallelized here)
    storage_path = RESULTS_DIR / "optuna_study.db"
    
    # Ensure only one process tries to create the study initially
    with storage_lock:
        try:
            study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{storage_path}")
            print(f"Resuming existing Optuna study: {study_name}")
        except KeyError:
            study = optuna.create_study(
                study_name=study_name,
                storage=f"sqlite:///{storage_path}",
                direction="maximize", # Maximize the chosen metric
                sampler=optuna.samplers.TPESampler(), # TPE is a good default
                pruner=optuna.pruners.MedianPruner(
                    n_startup_trials=5, # Don't prune until at least this many trials run
                    n_warmup_steps=len(DATA_FRACTIONS) // 2 # Allow trials to run through half the fractions before pruning
                )
            )
            print(f"Created new Optuna study: {study_name}")

        try:
            # Pass patient_ids, max_workers, and optimization_metric to the objective function
            study.optimize(
                lambda trial: objective(trial, patient_ids, max_workers, optimization_metric),
                n_trials=n_trials,
                timeout=None, # No overall timeout
                callbacks=[] # Add callbacks if needed, e.g., for logging
            )
        except KeyboardInterrupt:
            print("\nOptuna optimization interrupted by user.")

        print("\n✅ Optuna search completed!")
        if study.best_trial:
            print(f"Best trial number: {study.best_trial.number}")
            print(f"Best parameters: {study.best_params}")
            print(f"Best {optimization_metric}: {study.best_value:.3f}")

        # Generate final summaries and plots for ALL COMPLETE trials
        print("\nGenerating final summaries and plots for completed trials...")

        # Fetch ALL completed trials
        all_completed_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]

        # Sort by value (objective metric) in descending order
        sorted_trials = sorted(all_completed_trials, key=lambda t: t.value, reverse=True)

        # NEW: Create summaries for ALL completed trials, not just top 5
        print(f"Creating summaries for {len(sorted_trials)} completed trials...")
   
    for i, trial in enumerate(sorted_trials):
        print(f"Processing trial #{i+1}/{len(sorted_trials)} (Trial {trial.number}): {optimization_metric}={trial.value:.3f}")
        
        # Find the full results for this trial (from all_trial_results)
        full_trial_data = next((item for item in all_trial_results if item['trial_number'] == trial.number), None)

        if full_trial_data:
            # Create detailed summary for this trial
            create_trial_summary(trial.number, trial.params, full_trial_data['results_per_patient'])
            
            # Create plots only for top trials to avoid too many plots
            if create_plots and i < 10:  # Only plot top 10 trials
                print(f"  🎨 Creating plots for Trial {trial.number}...")
                create_event_plots(trial.number, trial.params, full_trial_data['results_per_patient'])
        else:
            print(f"  Warning: Full results for trial {trial.number} not found. Skipping detailed summary and plots.")

# ─────────────────────—— Analysis ──────────────────────────────────────────
# The analyze_results and show_best_params functions now primarily interact with
# the Optuna study's stored results, rather than a raw CSV, for more robust analysis.

def analyze_results_optuna(top_n: int = 20):
    """Analyze Optuna study results and show top parameter sets."""
    study_name = "dnb_optimization"
    storage_path = RESULTS_DIR / "optuna_study.db"

    try:
        study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{storage_path}")
    except KeyError:
        print(f"❌ Optuna study '{study_name}' not found. Run search first.")
        return
    except Exception as e:
        print(f"❌ Error loading Optuna study: {e}")
        return
    
    print("\n📊 Analyzing Optuna study results...")
    
    # Get ALL trials (including pruned ones) - FIX: handle user_attrs properly
    try:
        df = study.trials_dataframe(attrs=("number", "value", "params", "state", "user_attrs"))
    except Exception as e:
        print(f"Warning: Could not load user_attrs: {e}")
        # Fallback without user_attrs
        df = study.trials_dataframe(attrs=("number", "value", "params", "state"))
        df['user_attrs'] = [{} for _ in range(len(df))]  # Add empty user_attrs
    
    if df.empty:
        print("No trials found in the study.")
        return

    # Check if user_attrs column exists and has data
    if 'user_attrs' not in df.columns:
        print("Warning: No user_attrs found in study. Using empty attributes.")
        df['user_attrs'] = [{} for _ in range(len(df))]

    # Extract optimization metric from user attributes (with fallback)
    optimization_metrics_used = df['user_attrs'].apply(
        lambda x: x.get('optimization_metric', 'unknown') if isinstance(x, dict) else 'unknown'
    )
    print(f"Optimization metrics used: {optimization_metrics_used.value_counts().to_dict()}")

    # Extract TP/FP/FN from user attributes for all fractions
    for fraction in DATA_FRACTIONS:
        df[f'tp_frac_{fraction}'] = df['user_attrs'].apply(
            lambda x: x.get(f'tp_frac_{fraction}', 0) if isinstance(x, dict) else 0
        )
        df[f'fp_frac_{fraction}'] = df['user_attrs'].apply(
            lambda x: x.get(f'fp_frac_{fraction}', 0) if isinstance(x, dict) else 0
        )
        df[f'fn_frac_{fraction}'] = df['user_attrs'].apply(
            lambda x: x.get(f'fn_frac_{fraction}', 0) if isinstance(x, dict) else 0
        )
        df[f'precision_frac_{fraction}'] = df['user_attrs'].apply(
            lambda x: x.get(f'precision_frac_{fraction}', 0) if isinstance(x, dict) else 0
        )
        df[f'recall_frac_{fraction}'] = df['user_attrs'].apply(
            lambda x: x.get(f'recall_frac_{fraction}', 0) if isinstance(x, dict) else 0
        )
        df[f'f1_frac_{fraction}'] = df['user_attrs'].apply(
            lambda x: x.get(f'f1_frac_{fraction}', 0) if isinstance(x, dict) else 0
        )
        df[f'objective_frac_{fraction}'] = df['user_attrs'].apply(
            lambda x: x.get(f'objective_frac_{fraction}', 0) if isinstance(x, dict) else 0
        )

    # Also add TP/FP/FN from trial summary files (for backward compatibility)
    df['tp_summary'] = 0
    df['fp_summary'] = 0
    df['fn_summary'] = 0
    
    summary_dir = RESULTS_DIR / "trial_summaries"
    if summary_dir.exists():
        summary_files = list(summary_dir.glob("trial_*_summary.json"))
        print(f"Found {len(summary_files)} trial summary files")
        
        for summary_file in summary_files:
            try:
                with summary_file.open() as f:
                    data = json.load(f)
                
                trial_num = data['trial_number']
                stats = data['overall_statistics']
                
                if trial_num in df['number'].values:
                    df.loc[df['number'] == trial_num, 'tp_summary'] = stats['true_positives']
                    df.loc[df['number'] == trial_num, 'fp_summary'] = stats['false_positives']
                    df.loc[df['number'] == trial_num, 'fn_summary'] = stats['false_negatives']
                    
            except Exception as e:
                print(f"Error reading {summary_file}: {e}")
    else:
        print("No trial_summaries directory found")

    df = df.rename(columns={"value": "objective_score"})
    
    # Sort by objective score (NaN values will go to end)
    df_sorted = df.sort_values(by="objective_score", ascending=False, na_position='last')
    
    # Show distribution of check_sinusoidness (if it exists)
    print(f"\n📈 Parameter Distribution:")
    if 'params_check_sinusoidness' in df.columns:
        print(f"check_sinusoidness distribution:")
        print(df['params_check_sinusoidness'].value_counts())
    print(f"\nTrial states:")
    print(df['state'].value_counts())
    
    # Display top results with TP/FP/FN for final fraction
    final_fraction = DATA_FRACTIONS[-1]
    print(f"\n🏆 TOP {top_n} TRIALS (by objective score, showing final fraction {final_fraction})\n")
    
    # Build display columns dynamically
    display_cols = ["number", "state", "objective_score"]
    
    # Add fraction-specific columns if they exist
    for suffix in ["tp", "fp", "fn", "precision", "recall", "f1"]:
        col_name = f"{suffix}_frac_{final_fraction}"
        if col_name in df_sorted.columns:
            display_cols.append(col_name)
    
    # Add parameter columns
    param_cols = [col for col in df_sorted.columns if col.startswith("params_")]
    display_cols.extend(param_cols)
    
    # Filter to only existing columns
    display_cols = [col for col in display_cols if col in df_sorted.columns]
    
    # Format the display
    top_df = df_sorted[display_cols].head(top_n)
    
    # Rename columns for cleaner display
    rename_dict = {}
    if f"tp_frac_{final_fraction}" in top_df.columns:
        rename_dict.update({
            f"tp_frac_{final_fraction}": "tp",
            f"fp_frac_{final_fraction}": "fp", 
            f"fn_frac_{final_fraction}": "fn",
            f"precision_frac_{final_fraction}": "precision",
            f"recall_frac_{final_fraction}": "recall",
            f"f1_frac_{final_fraction}": "f1"
        })
    
    top_df_display = top_df.rename(columns=rename_dict)
    print(top_df_display.to_string(float_format="%.3f", index=False))
    
    # Save full summary with all fractions
    summary_csv = RESULTS_DIR / "optuna_study_full_summary.csv"
    df_sorted.to_csv(summary_csv, index=False)
    print(f"\n📄 Full Optuna study summary (all trials, all fractions) saved to {summary_csv}")
    
    # Show separate summary for COMPLETE trials only
    df_complete = df_sorted[df_sorted["state"] == "COMPLETE"]
    if not df_complete.empty:
        print(f"\n🎯 TOP {min(top_n, len(df_complete))} COMPLETE TRIALS ONLY:\n")
        top_complete_df = df_complete[display_cols].head(top_n)
        top_complete_display = top_complete_df.rename(columns=rename_dict)
        print(top_complete_display.to_string(float_format="%.3f", index=False))
    
    # Show fraction-by-fraction breakdown for top trial (if user_attrs available)
    if not df_complete.empty and 'user_attrs' in df_complete.columns:
        best_trial_row = df_complete.iloc[0]
        if isinstance(best_trial_row['user_attrs'], dict) and best_trial_row['user_attrs']:
            print(f"\n📊 BEST TRIAL ({best_trial_row['number']}) FRACTION BREAKDOWN:")
            print("Fraction | TP | FP | FN | Precision | Recall |   F1   | Objective")
            print("-" * 65)
            for fraction in DATA_FRACTIONS:
                tp = best_trial_row.get(f'tp_frac_{fraction}', 'N/A')
                fp = best_trial_row.get(f'fp_frac_{fraction}', 'N/A')
                fn = best_trial_row.get(f'fn_frac_{fraction}', 'N/A')
                prec = best_trial_row.get(f'precision_frac_{fraction}', 'N/A')
                rec = best_trial_row.get(f'recall_frac_{fraction}', 'N/A')
                f1 = best_trial_row.get(f'f1_frac_{fraction}', 'N/A')
                obj = best_trial_row.get(f'objective_frac_{fraction}', 'N/A')
                
                if isinstance(tp, (int, float)):
                    print(f"{fraction:8.2f} | {tp:2.0f} | {fp:2.0f} | {fn:2.0f} | {prec:9.3f} | {rec:6.3f} | {f1:6.3f} | {obj:9.3f}")
                else:
                    print(f"{fraction:8.2f} | {tp} | {fp} | {fn} | {prec} | {rec} | {f1} | {obj}")
    
    return df_sorted

def show_best_params_optuna():
   """Show the best parameter set from the Optuna study."""
   study_name = "dnb_optimization"
   storage_path = RESULTS_DIR / "optuna_study.db"
   best_json = RESULTS_DIR / "best_optuna_params.json"

   try:
       study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{storage_path}")
   except KeyError:
       print(f"❌ Optuna study '{study_name}' not found. Run search first.")
       return
   except Exception as e:
       print(f"❌ Error loading Optuna study: {e}")
       return

   if not study.best_trial:
       print("❌ No completed trials in the study yet to determine the best parameters.")
       return

   best_trial = study.best_trial
   optimization_metric = best_trial.user_attrs.get('optimization_metric', 'unknown')
   
   # Save to JSON
   with best_json.open("w") as f:
       json.dump(best_trial.params, f, indent=2)
   
   print(f"\n⭐ BEST PARAMETER SET from Optuna (saved to {best_json})")
   print(f"   Trial Number: {best_trial.number}")
   print(f"   Optimization Metric: {optimization_metric}")
   print(f"   Best {optimization_metric}: {best_trial.value:.3f}")
   
   # Show breakdown by fraction if available
   print(f"\n📊 Performance by Fraction:")
   print("Fraction | TP | FP | FN | Precision | Recall |   F1   | Objective")
   print("-" * 65)
   for fraction in DATA_FRACTIONS:
       tp = best_trial.user_attrs.get(f'tp_frac_{fraction}', 'N/A')
       fp = best_trial.user_attrs.get(f'fp_frac_{fraction}', 'N/A')
       fn = best_trial.user_attrs.get(f'fn_frac_{fraction}', 'N/A')
       prec = best_trial.user_attrs.get(f'precision_frac_{fraction}', 'N/A')
       rec = best_trial.user_attrs.get(f'recall_frac_{fraction}', 'N/A')
       f1 = best_trial.user_attrs.get(f'f1_frac_{fraction}', 'N/A')
       obj = best_trial.user_attrs.get(f'objective_frac_{fraction}', 'N/A')
       
       if isinstance(tp, (int, float)):
           print(f"{fraction:8.2f} | {tp:2.0f} | {fp:2.0f} | {fn:2.0f} | {prec:9.3f} | {rec:6.3f} | {f1:6.3f} | {obj:9.3f}")
       else:
           print(f"{fraction:8.2f} | {tp} | {fp} | {fn} | {prec} | {rec} | {f1} | {obj}")
   
   print(f"\nParameters:")
   print(json.dumps(best_trial.params, indent=2))

# ─────────────────────—— CLI Interface ─────────────────────────────────────
def main():
   parser = argparse.ArgumentParser(description="DirectNeuralBiasing Optuna Search CLI")
   subparsers = parser.add_subparsers(dest="command", help="Available commands")
   
   # Search command
   search_parser = subparsers.add_parser("search", help="Run Optuna search")
   search_parser.add_argument("--patients", default="2,3,4,6,7", 
                                help="Comma-separated patient IDs (default: 2,3,4,6,7)")
   search_parser.add_argument("--workers", type=int, default=4,
                                help="Number of parallel workers (default: 4)")
   search_parser.add_argument("--trials", type=int, default=100,
                                help="Number of Optuna trials to run (default: 100)")
   search_parser.add_argument("--no-plots", action="store_true",
                                help="Skip generating plots (faster)")
   search_parser.add_argument("--metric", default=DEFAULT_METRIC, 
                             choices=list(OPTIMIZATION_METRICS.keys()),
                             help=f"Optimization metric (default: {DEFAULT_METRIC}). "
                                  f"Options: {', '.join(f'{k} ({v})' for k, v in OPTIMIZATION_METRICS.items())}")
   
   # Analyze command
   analyze_parser = subparsers.add_parser("analyze", help="Analyze Optuna study results")
   analyze_parser.add_argument("--top", type=int, default=20,
                                help="Number of top results to show (default: 20)")
   
   # Best command
   subparsers.add_parser("best", help="Show best parameter set from Optuna study")
   
   # Summary command
   subparsers.add_parser("summary", help="Show detailed summary of a specific trial")
   
   args = parser.parse_args()
   
   if args.command == "search":
       patient_ids = [int(x.strip()) for x in args.patients.split(",")]
       run_optuna_search(patient_ids, args.workers, args.trials, 
                         create_plots=not args.no_plots, 
                         optimization_metric=args.metric)
   
   elif args.command == "analyze":
       analyze_results_optuna(args.top)
   
   elif args.command == "best":
       show_best_params_optuna()
   
   elif args.command == "summary":
       show_trial_summaries()
   
   else:
       parser.print_help()

def show_trial_summaries():
   """Show available trial summaries and let user select one to view."""
   summary_dir = RESULTS_DIR / "trial_summaries"
   
   if not summary_dir.exists():
       print("❌ No trial summaries found. Run search first.")
       return
   
   summary_files = sorted(summary_dir.glob("trial_*_summary.json"))
   
   if not summary_files:
       print("❌ No trial summary files found.")
       return
   
   print(f"\n📁 Found {len(summary_files)} trial summaries:")
   
   # Load and display brief info about each trial
   for i, summary_file in enumerate(summary_files):
       with summary_file.open() as f:
           data = json.load(f)
       
       trial_number = data['trial_number']
       stats = data['overall_statistics']
       
       print(f"{i+1:2d}. Trial {trial_number}: TP={stats['true_positives']} "
             f"FP={stats['false_positives']} FN={stats['false_negatives']} "
             f"Prec={stats['precision']:.3f} Rec={stats['recall']:.3f} F1={stats['f1_score']:.3f}")
   
   # Let user choose which one to view in detail
   try:
       choice = input(f"\nEnter number (1-{len(summary_files)}) to view details, or Enter to exit: ").strip()
       if not choice:
           return
       
       idx = int(choice) - 1
       if 0 <= idx < len(summary_files):
           show_detailed_trial_summary(summary_files[idx])
       else:
           print("❌ Invalid choice")
   except (ValueError, KeyboardInterrupt):
       print("\n👋 Exiting")

def show_detailed_trial_summary(summary_file: Path):
   """Show detailed information about a specific trial."""
   with summary_file.open() as f:
       data = json.load(f)
   
   trial_number = data['trial_number']
   params = data['parameters']
   stats = data['overall_statistics']
   patient_details = data['patient_details']
   events = data['event_indices']
   
   print(f"\n🔍 DETAILED SUMMARY - TRIAL {trial_number}")
   print("=" * 50)
   
   print(f"\n📋 Parameters:")
   for key, value in params.items():
       print(f"    {key}: {value}")
   
   print(f"\n📊 Overall Statistics:")
   print(f"    Patients: {stats['total_patients']}")
   print(f"    Ground Truth Events: {stats['total_ground_truth']}")
   print(f"    True Positives: {stats['true_positives']}")
   print(f"    False Positives: {stats['false_positives']}")
   print(f"    False Negatives: {stats['false_negatives']}")
   print(f"    Precision: {stats['precision']:.3f}")
   print(f"    Recall: {stats['recall']:.3f}")
   print(f"    F1 Score: {stats['f1_score']:.3f}")
   
   print(f"\n👥 Per-Patient Breakdown:")
   for pid, details in patient_details.items():
       print(f"    Patient {pid}: TP={details['tp_count']} FP={details['fp_count']} "
             f"FN={details['fn_count']} GT={details['gt_total']} "
             f"Prec={details['precision']:.3f} Rec={details['recall']:.3f}")
   
   print(f"\n🎯 Event Indices:")
   print(f"    True Positives ({len(events['true_positives'])}):")
   for i, (pid, det_idx, gt_idx) in enumerate(events['true_positives'][:10]):
       print(f"      {i+1}. Patient {pid}: Detection@{det_idx} matched GT@{gt_idx}")
   if len(events['true_positives']) > 10:
       print(f"      ... and {len(events['true_positives']) - 10} more")
   
   print(f"\n    False Positives ({len(events['false_positives'])}):")
   for i, (pid, det_idx) in enumerate(events['false_positives'][:10]):
       print(f"      {i+1}. Patient {pid}: Spurious detection@{det_idx}")
   if len(events['false_positives']) > 10:
       print(f"      ... and {len(events['false_positives']) - 10} more")
   
   print(f"\n    False Negatives ({len(events['false_negatives'])}):")
   for i, (pid, gt_idx) in enumerate(events['false_negatives'][:10]):
       print(f"      {i+1}. Patient {pid}: Missed GT@{gt_idx}")
   if len(events['false_negatives']) > 10:
       print(f"      ... and {len(events['false_negatives']) - 10} more")

if __name__ == "__main__":
   main()