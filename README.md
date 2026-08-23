# Wi-Fi CSI Motion Detection


Five ESP32s (all transmitting and receiving) distributed over a space detect movement through CSI.


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
