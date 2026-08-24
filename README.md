# CSI

Any number of (in our case 6) ESP32s (all transmitting and receiving) distributed over a space detect movement through CSI.

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
and chewing [[1]](#references).

## How it works

Each board sends the CSI from every packet it receives to a laptop over UDP. A
filter pipeline smooths the raw amplitudes and reduces each link to a single
motion score, so a pair of boards reports one number for how disturbed the path
between them is.

Because every board hears every other board, the room is crossed by many
overlapping links. Radio tomography combines their scores into a grid, which
places movement somewhere in the room instead of only reporting that something
moved.

The phone app arms the system when the space should be empty. Movement that
holds above a threshold then latches an alarm and sends a push notification,
and the same grid is drawn on the phone so the movement can be followed while
it happens.

## Team Members

- Stefan Moldoveanu: [@STMPRODUCTION](https://github.com/STMPRODUCTION)
- Pricop Maia: [@maitable](https://github.com/maitable)
- Radu Ilie-Goga: [@RaduGoga](https://github.com/RaduGoga)
- Gatan Dragos: [@dragosgatan](https://github.com/dragosgatan)

## References

1. [esp-csi](https://github.com/espressif/esp-csi) - Espressif's Wi-Fi CSI applications repo
