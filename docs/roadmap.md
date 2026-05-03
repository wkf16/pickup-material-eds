# 路线图与项目状态

> **当前日期**:2026-05-03
> **当前 Phase**:Phase 2 ✅ 完成 → Phase 2.5 待启动（HW sync + chirp Bode）
> **下一动作**:见 §"Next actions" 末尾；详细设计见 [`phase2-design.md`](phase2-design.md)

## 设计哲学(2026-05-03 重排)

WebUI 本身就是这个项目最重要的实验工具。**先把工具做出来,再用工具做实验**,比"先用裸脚本跑实验、然后回头改进工具"更顺序自然。所以 Phase 重新切分如下:

| Phase | 核心交付 | 一句话 |
|---|---|---|
| **0** | 项目骨架 + 文档 | 写下来才能想清楚 |
| **1** | 驱动 + 链路验证 | 让两台仪器能从 Lab Linux 说话 |
| **2** | WebUI MVP | 把仪器包成网页前端 |
| **3** | 实验执行(用 WebUI) | 跑实验 01 + 录 ML 数据集 |
| **4** | ML 训练 + 推理集成 | 把模型嵌回 WebUI |

(原 Phase 1 把"实验 01"当作主项,2026-05-03 拆开:实验文档保留在 `docs/exp-01-bandwidth-test.md`,但执行移到 Phase 3——见 `docs/decisions.md` D-11。)

---

## Phase 概览

| Phase | 目标 | 状态 | 阻塞点 |
|---|---|---|---|
| **Phase 0** | 项目骨架 + 文档基础 | ✅ 完成 | — |
| **Phase 1** | Windows VM 中的 NI-DAQmx 驱动 + 端到端链路验证 | ✅ 完成（链路 + 4 个 smoke test 全过） | — |
| **Phase 2** | WebUI 接真硬件（Linux WebUI + VM DAQ daemon 桥架构） | ✅ 完成（6/6 验收通过 2026-05-03） | — |
| **Phase 2.5** | AO + AI 硬件同步触发 + 实验 01 chirp Bode 一键跑 | ⚪ 未启动 | Phase 2 |
| **Phase 3** | ML 数据集采集 | ⚪ 未启动 | Phase 2.5 |
| **Phase 4** | ML 训练 + 推理集成回 WebUI | ⚪ 未启动 | Phase 3 |

---

## Phase 0:项目骨架 ✅(已完成 2026-05-03)

- [x] 创建 `~/projects/pickup-material-eds/` 目录结构
- [x] `README.md` 项目概述
- [x] `.gitignore`
- [x] `docs/architecture.md` 系统架构
- [x] `docs/roadmap.md` 本文档
- [x] `docs/decisions.md` 关键决策记录
- [x] `docs/exp-01-bandwidth-test.md` 实验 01 完整方案
- [x] `scripts/{gen_chirp,capture_freqresp,analyze_bode}.py` 单文件工具
- [x] `git init` + 首次 commit(2026-05-03)

---

## Phase 1:驱动 + 端到端链路验证 ✅

**目标**:Lab Linux 作为 **KVM 宿主机**,Windows VM 作为 **DAQ/串口来宾机**。在 Windows VM 里装好 NI-DAQmx,让 Python 能读 USB-6002 数据,6514 能 SCPI 通信,**两路数据从硬件流到 Python 都验证一次**。这一阶段不写 WebUI,只确保"裸的仪器层 ready"。

### 1.1 网络
- [x] 装 Tailscale(用户已自行完成,见 [`memory/lab_machine.md`](../../.claude/projects/-Users-okonfu/memory/lab_machine.md))
- [x] `ssh a203@203-precision3660` 工作(off-campus 也能连)
- [x] **关闭休眠**(masked sleep/suspend/hibernate/hybrid-sleep targets + logind HandleLid/Power/SuspendKey=ignore + IdleAction=ignore；2026-05-03 in Phase 2 infra)

### 1.2 DAQ 侧:Windows VM + NI-DAQmx
- [x] 在 Lab Linux 上装 `qemu/libvirt/virt-install/OVMF/swtpm`
- [x] 宿主机 KVM 自检通过(`virt-host-validate qemu`)
- [x] libvirt 默认 NAT 网络启动并设为自启
- [x] 确认 USB 设备 ID:
  - `3923:76c4` = USB-6002
  - `067b:23a3` = 6514 USB-Serial
- [x] **本地下载** Windows 10 Enterprise LTSC 2021 x64 ISO（`~/Downloads/en-us_windows_10_enterprise_ltsc_2021_x64_dvd_d289cf96.iso`）
- [x] ISO 传到 Lab Linux（`/var/lib/libvirt/images/`，注：需放此目录，见 `windows-vm-plan.md §4`）
- [x] 创建 Windows VM(UEFI + TPM 2.0 + USB passthrough) → `pickup-win10-ltsc` running，SPICE `localhost:5900`
- [x] **autounattend.xml 完成 Windows 无人值守安装**（用 floppy 注入，见 `docs/windows-vm-plan.md §9`）
- [x] VM 内安装 NI-DAQmx 25.5（在线 installer，曾因网络中断导致 nipal 内核驱动半装；通过 `palSetup64.msi /REINSTALL=ALL REINSTALLMODE=vomus` 修复）
- [x] VM 内安装 Python 3.12 + `nidaqmx` / numpy / scipy / soundfile / matplotlib / pyserial
- [x] 跑最小 enumerate 测试 ✅ 看到 `Dev1: USB-6002 S/N 0x2685c37`
  ```python
  import nidaqmx
  print(list(nidaqmx.system.System.local().devices.device_names))  # ['Dev1']
  ```
- [x] 6514 RS-232 在 Windows VM 上跑 IDN ✅ `KEITHLEY ...,MODEL 6514,4691930,A13` 与 Mac 测试一致

### 1.3 DAQ 侧:性能边界实测（数据保存在 VM `C:\setup\phase1_smoke\`）
- [x] **Smoke test 0**：1kS/s 100 点单通道，130ms 完成，开路噪声 σ=2.13V
- [x] **Smoke test 1**：50 kS/s × 50000 点 single-shot，1066ms 完成，全部样本到位 ✅
- [x] **Smoke test 2**：60 秒 **连续** 流采 @ 50 kS/s，每 ~200ms 读一块，**3M 样本、0 overrun、丢失率 +0.017%** ✅
- [x] **Smoke test 3**：差分 vs 单端，开路输入下 DIFF std=0.30V vs RSE std=2.26V，**DIFF 抑制共模噪声 7.5×**
- [x] **Smoke test 4**：AO 5 kS/s 1kHz 正弦写入 + AI 同时读，软件层全通；ao0 物理上未连到 ai0 所以 AI 端没看到信号（属于预期，需要拿杜邦线或 BNC 跳线连一下才能验证回环）
- [x] 落盘到 `data/phase1_smoketests/`（已 scp 到本地，6 个 .npy + 一个 status.txt）

### 1.4 6514 侧:验证已通的链路依然通
- [x] RS-232 物理接线(已验证,IDN 拿到 S/N 4691930)
- [x] 用 `scripts/capture_freqresp.py` 配置 + 一次有限采集(在 Mac 端验证过命令)
- [x] 在 Windows VM 上重跑 IDN ✅（COM3 = Prolific PL2303GT，9600 8N1，IDN 返回与 Mac 一致）
- [ ] 在 Windows VM 上跑完整 capture_freqresp.py（带 6514 + nidaqmx 配合的扫频）
- [x] 对照表:V/I/R/Q 四个模式各发 SCPI 切换 + 验证 `FUNC?` 回读

### 1.5 端到端验证
- [ ] 接一个简单信号源(电池 + 分压器,~100 mV DC)到 6514 输入
- [ ] 6514 V 模式 2V 量程 → 2V AO → USB-6002 → Windows VM Python
- [ ] 看到稳定 100 mV ± 噪声,符合预期
- [ ] **如果到这一步通过了:Phase 1 完成**

---

## Phase 2:WebUI 接真硬件 🟡

**目标**:把 MVP（simulator-backed）改造成真硬件链路——`WebUI 在 Lab Linux :80` ↔ `DAQ daemon 在 Windows VM :8765`，两边用 WebSocket 二进制流过 virtio 桥。详细设计见 [`docs/phase2-design.md`](phase2-design.md)。

### 2.0 已完成（codex/webui-wt 分支已合并到 main）
- [x] FastAPI 后端骨架 + WebSocket `/ws/stream` `/ws/state`
- [x] REST `/api/control/*` `/api/recording/*` `/api/data/*` 接口契约
- [x] `SimulatedBenchService` 模拟数据源（Phase 2 期间作为 dev fallback 保留）
- [x] `electrometer_serial.py` 真 6514 SCPI 桥（**Phase 2 改成走 daq daemon 而不是直连 `/dev/ttyUSB0`**）
- [x] `core/storage.py` `.npz + SQLite` 落盘
- [x] 前端 `index.html`（Preview v3 单文件，Alpine + uPlot）
- [x] `deploy/pickup-eds-webui.service` + `scripts/deploy_webui.sh`（systemd，端口 80 sudo）
- [x] 文档：`api-reference.md` `webui-mvp-delivery.md` `performance.md` `dev-real-hardware.md`

### 2.1 VM 侧：DAQ Daemon（新模块 `src/pickup_eds/daq_daemon/`）
- [x] `discovery.py` ── USB-6002 (`Dev1` 自动发现) + 6514 (枚举 PnP + `*IDN?` 探测)
- [x] `daq_worker.py` ── nidaqmx Task（专用线程，`read_into` 预分配 buf），二进制 ws push
- [x] `scpi_proxy.py` ── pyserial 单例 + 命令队列
- [x] `recovery.py` ── 启动时探测 nidaqmx，无设备则 pnputil rescan
- [x] `app.py` ── FastAPI :8765 入口，REST `/api/daq/*` `/api/scpi/*` + WS `/ws/raw_stream`
- [x] Windows 服务部署（scheduled task at startup, SYSTEM 账号，`scripts/deploy_daq_daemon.sh`）

### 2.2 Linux 侧：桥客户端 + 替换 simulator
- [x] `instruments/bridge.py` ── BridgeClient：ws 客户端 + 状态机 + 指数退避重连
- [x] `instruments/bridge.py` ── RealBenchService（实现 BenchServiceProtocol）
- [x] `api/main.py` ── 加 `PICKUP_EDS_BRIDGE_URL` 环境变量，simulator 默认保留
- [x] `electrometer_serial.py` ── bridge 模式下 SCPI 走 daemon `/api/scpi/send`
- [x] 桥状态推送进 `AppState.bridge`：`{state, daemon_addr, rtt_ms, last_seq, last_error}`

### 2.3 前端 Tabs（surgical edit of `index.html`，保留 Canvas 2D 渲染）
- [x] **Tab 1 实时**：DAQ 配置（采样率/通道/端接/量程）+ Canvas 2D scope
- [x] **Run / Pause** 主按钮
- [x] **Single** 单帧抓拍按钮
- [x] **Stop ⊗** 完全停 DAQ task
- [x] **Tab 2 录制**：标签 + 时长 + 历史列表（同 MVP）
- [x] **Tab 3 6514 SCPI**：保留 MVP 现状，bridge 模式下数据通路走 daemon
- [x] **Tab 4 输出 AO**：通道 + 模式（DC/Sine/Sweep-lin/Sweep-log/Chirp）+ Free run（File replay disabled, HW sync 留 2.5）
- [x] 桥状态指示灯（header 右侧彩色圆点 + state + RTT + seq）

### 2.4 50 kHz 不崩
- [x] DAQ 读专用线程，event loop 只 touch frame queue（daq_worker.py）
- [x] ring buffer 复用 `core/ring_buffer.py`，浏览器侧降采样到 720 点
- [x] WS 二进制帧（`struct.pack` `<IIfI` + `float32` 数组）
- [x] 后端降采样到 720 点 / 帧后再下发浏览器
- [x] 录制写盘**只在 Linux 侧**（StorageManager 在 RealBenchService 内部）

### 2.5 验收（2026-05-03 通过）
- [x] 浏览器 `http://lab4070-c/` 见实时波形（CSV/NPZ 录制都验过）
- [x] 桥状态推送进 `AppState.bridge`（disconnected/reconnecting/running/error）
- [x] 50 kHz 单通道连续 60 秒，0 overrun（`scripts/verify_phase2.py` PASS）
- [x] Run / Pause / Stop / Single 行为符合设计
- [x] 真 6514 SCPI `*IDN?` 返回 `MODEL 6514, S/N 4691930` over bridge
- [x] 录 5s `baseline` → 落盘 + SQLite 元数据（NPZ + CSV 都验过）
- [x] COM/Dev 自动发现（`discovery.py` 启动时探测）
- [x] 验收报告：`data/phase2_acceptance/20260503T111745Z.json`

---

## Phase 2.5:AO + AI 硬件同步触发 + 实验 01 chirp Bode 一键跑 ⚪

**目标**：在 Phase 2 已通的前提下加同步触发，跑 `docs/exp-01-bandwidth-test.md` 描述的 chirp Bode 实验。

- [ ] AO+AI 共享 start_trigger（USB-6002 `/Dev1/ai/StartTrigger` 配 `start_trigger.cfg_dig_edge_start_trig`）
- [ ] 前端"输出 AO" Tab 加"与 AI 同步触发"选项
- [ ] 实验预设 Tab（chirp 1Hz–2kHz × 30s @ 5kS/s + AI ai0/ai1 diff 模式）
- [ ] Bode 计算（实时画 H(f) + |H(f)| + ∠H(f)）
- [ ] 实验数据 schema 扩展：录 AO 参考波 + AI 采集 + 程序参数

---

## Phase 3:ML 数据集采集 ⚪

**目标**:把 `docs/exp-01-bandwidth-test.md` 里描述的实验,**通过 Phase 2 的 WebUI 完成**——并以此为契机录一份正式的 ML 数据集。

### 3.1 实验 01:材料带宽测试(详见 `docs/exp-01-bandwidth-test.md`)
> 实验 01 的软件能力（HW sync + chirp Bode + Bode 计算）由 **Phase 2.5** 提供。Phase 3.1 是用这套能力做物理实验、出结果。
- [ ] 凑物料:喇叭、双面胶、铜箔、夹具、BNC 线
- [ ] Step 0:噪声基线(用 WebUI 录,标签 `baseline_short`)
- [ ] Step 1:1 kHz 单音 go/no-go
- [ ] Step 2:扫频 Bode(机械直驱,贴喇叭)
- [ ] Step 3:扫频 Bode(空气耦合,悬空)
- [ ] Step 4:语音段录制(可选)
- [ ] 在 jupyter 里出 Bode 图 + 写 `docs/exp-01-results.md`

### 3.2 ML 数据集录制(基于实验 01 结论决定方案)
- [ ] 任务定义:几类、什么类、单类样本数(待 Q-02/Q-03 确认)
- [ ] WebUI 加 "批量录制" 模式:循环 N 次,每次提示用户,自动落盘
- [ ] 录第一批训练集
- [ ] 录测试集

### 3.3 打磨 / 部署
- [ ] 触发模式(单次/连续/边沿)
- [ ] 实时频谱面板
- [ ] 历史数据回放界面
- [ ] ttyd 终端嵌入
- [ ] systemd 服务 + reboot 自启
- [ ] HTTP Basic Auth(若开放给师兄/导师)

---

## Phase 4:ML 训练 + 推理集成 ⚪

- [ ] jupyter 里训练 ResNet-SE(用 Phase 3 数据集)
- [ ] 模型导出 ONNX 或 TorchScript
- [ ] 后端 `/api/inference/predict` 端点,加载模型 + 实时分类
- [ ] 前端显示当前预测类别 + 置信度
- [ ] 简单 demo(对着传感器说话 → 屏幕显示识别结果)

---

# 横切问题清单(跨 Phase 的开放问题)

| 编号 | 问题 | 状态 |
|---|---|---|
| Q-01 | 这个材料是空气麦还是接触式振动?(影响后续设计) | 等 Phase 3 实验 01 |
| Q-02 | ML 任务是 silent speech 短语分类还是别的? | 待用户与导师确认 |
| Q-03 | 录数据时类别集合多大?(5 类 vs 18 类) | 同上 |
| Q-04 | 6514 模拟输出实际带宽? | 等 Phase 3 Bode 实验 |
| Q-05 | 是否要加自制简化前级(INA128 板)做 A/B 验证? | Phase 4 之后,可选副线 |

---

# Next actions（按优先级，2026-05-03 更新）

**Phase 1 已全部完成** ✅（Windows VM、NI-DAQmx 25.5、6514 RS-232、4 个 smoke tests、数据归档）

下一步进入 **Phase 2: WebUI 接真硬件**，详细设计见 [`phase2-design.md`](phase2-design.md)：

1. **VM 侧 daq daemon 起步** —— `daq_daemon/discovery.py` + `daq_worker.py` 先做出来，本地 PowerShell + python 测试通过再往上盖 FastAPI
2. **Linux 侧 BridgeClient** —— 同步实现，先用 mock daemon 跑前端
3. **前端 Tab 重组** —— 1/2/3/4 四个 Tab，Run/Pause/Stop/Single 按钮，桥状态指示灯
4. **VM 服务部署** —— Windows scheduled task / NSSM，开机自起 8765
5. **VM 重启自动恢复** —— 把 `windows-vm-plan.md §10` 的 `nidevldu` / `nipalk` / phantom 处理写进 `daq_daemon/recovery.py`
6. **端到端 50 kHz × 60s 不崩** —— Phase 2 验收硬指标
7. （Phase 2 通过后）**Phase 2.5: AO+AI HW sync + 实验 01 chirp Bode 一键跑**

---

# 决策日志参见 `decisions.md`,实验细节参见各 `exp-*.md`
