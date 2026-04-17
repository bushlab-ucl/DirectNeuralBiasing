import numpy as np
import struct
from pathlib import Path


def read_ns6(filepath):
    """
    Read a Blackrock .ns6 (NEV spec 2.1+) continuous data file.
    Parses the file header and extended headers to extract metadata,
    channel info, and raw neural data. Returns everything needed for .npz export.
    """
    filepath = Path(filepath)

    with open(filepath, "rb") as f:
        # --- Basic Header (8 + 2 + 4 + 16 + 256 + 4 + 4 + 8*2 + 4 + 4 + 4 = 332 bytes min) ---
        file_type_id = f.read(8).decode("ascii").strip("\x00")
        if file_type_id != "NEURALCD":
            raise ValueError(f"Not a valid NSx file. Got file_type_id: '{file_type_id}'")

        # File spec version (major.minor)
        ver_major = struct.unpack("<B", f.read(1))[0]
        ver_minor = struct.unpack("<B", f.read(1))[0]
        file_spec = f"{ver_major}.{ver_minor}"

        # Bytes in headers (total header size including extended headers)
        bytes_in_headers = struct.unpack("<I", f.read(4))[0]

        # Label (16 bytes) and comment (256 bytes)
        label = f.read(16).decode("latin-1").strip("\x00")
        comment = f.read(256).decode("latin-1").strip("\x00")

        # Period: number of 1/30000 s clock ticks per sample
        # For NS6, period is typically 1 → fs = 30000 Hz
        period = struct.unpack("<I", f.read(4))[0]

        # Time resolution of timestamps (typically 30000)
        time_resolution = struct.unpack("<I", f.read(4))[0]

        # Sampling frequency derived from header
        fs = time_resolution / period

        # Time origin (8 x uint16): year, month, dow, day, hour, min, sec, ms
        time_origin = struct.unpack("<8H", f.read(16))

        # Number of channels (extended headers)
        channel_count = struct.unpack("<I", f.read(4))[0]

        # --- Extended Headers (66 bytes each) ---
        channels = []
        for _ in range(channel_count):
            ext_type = f.read(2).decode("ascii")  # "CC"
            electrode_id = struct.unpack("<H", f.read(2))[0]
            electrode_label = f.read(16).decode("latin-1").strip("\x00")
            phys_connector = struct.unpack("<B", f.read(1))[0]
            connector_pin = struct.unpack("<B", f.read(1))[0]
            min_digital = struct.unpack("<h", f.read(2))[0]
            max_digital = struct.unpack("<h", f.read(2))[0]
            min_analog = struct.unpack("<h", f.read(2))[0]
            max_analog = struct.unpack("<h", f.read(2))[0]
            units = f.read(16).decode("latin-1").strip("\x00")
            hi_freq_corner = struct.unpack("<I", f.read(4))[0]
            hi_freq_order = struct.unpack("<I", f.read(4))[0]
            hi_freq_type = struct.unpack("<H", f.read(2))[0]
            lo_freq_corner = struct.unpack("<I", f.read(4))[0]
            lo_freq_order = struct.unpack("<I", f.read(4))[0]
            lo_freq_type = struct.unpack("<H", f.read(2))[0]

            channels.append({
                "electrode_id": electrode_id,
                "label": electrode_label,
                "phys_connector": phys_connector,
                "connector_pin": connector_pin,
                "min_digital": min_digital,
                "max_digital": max_digital,
                "min_analog": min_analog,
                "max_analog": max_analog,
                "units": units,
            })

        # Verify we're at the right position
        assert f.tell() == bytes_in_headers, (
            f"Header size mismatch: at byte {f.tell()}, expected {bytes_in_headers}"
        )

        # --- Data Packets ---
        # Each data packet: 1-byte header (0x01), 4-byte timestamp, 4-byte num_points,
        # then num_points * channel_count int16 samples
        all_data = []

        while True:
            pkt_header = f.read(1)
            if not pkt_header:
                break  # EOF

            pkt_id = struct.unpack("<B", pkt_header)[0]
            if pkt_id != 1:
                raise ValueError(f"Unexpected data packet header: {pkt_id}")

            timestamp = struct.unpack("<I", f.read(4))[0]
            num_data_points = struct.unpack("<I", f.read(4))[0]

            # Read interleaved int16 samples: (num_data_points, channel_count)
            raw = f.read(num_data_points * channel_count * 2)
            if len(raw) < num_data_points * channel_count * 2:
                # Partial read at end of file
                num_data_points = len(raw) // (channel_count * 2)
                raw = raw[: num_data_points * channel_count * 2]

            packet_data = np.frombuffer(raw, dtype="<i2").reshape(num_data_points, channel_count)
            all_data.append(packet_data)

        # Concatenate all packets: shape (total_samples, channel_count)
        data = np.concatenate(all_data, axis=0) if all_data else np.empty((0, channel_count), dtype=np.int16)

    # Build conversion factors: microvolts = (analog_range / digital_range) * digital_value
    scale_factors = np.array([
        (ch["max_analog"] - ch["min_analog"]) / (ch["max_digital"] - ch["min_digital"])
        for ch in channels
    ], dtype=np.float64)

    electrode_ids = np.array([ch["electrode_id"] for ch in channels], dtype=np.int32)
    labels = np.array([ch["label"] for ch in channels])
    units_arr = np.array([ch["units"] for ch in channels])

    metadata = {
        "file_spec": file_spec,
        "label": label,
        "comment": comment,
        "fs": fs,
        "time_resolution": time_resolution,
        "period": period,
        "time_origin": np.array(time_origin, dtype=np.uint16),
        "channel_count": channel_count,
    }

    return data, metadata, electrode_ids, labels, units_arr, scale_factors


def ns6_to_npz(ns6_path, npz_path=None, convert_to_uv=False):
    """
    Convert a .ns6 file to .npz.

    Parameters
    ----------
    ns6_path : str or Path
        Path to the input .ns6 file.
    npz_path : str or Path, optional
        Output path. Defaults to same name with .npz extension.
    convert_to_uv : bool
        If True, store data as float32 in microvolts.
        If False (default), store raw int16 + scale factors.

    Saved arrays
    -------------
    data        : (n_samples, n_channels) int16 or float32
    fs          : scalar, sampling rate in Hz
    electrode_ids : (n_channels,) int32
    labels      : (n_channels,) str
    units       : (n_channels,) str
    scale_factors : (n_channels,) float64 — multiply raw int16 to get analog units
    time_origin : (8,) uint16 — [year, month, dow, day, hour, min, sec, ms]
    file_spec   : str
    """
    ns6_path = Path(ns6_path)
    if npz_path is None:
        npz_path = ns6_path.with_suffix(".npz")

    print(f"Reading {ns6_path} ...")
    data, meta, electrode_ids, labels, units, scale_factors = read_ns6(ns6_path)

    print(f"  File spec  : {meta['file_spec']}")
    print(f"  Fs         : {meta['fs']:.1f} Hz")
    print(f"  Channels   : {meta['channel_count']}")
    print(f"  Samples    : {data.shape[0]}  ({data.shape[0] / meta['fs']:.2f} s)")

    if convert_to_uv:
        print("  Converting to µV (float32) ...")
        data = (data.astype(np.float32) * scale_factors[np.newaxis, :]).astype(np.float32)

    print(f"Saving {npz_path} ...")
    np.savez_compressed(
        npz_path,
        data=data,
        fs=np.float64(meta["fs"]),
        electrode_ids=electrode_ids,
        labels=labels,
        units=units,
        scale_factors=scale_factors,
        time_origin=meta["time_origin"],
        file_spec=np.array(meta["file_spec"]),
        label=np.array(meta["label"]),
        comment=np.array(meta["comment"]),
    )
    print("Done.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ns6_to_npz.py <input.ns6> [output.npz] [--uv]")
        sys.exit(1)

    in_path = sys.argv[1]
    out_path = None
    to_uv = "--uv" in sys.argv

    for arg in sys.argv[2:]:
        if arg != "--uv":
            out_path = arg

    ns6_to_npz(in_path, out_path, convert_to_uv=to_uv)