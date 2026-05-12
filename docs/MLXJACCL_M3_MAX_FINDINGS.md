# MLXJACCL Findings For M3 Max + EXO Labs Pair

Date: April 11, 2026

## Objective

Get `mlxjaccl` working for EXO Labs with the highest-throughput path, preferably Tensor sharding over Thunderbolt RDMA instead of `mlx-ring` / MDMA fallback.

## Tested Pair

- Local Mac: MacBook Pro, Apple M3 Max
- Peer Mac: MacBook Pro, Apple M4 Max
- macOS: 26.4.1
- Build: 25E253
- MLX: 0.31.1
- EXO model path tested: `mlx-community/MiniMax-M2.5-6bit`

## What We Fixed Along The Way

- Removed `bridge100` / Thunderbolt bridge interference.
- Turned off Internet Sharing/NAT that was recreating `bridge100`.
- Forced EXO topology onto the direct Thunderbolt IP path instead of Wi-Fi.
- Rewrote EXO JACCL preview coordinators away from `0.0.0.0`.
- Got both nodes to discover each other correctly over:
  - local Thunderbolt IP `192.168.2.3`
  - peer Thunderbolt IP `192.168.2.4`
- Confirmed direct SSH between the Macs for `mlx.launch`.
- Confirmed the peer Mac could expose RDMA devices such as `rdma_en2`.

## What Still Failed

### EXO JACCL

Even after network cleanup and coordinator sanitization, EXO JACCL still failed at runtime with errors such as:

- `[jaccl] Couldn't allocate protection domain`
- `[jaccl] Couldn't connect (error: 60)`

These were not the root cause. They were downstream symptoms.

### Direct MLX JACCL Outside EXO

Direct `mlx.launch --backend jaccl` was also tested outside EXO using a custom benchmark. The result was the same class of failure:

- once the hostfile format and SSH issues were fixed, both ranks launched
- the job then stalled in distributed init / JACCL setup

This proved the remaining blocker was below EXO.

## Decisive Evidence

The local M3 Max never exposed any RDMA device through:

```bash
ibv_devices
```

even when all of the following were true:

- Thunderbolt peer showed `Device connected`
- the active Thunderbolt interface had a valid static IP
- the peer Mac exposed `rdma_en*`
- Apple RDMA kernel components were loaded

Loaded components on the local Mac included:

- `com.apple.iokit.IORDMAFamily`
- `com.apple.driver.AppleThunderboltRDMA`

However, the local kernel log showed the decisive reason:

```text
AppleThunderboltRDMAInterface... RDMA enabled, starting..
Thunderbolt controller does not support Thunderbolt 5, RDMA not supported. Exiting..
```

That message means macOS loaded the RDMA driver stack, attempted bring-up, then refused to expose Thunderbolt RDMA on the local controller.

## Conclusion

For this specific local machine:

- Thunderbolt IP networking works
- `mlx-ring` / MDMA can work
- `mlxjaccl` over Thunderbolt RDMA does not appear supported

The likely practical conclusion is:

- this Apple M3 Max Mac should be treated as `ring-only` for this EXO pair
- the current blocker is hardware/controller capability as enforced by macOS
- more EXO retries will not solve it

## What This Does Not Seem To Be

- not an EXO topology bug anymore
- not a `0.0.0.0` coordinator issue anymore
- not a bridge / Internet Sharing issue anymore
- not a plain Thunderbolt networking failure
- not obviously a bad reinstall or missing kernel extension

## Most Likely Current Root Cause

The local Apple M3 Max Thunderbolt controller is not accepted by macOS as Thunderbolt RDMA-capable for the `AppleThunderboltRDMA` path required by `mlxjaccl`.

The cable being Thunderbolt 4 is not the main evidence-based blocker here. The decisive blocker is the local controller capability check reported by macOS.

## Recommended Default State

Use the pair as:

- `mlx-ring` / MDMA fallback
- no further JACCL retries on this M3 Max pair unless one of the triggers below changes

## Retry Only If One Of These Changes

Retry `mlxjaccl` only if at least one of these becomes true:

1. Apple/macOS release notes or field reports show Thunderbolt RDMA support on M3 Max / Thunderbolt 4 systems.
2. A future macOS update removes the local kernel log message about Thunderbolt 5 RDMA not being supported.
3. `ibv_devices` on the local M3 Max starts showing a real `rdma_en*` device.
4. The local machine is replaced with a Mac that also exposes `rdma_en*`.
5. MLX / JACCL release notes explicitly mention support for the previously unsupported local controller path.

## Fast Re-Check Commands For The Future

Run these on the local Mac first:

```bash
system_profiler SPThunderboltDataType | sed -n '1,120p'
ibv_devices
/usr/bin/log show --last 2h --style compact --predicate 'eventMessage CONTAINS "Thunderbolt controller does not support Thunderbolt 5, RDMA not supported"' | tail -n 20
```

Interpretation:

- if `ibv_devices` is still empty and the kernel log still shows the Thunderbolt 5 RDMA rejection, stop and use `mlx-ring`
- if `ibv_devices` shows `rdma_en*`, then the block may be gone and JACCL is worth retesting

## Repo Artifacts Added During Investigation

- `/Users/ryan_chua/Desktop/capybara-home/scripts/check-jaccl-preflight.sh`
- `/Users/ryan_chua/Desktop/capybara-home/scripts/fix-macos-thunderbolt-network.sh`
- `/Users/ryan_chua/Desktop/capybara-home/scripts/validate-mlx-jaccl.sh`
- `/Users/ryan_chua/Desktop/capybara-home/scripts/start-minimax-m25-6bit-jaccl.sh`
- `/Users/ryan_chua/Desktop/capybara-home/scripts/bench_mlx_jaccl.py`
- `/Users/ryan_chua/Desktop/capybara-home/scripts/install-mlx-launch.sh`
- `/Users/ryan_chua/Desktop/capybara-home/scripts/capture-jaccl-diag.sh`
- `/Users/ryan_chua/Desktop/capybara-home/scripts/write-script.sh`

## Practical Recommendation

For this hardware pair, do not spend more time retrying `mlxjaccl` unless the local M3 Max starts exposing RDMA devices. The best working path today is the ring-based fallback.
