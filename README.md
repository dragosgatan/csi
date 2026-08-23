# Wi-Fi CSI Motion Detection


Five ESP32s (4 transmitters and 1 receiver) distributed over a space detect movement through CSI.

We are currently getting the hardware working: outputs are streamed through a port on serial.

## Live dashboard

The Python side listens for CSI UDP packets on port `6767` and serves a live browser dashboard on port `8080`.

Each receiver has a unique `NODE_ID` configured near the top of `hardware/csi_rx/csi_rx.ino`. Packets use the format `node_id,timestamp,rssi,length,` followed by the binary CSI values.

From the repository root, run:

```bash
python3 software/dashboard.py
```

Open `http://localhost:8080` on the laptop running the dashboard. The receiver board must send its UDP packets to that laptop's IP address. The dashboard shows one filtered amplitude heatmap per receiver node, with older packets on the left and the newest packet on the right, plus a motion score from the filtering pipeline. The raw dashboard data is also available at `http://localhost:8080/api/data`.

The streaming filter is available in `software/filter_pipeline.py`. Install its NumPy dependency with:

```bash
python3 -m pip install -r requirements.txt
```

It accepts alternating signed 8-bit I/Q frames through `CSIFilterPipeline.process_frame()` and returns a normalized motion score from `0.0` to `1.0`.

## What is CSI?

CSI (Channel State Information) describes the state of the wireless channel a
packet passed through. It records the signal's amplitude, its phase, and the
delay it accumulated in transit.

Those values depend on the physical environment. Anything that changes in the
room changes the channel, and that shows up in the CSI. Tracking the CSI over
time is therefore enough to infer what moved, which is what makes contactless
sensing possible.

Espressif reports that CSI registers large motion such as walking and running,
as well as smaller motion in an otherwise static environment, down to breathing
and chewing [1].

## References

1. [esp-csi](https://github.com/espressif/esp-csi) - Espressif's Wi-Fi CSI applications repo
