# WebUI API Reference

> 更新日期: 2026-05-03  
> 当前实现: `simulated-webui-mvp`

这份文档对应 `codex/webui-wt` 分支中已经落地的 Phase 2 WebUI 契约。真实 `6514 + USB-6002` 接入时，**优先保持这些路径和 JSON 结构稳定**，只替换后端 service 实现。

## 1. REST

### `GET /api/health`

返回服务健康状态。

```json
{
  "ok": true,
  "mode": "simulated-webui-mvp"
}
```

### `GET /api/state`

返回页面初始化所需的完整状态。

```json
{
  "updated_at": "2026-05-03T02:55:00.000000+00:00",
  "control": {
    "function": "VOLT",
    "range": 2.0,
    "zero_check": false,
    "zero_correct": false
  },
  "daq": {
    "sample_rate_hz": 5000,
    "display_window_s": 8.0,
    "live_rms": 0.353,
    "live_peak": 0.542,
    "display_points": 720
  },
  "recording": {
    "active": false,
    "label": null,
    "started_at": null,
    "duration_s": null,
    "sample_count": 0,
    "last_dataset_id": "20260503T025410Z-2d84d001"
  },
  "datasets": [],
  "scpi_port": "COM3 (simulated)",
  "scpi_log": [
    {
      "at": "2026-05-03T02:55:00.000000+00:00",
      "port": "COM3 (simulated)",
      "command": "*IDN?",
      "response": "KEITHLEY INSTRUMENTS INC.,MODEL 6514,4691930,1.0-sim",
      "ok": true
    }
  ]
}
```

### `POST /api/control/function`

请求:

```json
{
  "func": "VOLT"
}
```

### `POST /api/control/range`

请求:

```json
{
  "range": 2.0
}
```

### `POST /api/control/zero-check`

请求:

```json
{
  "on": true
}
```

### `POST /api/control/zero-correct`

请求:

```json
{
  "on": false
}
```

以上四个控制端点统一返回:

```json
{
  "ok": true,
  "state": {
    "...": "same as GET /api/state"
  }
}
```

### `GET /api/control/scpi/log`

返回最近的 COM/SCPI 调试记录。

```json
{
  "port": "COM3 (simulated)",
  "items": [
    {
      "at": "2026-05-03T03:10:00.000000+00:00",
      "port": "COM3 (simulated)",
      "command": "*IDN?",
      "response": "KEITHLEY INSTRUMENTS INC.,MODEL 6514,4691930,1.0-sim",
      "ok": true
    }
  ]
}
```

### `POST /api/control/scpi/send`

请求:

```json
{
  "command": "*IDN?"
}
```

返回:

```json
{
  "ok": true,
  "entry": {
    "at": "2026-05-03T03:10:00.000000+00:00",
    "port": "COM3 (simulated)",
    "command": "*IDN?",
    "response": "KEITHLEY INSTRUMENTS INC.,MODEL 6514,4691930,1.0-sim",
    "ok": true
  },
  "state": {
    "...": "same as GET /api/state"
  }
}
```

### `POST /api/recording/start`

请求:

```json
{
  "label": "baseline",
  "duration_s": 5
}
```

若已在录制，返回 `409`.

### `POST /api/recording/stop`

返回:

```json
{
  "ok": true,
  "state": {
    "...": "same as GET /api/state"
  },
  "dataset": {
    "id": "20260503T025410Z-2d84d001",
    "label": "baseline",
    "created_at": "2026-05-03T02:54:10.000000+00:00",
    "duration_s": 4.98,
    "sample_rate_hz": 5000,
    "sample_count": 25000,
    "file_path": "data/recordings/20260503_025410_baseline.npz",
    "file_size_bytes": 146712,
    "min_value": -0.54,
    "max_value": 0.55
  }
}
```

### `GET /api/data/list`

返回历史录制列表。

```json
{
  "items": [
    {
      "id": "20260503T025410Z-2d84d001",
      "label": "baseline",
      "created_at": "2026-05-03T02:54:10.000000+00:00",
      "duration_s": 4.98,
      "sample_rate_hz": 5000,
      "sample_count": 25000,
      "file_path": "data/recordings/20260503_025410_baseline.npz",
      "file_size_bytes": 146712,
      "min_value": -0.54,
      "max_value": 0.55
    }
  ]
}
```

### `GET /api/data/{id}/preview`

返回降采样预览。

```json
{
  "id": "20260503T025410Z-2d84d001",
  "label": "baseline",
  "sample_rate_hz": 5000,
  "time_s": [0.0, 0.01, 0.02],
  "value": [0.01, 0.04, -0.02]
}
```

### `GET /api/data/{id}/download`

直接下载当前录制文件。当前 MVP 为 `.npz`，真实 DAQ 接入阶段建议切换回文档原计划的 `.parquet`。

## 2. WebSocket

### `/ws/stream`

约 10 fps 推送滚动波形:

```json
{
  "seq": 42,
  "sample_rate_hz": 5000,
  "time_s": [0.0, 0.011, 0.022],
  "value": [0.12, 0.21, 0.17],
  "rms": 0.35,
  "peak": 0.55
}
```

### `/ws/state`

推送状态变化。结构与 `GET /api/state` 一致。

### `/ws/snapshot`

已占位。当前返回:

```json
{
  "available": false,
  "message": "Snapshot triggering is reserved for the real DAQ backend."
}
```

## 2.5 Phase 2 控制端点（DAQ + AO）

WebUI 的左侧控制路径在 Phase 2 引入了 DAQ task control 和 AO（free run）控制。在 simulator 模式下这些端点把状态写到 `AppState`；在 bridge 模式下转发到 VM daq daemon。

### `POST /api/control/daq/run`

```json
{
  "sample_rate_hz": 50000,
  "channels": ["ai0"],
  "terminal": "RSE",
  "range_v": 10.0
}
```

`terminal` ∈ `{RSE, DIFF}`；`range_v` ∈ `{10, 5, 2, 1}`。

### `POST /api/control/daq/pause`

仅冻结显示（DAQ task 在 daemon 侧继续跑）。请求体空。

### `POST /api/control/daq/stop`

请求体空。停 daemon 侧 task。

### `POST /api/control/daq/single`

请求体同 `/daq/run`。Phase 2 等同 run（窗口结束逻辑留给 Phase 3）。

### `POST /api/control/ao/start`

```json
{
  "mode": "Sine",
  "channel": "ao0",
  "params": { "amp_v": 1.0, "freq_hz": 1000, "freq_end_hz": 2000, "duration_s": 5 }
}
```

`mode` ∈ `{DC, Sine, Sweep-lin, Sweep-log, Chirp, File replay}`，`File replay` 暂未实现。

### `POST /api/control/ao/stop`

请求体空。

### Phase 2 `AppState` 扩展

```json
{
  "...": "Phase 1 fields",
  "daq": {
    "...": "Phase 1 fields",
    "state": "running",
    "channels": ["ai0"],
    "terminal": "RSE",
    "range_v": 10.0,
    "samples_emitted": 1500000,
    "overruns": 0
  },
  "ao": {
    "state": "running",
    "mode": "Sine",
    "channel": "ao0",
    "params": { "freq_hz": 1000 }
  },
  "bridge": {
    "state": "running",
    "daemon_addr": "ws://192.168.122.8:8765/ws/raw_stream",
    "rtt_ms": 0.4,
    "last_seq": 12345,
    "last_error": null
  }
}
```

`bridge` 在 simulator 模式下为 `null`。

## 3. VM DAQ daemon (`/api/...` on `:8765`)

仅在 LAN（virbr0）内监听。Linux 侧 BridgeClient 是唯一调用方；前端不直接访问。

| 端点 | 说明 |
|---|---|
| `GET /api/health` | `{ok, daq_device, scpi_com, scpi_idn, daq_state, samples_emitted, overruns}` |
| `POST /api/daq/start` | body `{sample_rate_hz, channels, terminal, range_v}` |
| `POST /api/daq/stop` | — |
| `GET /api/daq/status` | `{state, samples_emitted, overruns, seq_counter, last_error}` |
| `POST /api/scpi/send` | body `{cmd}` → `{ok, resp, elapsed_ms}` |
| `GET /api/scpi/state` | `{available, com, idn}` |
| `WS /ws/raw_stream` | binary frames, header `<IIfI>` (seq, n, sr, c) + `n×c×float32` |

帧布局（小端字节序）：

```
[0..3]  uint32  seq      (单调递增)
[4..7]  uint32  n        (samples per channel)
[8..11] float32 sr       (sample_rate_hz)
[12..15] uint32 c        (channel count)
[16..]  float32[]        n*c samples, ch-interleaved (ch0_s0, ch1_s0, ch0_s1, ...)
```

## 4. 服务实现注入点

- `src/pickup_eds/instruments/base.py`
  `BenchServiceProtocol` —— 三个实现都按它的方法签名走，`api/*.py` 类型注解用它。
- `src/pickup_eds/instruments/simulator.py`
  原 MVP 实现，simulator 模式默认值。
- `src/pickup_eds/instruments/bridge.py`
  `BridgeClient` + `RealBenchService` —— bridge 模式的实现，环境变量 `PICKUP_EDS_BRIDGE_URL` 触发。
- `src/pickup_eds/daq_daemon/`
  Windows VM 侧服务，部署到 `C:\setup\daq_daemon\`。
