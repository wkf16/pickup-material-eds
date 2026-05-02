# 系统架构

> 这份文档描述目标产品(Web 实验台)的整体架构,以及它在已有硬件(Keithley 6514 + NI USB-6002 + Manjaro Lab Linux)之上如何组织。**当前状态:设计阶段,代码尚未写**——见 `roadmap.md` 的 Phase 2。自 2026-05-03 起,DAQ 与串口驱动层迁移为 **Windows VM 方案**。

## 1. 一句话定位

一个**运行在 Windows VM 上、由 Lab Linux 承载的内网 Web 应用**,把 `Keithley 6514 + NI USB-6002` 这套硬件包成"网页示波器 + 仪器虚拟前面板 + 实验数据管理器",支持远程实时监测、控制 6514、录制带类别标签的数据集、嵌入终端调试。

## 2. 顶层数据流

```
┌─────────────────────────────────────────────────────────────┐
│  Browser(LAN/Tailscale 任意位置)                            │
│   uPlot(实时滚动波形)+ FFT 频谱 + 控制表单                  │
└─────────────────────────────────────────────────────────────┘
                  ▲                       ▲
                  │ WebSocket             │ REST(JSON)
                  │ ~10-50 fps            │ 控制命令
                  │ 降采样后波形          │
                  ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Windows VM 后端 — FastAPI + uvicorn(单进程,asyncio)       │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │ DAQ Worker   │   │ 6514 Worker  │   │ Storage Mgr    │  │
│  │ nidaqmx 流采  │   │ pyserial-async│   │ ring buffer    │  │
│  │ 50 kS/s      │   │ SCPI lock     │   │  + Parquet/npy │  │
│  └──────┬───────┘   └──────┬────────┘   └────────────────┘  │
│         │                   │                               │
│         └───────────┬───────┘                               │
│                     ▼                                       │
│             公共状态总线(asyncio Event/Queue)               │
└─────────────────────────────────────────────────────────────┘
                  ▲
                  │ KVM / libvirt / USB passthrough
                  ▼
┌─────────────────────────────────────────────────────────────┐
│  Lab Linux 宿主机(Manjaro)                                  │
│  负责 Tailscale / SSH / libvirt / 磁盘文件 / 可选反代        │
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

### 3.1 后端 — `src/pickup_eds/`

```
src/pickup_eds/
├── instruments/
│   ├── electrometer.py      # 6514 SCPI 异步包装 + 状态缓存
│   └── daq.py               # USB-6002 nidaqmx 流采 + ring buffer
├── core/
│   ├── scope.py             # 触发逻辑、显示降采样、捕获快照
│   ├── recorder.py          # 录制状态机、文件轮转、元数据
│   └── storage.py           # Parquet/npy 落盘 + SQLite 元数据
├── api/
│   ├── main.py              # FastAPI app 入口、生命周期管理
│   ├── ws.py                # WebSocket: /ws/stream(波形) /ws/state(状态)
│   ├── control.py           # REST: POST /api/control/*  (设量程/功能/触发)
│   ├── recording.py         # REST: POST /api/recording/{start,stop}
│   └── data.py              # REST: GET /api/data/*  (列表/下载)
└── web/                     # 静态前端
    ├── index.html
    ├── scope.js             # uPlot + WebSocket 客户端
    ├── controls.js          # 仪器控制 UI(Alpine.js)
    └── style.css
```

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
│    ─ libvirtd.service       (KVM/libvirt)                              │
│    ─ 可选: ttyd.service     :7681  (宿主机终端)                        │
│                                                                        │
│  Windows 10 LTSC VM:                                                   │
│    ─ pickup-eds backend     :8000                                      │
│    ─ USB passthrough: USB-6002 + 6514 USB-Serial                       │
│                                                                        │
│  访问方式:                                                              │
│    ─ 直接访问 guest IP                                                 │
│    ─ 或后续由宿主机反代/转发                                           │
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
