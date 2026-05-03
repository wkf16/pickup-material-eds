# 系统架构

> 这份文档描述目标产品(Web 实验台)的整体架构,以及它在已有硬件(Keithley 6514 + NI USB-6002 + Manjaro Lab Linux)之上如何组织。**当前状态(2026-05-03):Phase 1 ✅ 完成,Phase 2 设计已确认见 `phase2-design.md`,WebUI MVP 已合并(simulator-backed),真硬件接入开发中**。自 2026-05-03 起,DAQ 与串口驱动层运行在 **Windows VM**,WebUI 进程留在 **Lab Linux 主机**,两者用 **virtio-net 桥 + WebSocket 二进制流** 连接。

## 1. 一句话定位

一个 **WebUI 跑在 Lab Linux、DAQ daemon 跑在 Windows VM** 的两段式应用,把 `Keithley 6514 + NI USB-6002` 这套硬件包成"网页示波器 + 仪器虚拟前面板 + 实验数据管理器",支持远程实时监测、控制 6514、录制带类别标签的数据集、嵌入终端调试。

## 2. 顶层数据流

```
┌─────────────────────────────────────────────────────────────┐
│  Browser(LAN/Tailscale 任意位置)                            │
│   uPlot(实时滚动波形)+ FFT 频谱 + 控制表单                  │
└─────────────────────────────────────────────────────────────┘
                  ▲                       ▲
                  │ WebSocket             │ REST(JSON)
                  │ ~30 fps 默认          │ 控制命令
                  │ 720 点/帧 降采样      │
                  ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Lab Linux WebUI — FastAPI :80                              │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │ BridgeClient │   │ DecimateWS   │   │ Storage Mgr    │  │
│  │  (ws 长连)   │──▶│  → 浏览器     │   │ ring buffer    │  │
│  │  状态机       │   │  720pt/frame  │   │  + .npz/SQLite │  │
│  └──────┬───────┘   └──────────────┘   └────────────────┘  │
│         │ 二进制 WS 流(50 kHz × 4B)                          │
└─────────┼───────────────────────────────────────────────────┘
          │  192.168.122.0/24 virbr0,RTT < 0.5 ms
          ▼
┌─────────────────────────────────────────────────────────────┐
│  Windows VM DAQ Daemon — FastAPI :8765(仅 NAT 内)           │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │ DAQ Worker   │   │ SCPI Proxy   │   │ Recovery       │  │
│  │ nidaqmx 流采  │   │ pyserial 单例 │   │ COM/Dev 自动发现│  │
│  │ 50 kS/s      │   │ 6514 队列     │   │ NI 服务自动起   │  │
│  └──────┬───────┘   └──────┬────────┘   └────────────────┘  │
│         │                   │                               │
│         └───────────┬───────┘                               │
│                     ▼                                       │
│             公共状态(asyncio Lock + WS broadcast)            │
└─────────────────────────────────────────────────────────────┘
                  │                       │
                  ▼ USB                   ▼ RS-232 (USB-Serial)
        ┌──────────────────┐    ┌──────────────────────┐
        │  NI USB-6002     │    │  Keithley 6514       │
        │  16-bit, 50kS/s  │    │  V/I/Ω/Q 模式         │
        │  ±10V DIFF AI    │    │  9 档量程切换         │
        └────────┬─────────┘    │  Trigger Link out    │
                 │              └──────────┬───────────┘
                 │                         │
                 └────── 2V ANALOG OUT BNC ┘
                          │
                          ▼
                   ┌──────────────┐
                   │ 拾音材料(SLTS)│
                   └──────────────┘
```

## 3. 模块职责

### 3.1 Lab Linux WebUI — `src/pickup_eds/`(已合并 MVP)

```
src/pickup_eds/
├── instruments/
│   ├── electrometer_serial.py   # 现存 MVP,Phase 2 改成 BridgeClient 调 VM
│   ├── simulator.py             # 仅 dev 模式
│   └── bridge.py (TODO Phase 2) # 与 VM daq daemon 的 ws 客户端 + 状态机
├── core/
│   ├── ring_buffer.py
│   └── storage.py               # .npz + SQLite
├── api/
│   ├── main.py                  # FastAPI :80 入口
│   ├── ws.py                    # /ws/stream  /ws/state (浏览器侧)
│   ├── control.py               # REST 控制
│   ├── recording.py             # REST 录制
│   └── data.py                  # REST 数据列表 / 预览 / 下载
├── schemas.py
├── config.py
└── web/
    ├── index.html               # 单文件 (Alpine + uPlot 内嵌)
    └── favicon.png
```

### 3.1.5 Windows VM DAQ Daemon — `src/pickup_eds/daq_daemon/`(Phase 2 新增)

```
daq_daemon/
├── app.py            # FastAPI :8765 入口
├── discovery.py      # USB-6002 + 6514 自动发现
├── daq_worker.py     # nidaqmx Task + ring buffer + 二进制 ws 推送
├── scpi_proxy.py     # pyserial 单例 + 命令队列
└── recovery.py       # 启动时检查/启动 NI 服务、phantom 处理
```

详见 `phase2-design.md` 第 1、6 节。

### 3.2 关键设计原则

#### 原则 1:**显示降采样 vs 存储全速分离**
- 浏览器收 ~1 kS/s 流(降采样 50×),uPlot 流畅渲染
- 磁盘存 50 kS/s 全分辨率
- 历史回放时按需切片,客户端只看到与窗口宽度匹配的密度

#### 原则 2:**触发逻辑放后端**
- 阈值检测、边沿检测在后端 numpy 实时跑
- 命中后冻结一帧"快照"(前 N ms + 后 M ms)推前端
- 浏览器 JS 实时性差,不能依赖它做触发

#### 原则 3:**仪器单例 + asyncio Lock**
- 6514 串口、USB-6002 句柄都是物理硬件单例
- 多个 web 请求并发 → 必须串行化
- 单进程 uvicorn 不开 worker pool,避免句柄竞争

#### 原则 3.5:**把 NI 驱动问题隔离在 Windows guest**
- 宿主机保留 Manjaro,不为了 DAQ 驱动重装系统
- guest 拿走 `USB-6002 + USB-Serial` 直通
- Web 应用和驱动层放在同一 guest 内,先保证链路简单

#### 原则 4:**先做 LAN-only,鉴权简化**
- Tailscale 网络已经是事实上的认证层
- HTTP Basic Auth 加一层(< 10 行代码)
- 不引入 JWT / OAuth / RBAC——研究项目体量不需要

## 4. 选型决策(简表,详见 `decisions.md`)

| 件 | 选 | 主要原因 |
|---|---|---|
| Web 框架 | **FastAPI + uvicorn** | async 友好,WebSocket 一行,Pydantic 类型安全 |
| 前端框架 | **vanilla HTML + Alpine.js** | 千行项目无需 React,Alpine.js 200 字够 |
| 实时绘图 | **uPlot** | 比 Plotly 快 10-100×,流式 50k 点 60fps |
| 数据格式 | **Parquet (pyarrow)** | 列式压缩,直接 pandas/dask 加载训 ML |
| 元数据 | **SQLite** | 单文件,无服务,够 1000 实验级 |
| 终端 | **ttyd** | 单 C 二进制,Manjaro AUR 有 |
| 部署 | **systemd 用户单元** | reboot 自启,无 docker 复杂度 |
| 鉴权 | HTTP Basic + Tailscale | 内网+VPN,不过度工程 |

## 5. 核心 REST/WebSocket 端点(契约)

### REST(控制)

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/state` | 读 6514 + DAQ 当前完整状态 |
| POST | `/api/control/function` | `{"func": "VOLT"}` |
| POST | `/api/control/range` | `{"range": 2.0}` |
| POST | `/api/control/zero-check` | `{"on": true}` |
| POST | `/api/control/zero-correct` | `{"on": true}` |
| POST | `/api/recording/start` | `{"label": "B12", "duration_s": 5}` |
| POST | `/api/recording/stop` | 停止当前录制 |
| GET | `/api/data/list` | 列出已存储数据集 |
| GET | `/api/data/{id}/download` | 下载 .parquet |
| GET | `/api/data/{id}/preview` | 返回降采样后的预览波形 |

### WebSocket(流)

| 路径 | 用途 |
|---|---|
| `/ws/stream` | 持续推送降采样波形(每 ~50 ms 一帧) |
| `/ws/state` | 推送状态变更通知(谁切了量程、录制开始/结束) |
| `/ws/snapshot` | 触发命中时的高分辨率快照 |

## 6. 性能边界(继承自硬件,详见 `docs/exp-01-bandwidth-test.md` 附录)

| 维度 | 上限 | 备注 |
|---|---|---|
| AI 采样率 | 50 kS/s 单通道 | USB-6002 硬限 |
| 同时通道 | 1 路用满,4 路 12.5 kS/s | MUX 复用,有 µs skew |
| AO 激励 | 5 kS/s,即 < 2.5 kHz | 推不了高频音频激励 |
| 持续录制 | 8.6 GB/天 @ 50 kS/s | 磁盘 733 GB → 85 天 |
| 浏览器流量 | < 1 MB/s | 后端降采样后 |
| 端到端延迟 | ~50-200 ms | USB FIFO + 网络 + 渲染 |

## 7. 部署拓扑

```
┌────────────────────────── Lab Linux (Manjaro) ──────────────────────────┐
│                                                                        │
│  systemd services:                                                     │
│    ─ libvirtd.service           (KVM/libvirt)                          │
│    ─ pickup-eds-webui.service   :80   (Lab Linux 的 FastAPI)           │
│    ─ 可选: ttyd.service         :7681 (宿主机终端)                     │
│                                                                        │
│  Windows 10 LTSC VM (192.168.122.8):                                   │
│    ─ pickup-eds-daq.service    :8765  (DAQ daemon, NAT 内)             │
│    ─ USB passthrough: USB-6002 + 6514 USB-Serial                       │
│                                                                        │
│  访问方式:                                                              │
│    ─ 浏览器 → http://lab4070/        (Tailscale 任意位置)              │
│    ─ Linux WebUI → ws 连 192.168.122.8:8765 (内部桥)                  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

未来扩展(Phase 3+):
- nginx 反代 + TLS(若需要做正式 demo)
- 多用户 + 实验隔离(若多人协作)
- 推理服务(把训练好的 ResNet 加载,实时分类预测)

## 8. 与已有脚本的关系

`scripts/` 下的三个独立工具是**模块的"裸版本"**——通过单元测试 src 模块的函数后,scripts 自然成为"穷人版 demo"。**不会废弃**。

| scripts/ 文件 | 对应 src 模块 |
|---|---|
| `gen_chirp.py` | (本机使用,无对应) |
| `capture_freqresp.py` | `instruments/daq.py` + `instruments/electrometer.py` |
| `analyze_bode.py` | `core/storage.py`(读取) + 用户分析层 |

## 9. 不在本架构内的事(留意)

- ❌ 不做 ML 训练 web 化(留 jupyter / CLI)
- ❌ 不做仪器多型号通用抽象(单单为 6514+USB-6002 写)
- ❌ 不做用户管理 / RBAC
- ❌ 不做云端部署(纯本地)

这些是为了**节制范围**——研究工具不是 SaaS,克制比扩张更重要。
