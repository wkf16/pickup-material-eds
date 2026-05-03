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

## 3. 与真实硬件对接的替换点

- `src/pickup_eds/instruments/simulator.py`
  当前所有控制和数据流都从这里生成。
- `src/pickup_eds/core/storage.py`
  当前是零编译依赖的 `.npz + SQLite` 落盘层。接真机时可以保留 API，单独把底层文件格式换回 `.parquet`。
- `src/pickup_eds/api/*.py`
  尽量保持不动，只换 service 注入对象。
