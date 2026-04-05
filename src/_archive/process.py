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
            payload = raw[6:]  # skip 6-value header
            samples = payload.reshape(83, 6)  # 83 channels x 6 samples
            packets.append((header.time, samples))

    time.sleep(3)

    print(f"Captured {len(packets)} packets")

    if packets:
        all_samples = np.array([p[1] for p in packets])
        continuous = all_samples.transpose(1, 0, 2).reshape(83, -1)
        print(f"Continuous data shape: {continuous.shape}")
        print(f"Total duration: {continuous.shape[1] / 30000:.2f} seconds")

        # Save locally
        np.savez('neural_data.npz',
                 continuous=continuous,
                 sample_rate=30000,
                 channel_count=83)
        print("Saved to neural_data.npz")