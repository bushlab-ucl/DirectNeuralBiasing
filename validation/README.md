# Running the offline detector on your recordings

Hey Dan — this walks you through running the slow-wave detector on
real `.ns6` recordings and getting detection logs you can validate by eye.

The whole thing is one Jupyter notebook. You edit two lines at the top
(your file paths and which channel), then run all cells. It spits out
a CSV per file with sample indices you can look up in the raw recording.

&nbsp;

---

&nbsp;

## First time setup

You only need to do this once. In the `DirectNeuralBiasing` directory:

```bash
git clone https://github.com/bushlab-ucl/DirectNeuralBiasing
cd DirectNeuralBiasing
pip install -e .
```

&nbsp;

---

&nbsp;

## 1. Convert your .ns6 files

```bash
python validation/ns6_to_npz.py  D:\recordings\20190122-065346-004.ns6
```

Creates a `.npz` next to the original. Reads the sample rate, channel
labels, and scale factors from the ns6 header — you don't need to specify
anything.

&nbsp;

---

&nbsp;

## 2. Open the notebook

```bash
jupyter notebook validation/batch-processing.ipynb
```

&nbsp;

---

&nbsp;

## 3. Edit the config cell

Two things to change:

```python
FILES = [
    Path('D:/recordings/20190122-065346-004.npz'),
    Path('D:/recordings/20190123-071200-001.npz'),
]

CHANNEL_ID = 0    # which channel to analyse
```

That's it. Everything else has defaults that should work. If you want to
check what channels are in a file:

```python
import numpy as np
d = np.load('D:/recordings/20190122-065346-004.npz', allow_pickle=True)
print(d['labels'])
```

&nbsp;

---

&nbsp;

## 4. Run All

Shift+Enter through the cells, or Cell → Run All. For each file you'll see:

- A print line like `14 detections, 12 stims (with inhibition)`
- A 3-panel figure (saved as `_report.png`)
- A detection log (saved as `_detections.csv`)

The last optional cell plots every single detection with its surrounding
context — useful for eyeballing but set `MAX_EVENTS = 20` or so if there
are hundreds.

&nbsp;

---

&nbsp;

## What's in the CSV

```
event_type,  timestamp_s,  sample_index,  frequency_hz,  amplitude, ...
SLOW_WAVE,   12.3400,      370200,        0.850,         1543.2,    ...
STIM,        12.9290,      387870,        0.850,         ,          ...
```

**`sample_index` is at the original 30 kHz rate.** Open your recording,
jump to that sample, and check if it's a real slow wave.

&nbsp;

---

&nbsp;

## What's in the figure

**(a)** Every detected slow wave aligned at the predicted stim time.
Individual trials in colour, mean in black. The signal is filtered to
the SO band (0.5–4 Hz). If things are working, the mean peaks at t=0.

**(b)** Polar plot of where each stim lands in the slow-wave cycle.
Green = target (peak). Red = actual. Bars should cluster at the top.

**(c)** How many stims fired vs how many got blocked by the IED inhibitor.

&nbsp;

---

&nbsp;

## If the results look wrong

**0 detections** — lower `Z_SCORE_THRESHOLD` (try 0.5), or check that
`CHANNEL_ID` has actual neural data on it.

**Way too many detections** — raise `Z_SCORE_THRESHOLD` (try 2.0) or
increase `BACKOFF_S` (minimum gap between detections, default 2.5s).

**Everything blocked by IED inhibitor** — raise `IED_ADAPTIVE_N_STD`
(default 5.0, try 8.0) to make it less aggressive.

**Phase is off** — this might just be the frequency resolution at
`N_CYCLES_BASE=1.0`. Try 1.5 for tighter frequency estimates
(adds a bit of latency that doesn't matter offline).

&nbsp;

---

&nbsp;

## Files here

| File                     | What                    |
| ------------------------ | ----------------------- |
| `batch-processing.ipynb` | The notebook — run this |
| `ns6_to_npz.py`          | Converts .ns6 → .npz    |
| `README.md`              | You're reading it       |
