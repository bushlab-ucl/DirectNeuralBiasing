# Offline Validation — Quick Start

This folder contains everything needed to run the slow-wave detector
on existing recordings and produce detection logs for visual validation.

&nbsp;

---

&nbsp;

## What you need

- Python 3.11+ (already on the lab machine)
- The `DirectNeuralBiasing` repo (already cloned)
- One or more `.ns6` or `.npz` recordings

&nbsp;

---

&nbsp;

## Setup (one time only)

Open a terminal in the `DirectNeuralBiasing` directory:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

This installs the library and Jupyter. Takes about 30 seconds.

&nbsp;

---

&nbsp;

## Step 1 — Convert .ns6 to .npz

If your recordings are `.ns6` files (Blackrock native format), convert
them first. If you already have `.npz` files, skip this step.

```bash
python validation/ns6_to_npz.py  D:\recordings\20190122-065346-004.ns6
```

This creates `20190122-065346-004.npz` in the same directory.
The sample rate, channel labels, and scale factors are read from
the `.ns6` header automatically.

To convert to µV directly (larger files, but no scale factor to worry about):

```bash
python validation/ns6_to_npz.py  D:\recordings\20190122-065346-004.ns6  --uv
```

&nbsp;

---

&nbsp;

## Step 2 — Edit the notebook

```bash
jupyter notebook validation/batch-processing.ipynb
```

In the **config cell**, edit two things:

### 1. File list

Point `FILES` at your `.npz` files. Use full paths:

```python
FILES = [
    Path('D:/recordings/20190122-065346-004.npz'),
    Path('D:/recordings/20190123-071200-001.npz'),
]
```

### 2. Channel

Set `CHANNEL_ID` to the channel you want to analyse:

```python
CHANNEL_ID = 0
```

Channel numbering starts at 0. To check what channels are available:

```python
import numpy as np
data = np.load('D:/recordings/20190122-065346-004.npz', allow_pickle=True)
print(f"Channels: {data['data'].shape[1]}")
print(f"Labels: {data['labels']}")
```

Everything else has sensible defaults. You can leave it alone.

&nbsp;

---

&nbsp;

## Step 3 — Run all cells

Click **Cell → Run All** (or Shift+Enter through each cell).

For each file the notebook will:

1. Print detection and stim counts
2. Save a `_detections.csv` to the output directory
3. Show a 3-panel report figure and save it as `_report.png`

At the end, a summary table shows all files.

The last cell plots every individual detection with context.
Set `MAX_EVENTS = 20` or similar if you don't want hundreds of plots.

&nbsp;

---

&nbsp;

## Step 4 — Validate detections

The key output is the `_detections.csv` file. It looks like this:

```
event_type,  timestamp_s,  sample_index,  frequency_hz,  amplitude,  ...
SLOW_WAVE,   12.3400,      370200,        0.850,         1543.2,     ...
STIM,        12.9290,      387870,        0.850,         ,           ...
SLOW_WAVE,   17.8600,      535800,        1.120,         2105.7,     ...
...
```

The `sample_index` column is at the **original hardware rate** (e.g. 30 kHz).
Use it to jump directly to that sample in your recording viewer and check
whether the detection looks like a real slow wave.

&nbsp;

---

&nbsp;

## The report figure

Each file gets a 3-panel figure:

**(a) Stim-triggered average** — every detected slow wave aligned at the
predicted stim time (t=0). Individual trials in colour, mean in black.
If the pipeline is working, the mean should peak at t=0 (we're stimulating
at the predicted positive peak). The signal is bandpass filtered to the
slow oscillation band (0.5–4 Hz).

**(b) Phase polar plot** — where in the slow-wave cycle each stim actually
lands. Green line = target (0° = peak). Red line = actual mean.
If phase accuracy is good, the red bars cluster around 0° and the error
is small.

**(c) Fired vs blocked** — how many stims fired vs how many were blocked
by IED inhibition. The pipeline runs twice per file: once with the
`AmplitudeMonitor` (IED rejection) and once without. The difference is
the blocked count.

&nbsp;

---

&nbsp;

## Tuning parameters

If too many or too few detections, these are the knobs to turn:

| Parameter            | Default | Effect                                             |
| -------------------- | ------- | -------------------------------------------------- |
| `Z_SCORE_THRESHOLD`  | 1.0     | Higher = fewer detections (only large SWs)         |
| `BACKOFF_S`          | 2.5     | Minimum gap between detections (seconds)           |
| `IED_ADAPTIVE_N_STD` | 5.0     | Higher = less aggressive IED blocking              |
| `PHASE_TOLERANCE`    | 0.05    | How close to π the phase must be to trigger        |
| `N_CYCLES_BASE`      | 1.0     | Higher = better frequency resolution, more latency |

&nbsp;

---

&nbsp;

## Troubleshooting

**"No sample rate key"** — the `.npz` file wasn't produced by `ns6_to_npz.py`.
Re-convert from `.ns6`, or check what keys are in the file:

```python
import numpy as np
data = np.load('file.npz', allow_pickle=True)
print(list(data.keys()))
```

**0 detections** — try lowering `Z_SCORE_THRESHOLD` to 0.5, or check that
`CHANNEL_ID` points to a channel with actual neural data.

**Too many detections** — raise `Z_SCORE_THRESHOLD` to 1.5 or 2.0,
or increase `BACKOFF_S`.

**MemoryError on large files** — long recordings (hours) at 30 kHz use a lot
of RAM. Consider splitting the `.ns6` file, or converting with `--uv` and
using a machine with more memory.

&nbsp;

---

&nbsp;

## Files in this directory

| File                     | What it does             |
| ------------------------ | ------------------------ |
| `batch-processing.ipynb` | Main notebook — run this |
| `ns6_to_npz.py`          | Convert .ns6 → .npz      |
| `README.md`              | This file                |
