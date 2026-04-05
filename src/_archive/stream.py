from pycbsdk import Session
import time
import numpy as np
import sys

PRINT_INTERVAL = 1.0  # seconds between updates
NUM_CHANNELS = 83
SAMPLES_PER_PACKET = 6

with Session("NPLAY") as session:
    time.sleep(2)

    # Accumulate packets for one interval, then print stats
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