import socket
import csv
from datetime import datetime


LISTEN_IP   = "0.0.0.0"
LISTEN_PORT = 6767
OUTPUT_FILE = f"../data/csi_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
BUFFER_SIZE = 2048# bytes per UDP packet 

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))

    print(f"Listening for CSI UDP packets on port {LISTEN_PORT}...")
    print(f"Saving to {OUTPUT_FILE}")
    print("(Ctrl+C to stop)\n")

    row_count = 0

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_ms", "rssi", "len", "raw_bytes", "sender_ip"])

        while True:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            line = data.decode("utf-8", errors="ignore").strip()

            if not line:
                continue

            parts = line.split(",", 3)
            if len(parts) < 4:
                continue  # skip malformed packets

            writer.writerow(parts + [addr[0]])
            row_count += 1

            if row_count % 100 == 0:
                f.flush()
                print(f"captured {row_count} packets... (last from {addr[0]})")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")