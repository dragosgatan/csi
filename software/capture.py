import socket
import threading
import queue
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation


LISTEN_IP   = "0.0.0.0"
LISTEN_PORT = 6767

SC_FIRST = 6
SC_LAST  = 58

# 802.11 OFDM - they carry no signal by design, so they always read
NULL_SC_LOW  = 28
NULL_SC_HIGH = 36

HISTORY_LEN = 150     # packets kept on screen per node (smaller since we have a grid now)
MAX_NODES   = 4

AMP_VMIN = 0
AMP_VMAX = 60



data_queue = queue.Queue()


def parse_packet(data: bytes):
    """Header 'timestamp,rssi,len,' (ASCII) + raw binary CSI bytes."""
    idx = None
    commas = 0
    for i, b in enumerate(data):
        if b == 0x2C:
            commas += 1
            if commas == 3:
                idx = i
                break
    if idx is None:
        return None

    header_str = data[:idx].decode("ascii", errors="ignore")
    parts = header_str.split(",")
    if len(parts) != 3:
        return None

    try:
        rssi = int(parts[1])
        length = int(parts[2])
    except ValueError:
        return None

    raw = data[idx + 1: idx + 1 + length]
    if len(raw) < length:
        return None

    signed_vals = [b - 256 if b > 127 else b for b in raw]
    return rssi, signed_vals


def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))
    print(f"Listening on UDP port {LISTEN_PORT}...")

    needed_len = (SC_LAST + 1) * 2

    while True:
        data, addr = sock.recvfrom(2048)
        if not data:
            continue

        result = parse_packet(data)
        if result is None:
            continue

        rssi, raw_vals = result
        if len(raw_vals) < needed_len:
            continue

        amps = []
        for i in range(SC_FIRST, SC_LAST + 1):
            if NULL_SC_LOW <= i <= NULL_SC_HIGH:
                continue  # skip null/DC/guard subcarriers
            im = raw_vals[i * 2]
            re = raw_vals[i * 2 + 1]
            amps.append((re * re + im * im) ** 0.5)

        # tag each reading with the sender's IP - this is the "node ID"
        data_queue.put((addr[0], rssi, amps))


def main():
    n_subcarriers = (SC_LAST - SC_FIRST + 1) - (NULL_SC_HIGH - NULL_SC_LOW + 1)

    # one buffer + one axes slot per node, assigned in first-seen order
    node_order = []          # list of IPs, in the order they were first seen
    node_buffers = {}        # ip -> numpy array (HISTORY_LEN x n_subcarriers)

    ncols = 2
    nrows = (MAX_NODES + 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(11, 3.2 * nrows))
    axes = np.array(axes).reshape(-1)
    fig.suptitle("CSI Live View - multiple RX nodes (identified by IP)")

    images = {}  
    titles = {}

    for i, ax in enumerate(axes):
        ax.set_title(f"(waiting for node {i + 1}...)")
        ax.set_xticks([])
        ax.set_yticks([])

    def get_or_create_slot(ip):
        """Assign this IP to the next free subplot the first time we see it."""
        if ip in node_buffers:
            return
        if len(node_order) >= len(axes):
            return  

        slot = len(node_order)
        node_order.append(ip)
        node_buffers[ip] = np.zeros((HISTORY_LEN, n_subcarriers))

        ax = axes[slot]
        ax.set_title(f"RX: {ip}")
        ax.set_xlabel("Packets")
        ax.set_ylabel("Subcarrier")
        im = ax.imshow(node_buffers[ip].T, aspect="auto", origin="lower",
                        cmap="viridis", interpolation="nearest",
                        vmin=AMP_VMIN, vmax=AMP_VMAX)
        images[ip] = im
        print(f"[+] new node discovered: {ip} -> slot {slot + 1}")

    def update(frame):
        updated_ips = set()
        while not data_queue.empty():
            ip, rssi, amps = data_queue.get()
            get_or_create_slot(ip)
            if ip not in node_buffers:
                continue  # grid is full, drop extra nodes

            buf = node_buffers[ip]
            buf[:-1] = buf[1:]
            buf[-1] = amps
            updated_ips.add(ip)

        for ip in updated_ips:
            images[ip].set_data(node_buffers[ip].T)

        return list(images.values())

    listener_thread = threading.Thread(target=udp_listener, daemon=True)
    listener_thread.start()

    ani = animation.FuncAnimation(fig, update, interval=150, blit=False,
                                   cache_frame_data=False)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()