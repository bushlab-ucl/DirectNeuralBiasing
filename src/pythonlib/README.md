# Cerebus Neural Data Capture via pycbsdk

## Overview

This project captures continuous neural data from a Blackrock Neurotech Cerebus system using the new [CereLink](https://github.com/CerebusOSS/CereLink)-based `pycbsdk` Python package. It connects in **client mode** to Central's shared memory (rather than owning the device connection directly) and extracts raw 30 kHz broadband data from group packets.

## Background

The CereLink `pycbsdk` exposes a `Session` class with decorator-based callbacks for different packet types. In a typical setup, Central (Blackrock's GUI application) or nPlayServer (a data replay simulator) owns the UDP connection to the NSP hardware and writes packets into shared memory. Our Python script attaches to that shared memory as a client and receives packets via the `@session.on_packet()` catch-all callback.

### Why the catch-all instead of `@session.on_group()`?

In client mode, the channel-to-group assignments may not be populated in the shared memory config. This means `session.get_group_channels(5)` returns an empty list and `@session.on_group(5)` never fires, even though 30 kHz continuous data *is* flowing. The workaround is to intercept **type 6** packets directly via `@session.on_packet()` and decode them manually.

## Packet structure

Each type 6 packet contains 1008 bytes (504 int16 values):

```
[ header (6 values) | payload (498 values) ]
                       └── 83 channels × 6 samples per channel
```

- **Header** (indices 0–5): Index 0 is a small varying value (possibly a sequence counter or sub-packet identifier). Indices 1–5 are always zero.
- **Payload** (indices 6–503): 83 channels × 6 time samples each, stored as contiguous int16. Reshaping to `(83, 6)` gives one row per channel.

At 30 kHz with 6 samples per packet, packets arrive at approximately **5,000 packets/second** (timestamps increment by 1 per packet).

## Channel classification

From a 1-second capture (30,000 samples per channel):

| Channels | Type | Description |
|----------|------|-------------|
| 0–7 | Continuous | All 30,000 samples populated. High variance (std 7,400–10,500). Channels 0 and 5 clip at ±32768. Likely raw wideband neural or analog input signals. |
| 8–82 | Sparse / event | Mostly zeros with isolated deflections (62–10,125 non-zero samples). Consistent with spike timestamps or extracted waveform snippets. |

## Scripts

### `process.py` — capture and save

Captures a fixed number of packets, assembles them into a continuous `(channels, samples)` array, and saves to disk.

```python
from pycbsdk import Session
import time
import numpy as np

with Session("NPLAY") as session:
    time.sleep(2)

    packets = []

    @session.on_packet()
    def on_any(header, data):
        if header.type == 6 and len(packets) < 5000:
            raw = np.frombuffer(bytes(data), dtype=np.int16).copy()
            payload = raw[6:]       # skip 6-value header
            samples = payload.reshape(83, 6)  # 83 channels × 6 samples
            packets.append((header.time, samples))

    time.sleep(3)

    print(f"Captured {len(packets)} packets")

    if packets:
        all_samples = np.array([p[1] for p in packets])
        continuous = all_samples.transpose(1, 0, 2).reshape(83, -1)
        print(f"Continuous data shape: {continuous.shape}")
        print(f"Total duration: {continuous.shape[1] / 30000:.2f} seconds")

        np.savez('neural_data.npz',
                 continuous=continuous,
                 sample_rate=30000,
                 channel_count=83)
        print("Saved to neural_data.npz")
```

**How the reshape works:**

1. `all_samples` has shape `(n_packets, 83, 6)`
2. `.transpose(1, 0, 2)` rearranges to `(83, n_packets, 6)` — grouping by channel
3. `.reshape(83, -1)` flattens the last two dimensions into `(83, n_packets × 6)` — a single time series per channel

### `stream.py` — live printing

Prints channel statistics to the terminal in real time as packets arrive. Useful for verifying the connection is working and data looks reasonable.

```python
from pycbsdk import Session
import time
import numpy as np
import sys

PRINT_INTERVAL = 1.0  # seconds between updates
NUM_CHANNELS = 83
SAMPLES_PER_PACKET = 6

with Session("NPLAY") as session:
    time.sleep(2)

    # Ring buffer: accumulate one second of data, then print stats
    buffer = []
    last_print = time.time()
    packet_count = [0]

    @session.on_packet()
    def on_any(header, data):
        if header.type != 6:
            return

        raw = np.frombuffer(bytes(data), dtype=np.int16).copy()
        payload = raw[6:]
        samples = payload.reshape(NUM_CHANNELS, SAMPLES_PER_PACKET)
        buffer.append(samples)
        packet_count[0] += 1

    print("Streaming... press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(0.1)
            now = time.time()

            if now - last_print >= PRINT_INTERVAL and buffer:
                block = np.concatenate(buffer, axis=1)  # (83, n_samples)
                n_samples = block.shape[1]

                # Clear screen and print header
                sys.stdout.write("\033[2J\033[H")
                print(f"Packets/sec: {packet_count[0]:.0f}  |  "
                      f"Samples: {n_samples}  |  "
                      f"Duration: {n_samples / 30000:.3f}s\n")
                print(f"{'Chan':>5} {'Mean':>8} {'Std':>8} {'Min':>8} {'Max':>8} {'NonZero':>8}")
                print("-" * 53)

                for ch in range(NUM_CHANNELS):
                    row = block[ch].astype(float)
                    nz = np.count_nonzero(row)
                    print(f"{ch:5d} {row.mean():8.0f} {row.std():8.0f} "
                          f"{row.min():8.0f} {row.max():8.0f} {nz:8d}")

                buffer.clear()
                packet_count[0] = 0
                last_print = now

    except KeyboardInterrupt:
        print("\nStopped.")

    print(session.stats)
```

## Prerequisites

- **Python 3.10+** with numpy: `pip install pycbsdk[numpy]`
- **Central + nPlayServer** running and playing a data file (the script connects as a client to shared memory)
- Device type in `Session()` should match your setup: `NPLAY` for nPlayServer, `LEGACY_NSP` for older NSPs, `HUB1`–`HUB3` for Gemini hubs

## Output format

`neural_data.npz` contains:

| Key | Shape | Description |
|-----|-------|-------------|
| `continuous` | `(83, N)` | int16 samples, N = packets × 6 |
| `sample_rate` | scalar | 30000 |
| `channel_count` | scalar | 83 |

Load with:

```python
data = np.load('neural_data.npz')
continuous = data['continuous']  # shape (83, 30000) for 5000 packets
```

## Known limitations

- The packet structure (83 channels, 6-value header) is specific to this device configuration and may differ on other setups or with different nPlayServer data files.
- In client mode, `set_runlevel`, `set_channel_sample_group`, and other write commands will fail — Central controls the device.
- The `runlevel` may report 0 even while data is flowing through shared memory.

## WIKI
- https://github.com/CerebusOSS/CereLink/wiki