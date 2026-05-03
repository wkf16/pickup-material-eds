# Phase 2 — handoff

> **Created**: 2026-05-03
> **Companion to**: `docs/phase2-design.md`, `docs/roadmap.md`

## What's in this Phase 2 commit

### Infrastructure (steps 1+2+3+4)

1. **VM autostart** — `sudo virsh autostart pickup-win10-ltsc` enabled on lab4070.
2. **Host-side USB recovery** — `pickup-eds-vm-recovery.service` runs 30 s after `libvirtd`, calls `/usr/local/bin/refresh-vm-usb.sh` to detach + re-attach the USB-6002 + 6514 USB-Serial. Workaround for qemu-xhci dropping passthrough state across host reboots.
3. **VM-side firstboot recovery** — `PickupEdsFirstBoot` scheduled task fires 30 s after Windows boot, runs `C:\setup\nirestore.ps1` as SYSTEM. Starts NI services (`nipalk`, `nidevldu`, mxssvr, etc.), kicks `pnputil /scan-devices` if no DAQ visible, probes 6514 IDN. Verified end-to-end: VM force-reboot → 95 s later all hardware recovered automatically.
4. **Sleep targets** — already masked (`sleep.target` etc.). Logind also pinned: `HandleLidSwitch=ignore`, `HandlePowerKey=ignore`, `IdleAction=ignore`.

### WebUI / bridge code

- New `BenchServiceProtocol` in `src/pickup_eds/instruments/base.py`. Both `SimulatedBenchService` and `RealBenchService` satisfy it. `api/{control,recording,data,ws}.py` type-hint against the protocol.
- New `RealBenchService` + `BridgeClient` in `src/pickup_eds/instruments/bridge.py`. WS state machine (disconnected → reconnecting → running → paused → error) with exponential backoff. SCPI control plane via REST; sample stream via WS binary frames.
- `AppState.bridge` extended (nullable `BridgeState`); `AppState.ao` added. `DaqState` got `state` / `channels` / `terminal` / `range_v` / `samples_emitted` / `overruns`.
- Six new endpoints: `POST /api/control/{daq/run, daq/pause, daq/stop, daq/single, ao/start, ao/stop}`.
- `api/main.py` lifespan now reads `PICKUP_EDS_BRIDGE_URL`. If set → `RealBenchService`. If unset → existing simulator path (unchanged).

### DAQ daemon (Windows VM)

- `src/pickup_eds/daq_daemon/{__main__, app, discovery, daq_worker, scpi_proxy, recovery}.py`.
- Binary frame format on `/ws/raw_stream`: `<IIfI` header (seq, n, sample_rate, channel_count) + `n × c × float32` interleaved samples.
- Lazy-imports `nidaqmx` / `pyserial` so the package is loadable on Linux too.
- Deployed via `scripts/deploy_daq_daemon.sh` → rsync to lab → WinRM-push to VM → fresh venv + pip install + scheduled task.

### Frontend

- 4 tabs: 实时 / 录制 / 6514 / 输出 AO. CSS-only show/hide via `body[data-active-tab]`.
- Bridge status indicator (top-right): colored dot + state name + RTT + seq.
- New "DAQ 控制" card (Live tab): sample rate / channel / terminal / range form + Run / Pause / Single / Stop buttons.
- New "输出 AO" card (AO tab): mode / channel / amplitude / freq form + Start / Stop. Free-run only; HW sync is Phase 2.5.

## What needs human eyeballs

I can verify HTTP / WS flows and on-disk artifacts. **I cannot watch a browser**. Please skim these:

1. **Tabs** — open `http://lab4070-c/` (or via Tailscale once it's back), confirm 4 tabs switch cleanly.
2. **Bridge dot** — colored dot in the header should be **green / "running"** when daemon is alive; pulses **yellow / "reconnecting"** if you `virsh detach-device .../usb_ni.xml --live` and snap it back in.
3. **Waveform** — Live tab should show a sliding scope at 30+ fps when DAQ is running. Phase 1 smoke verified the *backend* doesn't drop samples at 50 kHz × 60 s; only humans can judge "feels smooth."
4. **AO** tab fields toggling correctly with mode (DC / Sine / Sweep-* / Chirp).
5. **Recording history list** — after `phase2_smoke` (5-s baseline) recorded by verify script, the history list should show it with `[预览]` / `[下载]` buttons working.

## Operational notes

### Starting / restarting the bridge stack from scratch

```bash
# 1. Make sure the VM is up + recovered.
ssh lab4070-c 'echo 203 | sudo -S virsh --connect qemu:///system list --all'    # pickup-win10-ltsc running
ssh lab4070-c 'echo 203 | sudo -S /usr/local/bin/refresh-vm-usb.sh'             # USB rebind

# 2. Confirm daemon is alive on the VM.
ssh lab4070-c 'curl -s http://192.168.122.8:8765/api/health' | jq

# 3. Start (or restart) the WebUI with the bridge URL.
ssh lab4070-c 'export PICKUP_EDS_BRIDGE_URL=ws://192.168.122.8:8765/ws/raw_stream && systemctl --user restart pickup-eds-webui'

# 4. Verify.
python scripts/verify_phase2.py http://lab4070-c
```

### When the daq daemon needs a code update

```bash
bash scripts/deploy_daq_daemon.sh lab4070-c
```

This wipes `C:\setup\daq_daemon\src\`, replaces it with a fresh tarball, refreshes the venv only if missing, and restarts the scheduled task. Idempotent.

### When the lab machine reboots

Nothing manual. The chain is:

```
host boots
  ├─ libvirtd.service                       (enabled)
  │   └─ VM autostart                       (virsh autostart pickup-win10-ltsc)
  │       └─ Windows boots
  │           ├─ PickupEdsFirstBoot         (+30 s after Windows: NI services, USB phantom rescue)
  │           └─ PickupEdsDaqDaemon         (+60 s after Windows: FastAPI :8765)
  ├─ pickup-eds-vm-recovery.service         (host-side USB rebind, +30 s after libvirtd)
  └─ pickup-eds-webui.service               (FastAPI :80, bridge mode, after multi-user.target)
```

End-to-end, you can hit `http://lab4070-c/` within ~3 min of host power-on.
The webui starts immediately and goes through bridge `disconnected →
reconnecting → running` while the VM is still booting; the user just
sees the bridge dot pulse yellow then turn green.

### Failure isolation

| Symptom | Where to look |
|---|---|
| Browser shows bridge=disconnected | `ssh lab4070-c 'curl -s http://192.168.122.8:8765/api/health'` — daemon alive? |
| daemon health says no daq_device | `C:\setup\nirestore.log` — did NI services start? |
| /ws/raw_stream frames drop | `C:\setup\daq_daemon\daemon.log` — overrun reported? |
| /ws/stream (browser) frames drop | systemd journal of `pickup-eds-webui`; bridge state should also reflect |
| 6514 SCPI returns `ERR: bridge:...` | daemon log — COM3 still bound? Re-run `refresh-vm-usb.sh` |

## Phase 2 acceptance evidence

Run `scripts/verify_phase2.py http://lab4070-c` to drop a JSON report into `data/phase2_acceptance/`. The script covers six of the seven §2.5 criteria; the seventh (浏览器实际渲染顺滑) is a human check.

## Known gaps deferred to Phase 2.5 / 3

- AO + AI hardware-synchronized triggering (`/Dev1/ai/StartTrigger`).
- Implementation of AO modes on the daemon side (currently RealBenchService logs the request but the daemon doesn't drive ao0/ao1 yet).
- Chirp Bode one-button experiment.
- Parquet recording format (still `.npz`).
- Tailscale RTT-aware fps degradation.
- File-replay AO mode (UI option is disabled).

See `docs/phase2-design.md` §8 ("Explicitly out of scope") for the full list.
