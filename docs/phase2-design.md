# Phase 2 设计：WebUI + 真硬件接入（Linux + VM 桥架构）

> **创建日期**：2026-05-03  
> **状态**：设计已确认，等待实现  
> **关联文档**：`architecture.md`（顶层）、`webui-mvp-delivery.md`（MVP 现状）、`api-reference.md`（接口契约）、`performance.md`（容量模型）、`windows-vm-plan.md` §10（VM 重启恢复）

## 0. 一句话

把已经搭好的 **WebUI MVP（在 Lab Linux 上跑，simulator 喂数据）** 改成一个 **"WebUI 仍在 Linux + 真 DAQ daemon 在 Windows VM 内"** 的两段式架构，桥用 WebSocket / HTTP，DAQ 任务在 VM 内跑 `nidaqmx.Task`，6514 SCPI 也由 VM 端 daemon 代理。

## 1. 拓扑

```
                     Browser (LAN / Tailscale)
                         │
                         │  HTTP (80) + WebSocket
                         ▼
┌────────────── Lab Linux (Manjaro) ──────────────┐
│                                                 │
│  pickup-eds-webui.service  (端口 80)            │
│   ├── /  index.html + uPlot                     │
│   ├── REST  /api/control/* /api/recording/*     │
│   └── WS    /ws/stream  /ws/state               │
│                                                 │
│   后端 BenchService（替换 SimulatedBenchService）│
│   ├── 与 VM daemon 维持长连接 (内网 ws)          │
│   ├── 接收原始 50 kS/s 二进制流                  │
│   ├── 降采样到 720 点 / 帧                       │
│   ├── 落盘 .npz + SQLite 元数据                  │
│   └── 桥状态机（disconnected / running / ...）   │
│                                                 │
└──────────────┬──────────────────────────────────┘
               │
               │  192.168.122.0/24 (virbr0, 同主机 virtio-net)
               │  实测 RTT < 0.5 ms / 1 MB < 10 ms
               ▼
┌──────────── Windows VM (pickup-win10-ltsc) ──────────┐
│                                                       │
│  pickup-eds-daq.service  (端口 8765, 仅监听 NAT)      │
│   REST                                                │
│     POST /api/daq/start   { sample_rate, channels,    │
│                              terminal, range }        │
│     POST /api/daq/stop                                │
│     GET  /api/daq/status                              │
│     POST /api/scpi/send   { cmd } → resp              │
│     GET  /api/scpi/state                              │
│   WebSocket                                           │
│     /ws/raw_stream  二进制帧                          │
│       header (uint32 seq, uint32 n, float32 sr) +     │
│       payload (n × float32 little-endian)             │
│                                                       │
│  内部                                                  │
│   ├── nidaqmx.Task（专用线程，read_into 预分配 buf）  │
│   ├── pyserial COM auto-discovery（认 IDN）           │
│   ├── 自带启动恢复（USB phantom / nidevldu / 服务起） │
│   └── 不写盘                                           │
│                                                       │
│  USB 直通                                              │
│   ├── 0x3923:0x76c4  USB-6002  → Dev1                 │
│   └── 0x067B:0x23A3  PL2303GT  → COMx (动态)          │
└───────────────────────────────────────────────────────┘
```

## 2. 桥状态机（Linux 侧 BenchService 视角）

```
disconnected ──(connect ws ok)──▶ connected_idle ──(start)──▶ running
     ▲                                  ▲                       │
     │                                  │ stop                  │ pause/resume
     │ socket lost                      │                       ▼
     └─────────────────── reconnecting        ◀──────── paused ─┘
                                │
                                └──(N retries)──▶ error (manual retry)
```

| 状态 | 前端 UI | DAQ 任务 | 显示帧 |
|---|---|---|---|
| `disconnected` | 灰点 / "桥未连" / 控件 disabled | — | — |
| `reconnecting` | 黄点闪 / 倒计时 | — | — |
| `connected_idle` | 绿点 / "待机" / Run 按钮亮 | 未启 | — |
| `running` | 绿点 / "采集中" | 启动 | 推送 |
| `paused` | 蓝点 / "已暂停" | 启动（buffer 继续涨） | 不推送 |
| `error` | 红点 / 错误信息 | — | — |

重连策略：指数退避 1s/2s/4s/8s/8s…，5 次失败后进入 `error`，按钮变"重试"。

## 3. 数据流：50 kHz 不崩的关键

直接列已知坑 + 规避：

| 坑 | 规避 |
|---|---|
| `task.read()` 在 asyncio 主循环里阻塞 | DAQ 读放 **专用线程**，event loop 只碰 ring buffer |
| 把原始 50 kHz JSON 喂浏览器（~1 MB/s 字符串） | 降采样**在后端**完成（VM 把原始流送 Linux，Linux 降采样到 720 点 / 帧后再下发浏览器） |
| ring buffer 无界 → OOM | 固定 `numpy.float32` 数组 + 写指针环回，**满了覆盖最旧** |
| 每块 `numpy.array(list)` → GC 风暴 | `task.read_into(buf)` 复用预分配 buffer |
| WebSocket 用 JSON 文本帧 | **样本流走二进制**：`struct.pack` header + `float32` 字节，控制平面才用 JSON |
| 录制时既写盘又走 WS → IO 抢 CPU | 写盘 **只在 Linux 侧**，VM daemon 不写盘（数据过桥后即扔）|

50 kHz × 4 byte = 200 KB/s 单通道；4 通道 × 50 kHz = 800 KB/s。virtio bridge 实测吞吐没问题（HTTP 200 ms 内拉 1 MB，理论上限远高于此）。

## 4. 自动发现：COM 口换位置 / Dev 名变化都能跑

VM daemon 启动 + 每次 disconnected→running 都跑：

```python
def find_keithley_com() -> str:
    # 1) 优先 PnP，过滤 vendor 0x067B & product 0x23A3 的 USB 设备
    candidates = enumerate_pnp_serial_ports(vid=0x067B, pid=0x23A3)
    # 2) fallback：扫所有 COMx
    if not candidates:
        candidates = list_all_com_ports()
    # 3) 每个候选发 *IDN?，2 秒超时
    for com in candidates:
        with serial.Serial(com, 9600, timeout=2) as p:
            p.write(b'*IDN?\r\n'); time.sleep(0.3)
            resp = p.read(p.in_waiting).decode(errors='replace')
            if 'KEITHLEY' in resp and 'MODEL 6514' in resp:
                return com
    raise RuntimeError("no 6514 found")

def find_usb6002() -> str:
    sys = nidaqmx.system.System.local()
    for dev in sys.devices:
        if dev.product_type == 'USB-6002':
            return dev.name  # 'Dev1' / 'Dev2' / ...
    raise RuntimeError("no USB-6002 found")
```

`/api/scpi/state` 返回当前用的 COM 名，前端右上角小字显示 "6514 on COM4 / Dev1"，做诊断用。**前端永远不需要让用户填这两个名字**。

VM 重启后还需要的恢复步骤（USB phantom + `nidevldu` + 偶尔 `palSetup64.msi`）见 `windows-vm-plan.md §10`。Phase 2 把这些自动化进 daemon 启动逻辑里：

1. 启动时如果 nidaqmx 看不到 USB-6002 → 调一次 `nipnp /scan-devices` + 等 2 秒重试
2. 如果 nipalk 服务未启 → `Start-Service nipalk`（需要 daemon 用 admin 跑）
3. 如果 mxssvr/nidevldu 未启 → 顺带 Start-Service
4. 仍失败 → 把错误状态向 Linux 侧上报（桥 → `error`），让人看 daemon 日志而不是 daemon 卡死

## 5. 前端 Tab 布局

```
┌─────────────────────────────────────────────────────┐
│ [实时]  [录制]  [6514]  [输出 AO]    🟢 桥已连·30 fps │
├─────────────────────────────────────────────────────┤
│  Tab 内容                                            │
└─────────────────────────────────────────────────────┘
```

### Tab 1：实时（默认）

```
DAQ 配置                          运行控制
─────────                         ────────
采样率   [▼ 1k │ 5k │ 10k │ 25k │ 50k]   [▶ Run]   [○ Single]    [■ ⊗]
通道     [☑ai0 ☐ai1 ... ☐ai7]            ↑ 主按钮  ↑ 单帧抓拍   ↑ 右上角小图标 (Stop)
端接     [● RSE  ○ DIFF]
量程     [▼ ±10V │ ±5V │ ±2V │ ±1V]

显示降采样
显示窗口 [▼ 0.1s │ 0.5s │ 1s │ 5s │ 10s]
显示刷新 [▼ 5 │ 10 │ 30 │ 60 fps]   (默认 30)

┌────────────────── waveform (uPlot) ──────────────────┐
│                                                      │
│   ↑ Run 状态：滚动；Pause 状态：冻结，可拖时间轴回看 │
└──────────────────────────────────────────────────────┘
```

**按钮语义**：
- **▶ Run / ⏸ Pause**（主按钮，切换）：DAQ 任务一直跑，buffer 一直涨；Pause 只冻结显示，可用鼠标拖时间轴回看 buffer 中已采但未显示的样本
- **○ Single**：触发一次单帧捕获（满一窗后自动 Pause）
- **■ ⊗**（右上角小图标，Stop）：完全停 DAQ 任务，释放 USB；需要再 Run 时重启 task

### Tab 2：录制

```
标签       [____________________]
时长       [___] 秒         (0.5–3600)
落盘格式   [● .npz   ○ .parquet (TODO)]
附加记录   [☐ 6514 SCPI 测量值（@ 1 Hz 采样)]

[ ▶ 开始录制 ]    剩余 12.3 s ▓▓▓▓░░░░

历史记录
─────────
2026-05-03 13:11   baseline      60s   3.0M    [预览] [下载]
2026-05-03 13:09   test          1s    50k     [预览] [下载]
…
```

录制走的是后端 ring buffer 的 tap：开始录制时不另启 DAQ task，而是从 BenchService 的 ring buffer **复制一份**到磁盘队列。停止时 flush + 写元数据到 SQLite。

### Tab 3：6514 SCPI（保留 MVP 现状）

现有的 function/range/zero-check/zero-correct 按钮 + SCPI 控制台。Phase 2 这层不变，只是数据通路改成"前端 → Linux WebUI → VM daemon → COMx"，VM daemon 替了原 `electrometer_serial.py` 的位置。

### Tab 4：输出 AO

```
AO 通道   [● ao0   ○ ao1]
模式      [▼ DC │ Sine │ Sweep-lin │ Sweep-log │ Chirp │ File replay]

— 当 模式 = Sine：
  频率   [____] Hz    (≤ 2.5 kHz @ AO 5 kS/s)
  幅度   [____] V     (±5 V)
  时长   [____] 秒    (留空 = 持续)

— 当 模式 = Sweep-log：
  起始   [____] Hz
  终止   [____] Hz
  时长   [____] 秒
  幅度   [____] V

触发     [● Free run   ○ 与 AI 同步触发（HW，Phase 2.5 启用）]

[ ▶ 开始输出 ]   [ ■ 停止 ]
```

**Phase 2 里 AO 只做 Free run**，HW 同步留 Phase 2.5（需要在 daemon 里配 `start_trigger.cfg_dig_edge_start_trig('/Dev1/ai/StartTrigger')`，前端 UX 也要改）。

### 取消的 Tab

~~实验预设（实验 01 一键跑）~~ — 范围太大，等 Phase 3 / 实验文档定型再做。

## 6. API 契约（VM daemon ⇄ Linux WebUI）

VM daemon 监听 `192.168.122.8:8765`，仅 NAT 内网访问。

### REST

```
GET  /api/health
  → 200 { status, daq_device, scpi_com, uptime_s }

POST /api/daq/start
  body { sample_rate_hz, channels: [ai0, ...], terminal: RSE|DIFF,
         range_v: 10|5|2|1 }
  → 200 { task_id, started_at } | 4xx { error }

POST /api/daq/stop
  → 200 {}

GET  /api/daq/status
  → { state: idle|running, sample_rate_hz, channels, samples_emitted }

POST /api/scpi/send       body { cmd }
  → { resp, elapsed_ms } | 5xx { error }

GET  /api/scpi/state
  → { com, idn, function, range, zero_check, zero_correct, last_seen_at }
```

### WebSocket

`/ws/raw_stream` — 单向（VM → Linux）：

```
  Frame layout (binary):
    [0..3]   uint32 LE   sequence number (单调递增)
    [4..7]   uint32 LE   sample count n (per channel)
    [8..11]  float32 LE  sample_rate_hz (echo back, sanity)
    [12..15] uint32 LE   channel count c
    [16..]   float32[]   n*c samples, 通道交错 (ch0_s0, ch1_s0, ch0_s1, ...)
```

Linux 侧维护 ring buffer，每 `~1000/fps` ms 派一帧给浏览器（已降采样 + JSON 文本）。

## 7. 落地步骤（提议的实现顺序）

按依赖排：

1. **`pyproject.toml` + `nidaqmx` 依赖**（VM 侧）
2. **`src/pickup_eds/daq_daemon/`**（新模块，VM 内独立 entry point）
   - `discovery.py`：USB-6002 / 6514 自动发现
   - `daq_worker.py`：nidaqmx Task + ring buffer + 二进制 WS push
   - `scpi_proxy.py`：pyserial 单例 + 命令队列
   - `recovery.py`：启动时检查/启动 NI 服务
   - `app.py`：FastAPI 入口
3. **VM 侧部署**：Windows scheduled task / NSSM 把 daemon 装成服务，开机 8765 监听
4. **`src/pickup_eds/instruments/bridge.py`**（Linux 侧新模块）
   - `BridgeClient`：WS 客户端 + 状态机 + 指数重连
   - `RealBenchService`（替换 `SimulatedBenchService`）：用 `BridgeClient` 喂 ring buffer
5. **`src/pickup_eds/api/main.py`**：新增 `--bridge ws://192.168.122.8:8765` flag，simulator 默认保留作 fallback
6. **前端 `index.html`**：
   - 新加 Tab 1 控件（采样率/通道/端接/量程/fps/窗口）
   - Run/Pause/Stop/Single 按钮
   - 桥状态指示灯
   - Tab 4 AO 控件（Free run 模式）
7. **6514 自动发现替换 hardcoded `/dev/ttyUSB0`**：现有 `electrometer_serial.py` 的端口字串改成"问 daemon 拿"
8. **`docs/api-reference.md` 更新**：补 `/api/daq/*` `/ws/raw_stream` `/api/scpi/state` 三组接口、AO 接口、桥状态枚举
9. **桥端到端测试**：lab 上跑一次 50 kHz × 60s 不崩

## 8. 显式不做的事（Phase 2 范围之外）

- ❌ AO 与 AI 硬件同步触发（→ Phase 2.5）
- ❌ 实验 01 chirp Bode 一键跑（→ Phase 2.5 / 3）
- ❌ Parquet 落盘（PyArrow 编译麻烦先放 .npz；Phase 3+ 再换）
- ❌ 多用户/鉴权（Tailscale 已经是事实认证层）
- ❌ FFT 实时频谱面板（Phase 3 再做）
- ❌ 历史回放高分辨率拉伸（Phase 3）

## 9. 待确认 / 留作 TODO

- 录制时如果 DAQ 配置（采样率/通道）中途变化怎么办？目前设计：录制中**不允许改 DAQ 配置**（前端把那些控件 disable）；如果用户硬要改，提示"先停录制"
- AO 的"File replay" 模式输入文件用什么格式？暂定 .npy（一维 float32），元数据从文件名解析采样率
- Tailscale 远程访问时，桥的 RTT 监测要不要做？前端是否要降级到 10 fps 以避免 stutter？暂定不做，先看实际体验
