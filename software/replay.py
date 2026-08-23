#!/usr/bin/env python3
"""Replay a recorded CSI csv into the collector as if the boards were live.

Rebuilds each row into the same UDP packet csi_rtx.ino sends, so capture.py,
the filters, the tomography and the dashboard all run unchanged.

Expects the columns written by the raw logger:
    host_time_s,timestamp_ms,rx_mac,tx_mac,rssi,len,raw_bytes,sender_ip
"""

import argparse
import collections
import csv
import socket
import time


def load(path):
    with open(path, newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"no rows in {path}")
    missing = {"host_time_s", "rx_mac", "tx_mac", "rssi", "len", "raw_bytes"} - set(rows[0])
    if missing:
        raise SystemExit(f"{path} is missing columns: {', '.join(sorted(missing))}")
    return rows


def build_packet(row):
    """Header then raw binary CSI, exactly as the firmware sends it."""
    values = [int(v) for v in row["raw_bytes"].split(";")]
    raw = bytes(v & 0xFF for v in values)
    header = (f'{row["rx_mac"]},{row["tx_mac"]},{row["timestamp_ms"]},'
              f'{row["rssi"]},{len(raw)},').encode("ascii")
    return header + raw


def main():
    parser = argparse.ArgumentParser(description="Replay a CSI capture over UDP")
    parser.add_argument("path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6767)
    parser.add_argument("--speed", type=float, default=1.0, help="playback rate multiplier")
    parser.add_argument("--loop", action="store_true", help="repeat until interrupted")
    parser.add_argument("--keep-strays", action="store_true",
                        help="keep senders that never appear as a receiver")
    parser.add_argument("--keep-odd-len", action="store_true",
                        help="keep frames whose length differs from the majority")
    args = parser.parse_args()

    rows = load(args.path)
    start = float(rows[0]["host_time_s"])
    span = float(rows[-1]["host_time_s"]) - start

    receivers = {row["rx_mac"] for row in rows}
    lengths = collections.Counter(int(row["len"]) for row in rows)
    common_len = lengths.most_common(1)[0][0]

    kept, strays, odd = [], set(), 0
    for row in rows:
        if not args.keep_strays and row["tx_mac"] not in receivers:
            strays.add(row["tx_mac"])
            continue
        if not args.keep_odd_len and int(row["len"]) != common_len:
            odd += 1
            continue
        kept.append(row)

    boards = sorted(receivers)
    print(f"{len(rows)} rows over {span:.1f}s  ({len(rows)/span:.0f} pkt/s)")
    print(f"{len(boards)} boards, {len({(r['rx_mac'], r['tx_mac']) for r in kept})} links")
    if strays:
        print(f"dropped {len(rows)-len(kept)-odd} packets from non-mesh senders: "
              f"{', '.join(sorted(strays))}  (--keep-strays to keep)")
    if odd:
        print(f"dropped {odd} frames not {common_len} bytes  (--keep-odd-len to keep)")
    print("\nNODE_POSITIONS = {")
    for mac in boards:
        print(f'    "{mac}": (0.0, 0.0),   # measure this board')
    print("}\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"replaying to {args.host}:{args.port} at {args.speed}x"
          f"{' on a loop' if args.loop else ''} (ctrl-c to stop)")
    try:
        while True:
            t0 = time.monotonic()
            for row in kept:
                due = (float(row["host_time_s"]) - start) / args.speed
                delay = due - (time.monotonic() - t0)
                if delay > 0:
                    time.sleep(delay)
                sock.sendto(build_packet(row), (args.host, args.port))
            if not args.loop:
                break
            print(f"  looped after {span/args.speed:.1f}s")
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
