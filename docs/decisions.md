# 关键技术决策日志(ADR-style)

> 这份文档记录项目里"为什么这么选"。每一条决策都标记**做出时间、上下文、备选、最终选择、理由**。
> 项目演进过程中如果某条决策被推翻,**新增一条 D-XX 标记 supersedes 老决策**,不删除原条目——保留思考痕迹。

---

## D-01:用 Tailscale 而不是固定校园 IP

**时间**:2026-05-02
**状态**:已采纳,待实施

**背景**:Lab Linux 在 10.24.32.98,校园网 IP。从 Mac 直连有几个问题:
- DHCP 续约后 IP 可能变
- 跨子网路由不稳(实测从 10.25.x 到 10.24.x 经常超时)
- 出校园后无法直连

**备选**:
- A. 申请固定 IP + 校外 SSH 跳板
- B. **Tailscale + `tailscale ssh`** ← 选择
- C. 自建 WireGuard

**理由**:
- Tailscale 一次配置,永久解决 IP 漂移和跨网络
- `--ssh` 标志用 Tailscale 自身的身份替代公钥管理
- Mac 端已装,Lab 端 Manjaro AUR/官方源都有

**代价**:依赖第三方服务(Tailscale 控制平面),但研究项目可以接受。

---

## D-02:Web 框架选 FastAPI 不选 Flask/Django

**时间**:2026-05-02
**状态**:已采纳

**背景**:需要在 Web 上做实时数据流(WebSocket)+ 简单 REST 控制。

**备选**:
- A. **FastAPI + uvicorn** ← 选择
- B. Flask + Flask-SocketIO
- C. Django + Channels
- D. Sanic
- E. 直接用 `aiohttp`

**理由**:
- async-first,WebSocket 是一等公民(`@app.websocket(...)` 一行)
- Pydantic 类型校验 → REST 端点参数自动验证 + OpenAPI 文档自动生成
- 单文件可起步,扩展不复杂
- 项目体量(~1500 行)不需要 Django 那种"开箱即用"

---

## D-03:实时绘图选 uPlot 不选 Plotly/Chart.js

**时间**:2026-05-02
**状态**:已采纳

**背景**:浏览器要画实时滚动波形,1-2 kS/s 流式更新,可能会画到 50k+ 历史点。

**备选**:
- A. Plotly.js ── 功能最全,但 5k 点以上明显卡
- B. Chart.js ── 通用,流式不强
- C. **uPlot** ← 选择
- D. ECharts
- E. D3.js 自己撸

**理由**:
- uPlot 专为时间序列流式设计,benchmark 比 Plotly 快 10-100×
- 50k+ 点 60fps 无压力
- 体积小(< 50 KB gzip)
- 不依赖 React/Vue,纯函数式 API

**代价**:UI 美观度逊 Plotly,但研究工具不在乎。

---

## D-04:NI-DAQmx 部署方式选 distrobox 容器不选直接装/双系统

**时间**:2026-05-02
**状态**:已撤回,被 D-12 取代

**背景**:NI 官方不支持 Manjaro/Arch,只支持 Ubuntu LTS / RHEL / SUSE。

**备选**:
- A. AUR `ni-visa` + 手动从 .deb 提取 daqmx ── 脆弱,内核更新会坏
- B. **distrobox + Ubuntu 24.04 容器**(podman 后端)← 选择
- C. 双启动 Ubuntu ── 重,影响主系统使用
- D. Docker + USB passthrough ── 比 distrobox 折腾

**理由**:
- distrobox 是为这种"我喜欢 Manjaro,但需要某个 Ubuntu 包"场景设计的
- USB 设备自动 passthrough,几乎无配置
- 容器内安装的 NI-DAQmx 是官方 Ubuntu 包,稳定
- 主机 Manjaro 不被污染,卸载等于 `distrobox rm`

**代价**:每次开新 shell 要 `distrobox enter`,可写脚本固化。

**撤回原因(2026-05-03)**:
- 实测 `NI Linux Device Drivers 2026Q2` 在 Ubuntu 24.04 仓库里虽然有 `ni-daqmx`,但它会继续拉一整套 **DKMS + Ubuntu 6.8 generic headers**
- 当前宿主机是 `Manjaro 6.18.18-1-MANJARO`,容器内 DKMS 不能替代宿主机真实内核驱动
- 对 `USB-6002` 这类 USB MIO 设备,Windows 路线明显更稳

---

## D-05:为采集机关闭休眠/suspend

**时间**:2026-05-02
**状态**:已采纳,待实施

**背景**:USB-6002 AI FIFO 只 2047 样本(41 ms @ 50 kS/s)。系统进入 suspend → USB 中断 → FIFO overrun 数据丢失。

**决策**:`systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`,以及 logind 关掉电源键/盖子触发,GNOME GSettings 关空闲挂起。

**理由**:Lab 工作站本来就该 24/7 在线,休眠收益小,代价大。

---

## D-06:数据格式选 Parquet 不选 CSV/HDF5/.npy

**时间**:2026-05-02
**状态**:已采纳

**备选**:
- A. CSV ── 通用,但巨大(50 kS/s × 4 字节/数 = 200 KB/s,文本表示再 5×)
- B. .npy ── Python 原生快,但不带元数据,跨语言差
- C. HDF5 ── 强大,但库重(libhdf5 50 MB+),依赖头痛
- D. **Parquet (pyarrow)** ← 选择
- E. .wav ── 兼容音频工具,但只能 int 量化,丢精度

**理由**:
- 列式压缩,典型 5-10× 体积小于 CSV
- pandas / dask / polars / 直接 PyTorch DataLoader 都能秒读
- 自带 schema(列类型、单位、标签)
- 跨语言(R / Java / Rust 都有库)
- 文件结构良好,不易损坏

**代价**:不像 .npy 那样"打开就是 array",需要 pyarrow 这一层。

---

## D-07:仪器单例 + asyncio.Lock,不开多 worker

**时间**:2026-05-02
**状态**:已采纳

**背景**:6514 串口和 USB-6002 句柄都是物理唯一资源。FastAPI 默认起 uvicorn 单进程足够;若用 gunicorn 多 worker,会导致两个 worker 同时打开 /dev/ttyUSB0 → 一个抢到一个失败。

**决策**:
- 用 `uvicorn` 单进程
- 模块层全局单例 `_DAQ` 和 `_KEITHLEY`,初始化在 lifespan event
- 所有访问通过 `asyncio.Lock` 串行化
- 不开 `--workers N`

**代价**:吞吐受限于单进程。但本应用 < 100 req/s,完全够。

---

## D-08:鉴权选 HTTP Basic + Tailscale,不上 OAuth/JWT

**时间**:2026-05-02
**状态**:已采纳

**背景**:研究内部工具,不开放给外人,不需要复杂权限模型。

**决策**:
- 第一阶段:Tailscale 加入 = 已认证。不加 HTTP 鉴权
- 第二阶段(若开放给师兄/导师):加 HTTP Basic Auth(单用户名/密码),环境变量传入

**理由**:
- 加一层 Basic Auth < 10 行代码
- 上 OAuth/JWT 至少 200 行 + 一个用户管理界面,不值得

**未来**:如果项目变成实验室公用工具,再升级到 keycloak / authentik。

---

## D-09:前端用 vanilla + Alpine.js,不上 React/Vue

**时间**:2026-05-02
**状态**:已采纳

**备选**:
- A. **vanilla HTML + Alpine.js** ← 选择
- B. React + Vite + 状态管理库
- C. Vue 3
- D. Svelte
- E. HTMX

**理由**:
- 项目前端代码量预估 < 1000 行
- 复杂状态主要在后端(数据流、仪器状态),前端只是显示
- Alpine.js < 15 KB,声明式响应,语法接近 Vue 但不需要 build step
- React/Vue 引入 build pipeline、依赖管理、节点工程,投入产出比差

**代价**:大型 SPA 不适合 Alpine.js。但本项目永远不会变 SPA。

---

## D-11:Phase 重排 — WebUI 先于实验执行

**时间**:2026-05-03
**状态**:已采纳,supersedes 原 Phase 1 划分

**背景**:原 Phase 1 把"实验 01:测带宽"作为主交付,试图用裸 `scripts/*.py` 跑实验,然后 Phase 2 才做 WebUI。重新审视后发现这个顺序不对:

- WebUI **本身就是这个项目最重要的实验工具**,而不是装饰
- 用裸脚本跑一次实验,数据保存格式、控制流、回放方式都临时凑——之后写 WebUI 时还要重新组织
- 用 WebUI 跑实验,所有动作天然落到代码 + UI 上,不会"跑完就忘"

**决策**:
- Phase 1 = **驱动 + 链路验证**(只到 "Python 能从 Lab Linux 读 USB-6002 + 控 6514")
- Phase 2 = **WebUI MVP**
- Phase 3 = **用 WebUI 跑实验 01 + 录 ML 数据集**
- Phase 4 = **ML 训练 + 推理回填到 WebUI**

`docs/exp-01-bandwidth-test.md` 文档保留(作为执行手册),只是执行时机移到 Phase 3。

**理由**:
- 工具优先,实验后置——避免"先用脚本临时跑、再用 WebUI 重跑"的双倍工作
- 数据格式从一开始就是 Parquet + 元数据 SQLite,无需迁移
- 实验过程中产生的对工具的反馈,直接喂回 Phase 2 WebUI 的迭代

**代价**:推迟了"看到第一个 Bode 图"的时间(从 Phase 1 推迟到 Phase 3)。但因为 WebUI 写起来快(~1500 行),整体节奏不会差很多。

**何时推翻**:如果 WebUI 写到一半发现核心库(nidaqmx、pyserial)出了大坑,需要先用裸脚本验证某些假设,可以临时跳到 Phase 3 跑一次 smoke 实验,然后回到 Phase 2。这种 "tactical detour" 不算推翻这条决策。

---

## D-10:ML 训练不放 Web,留 Jupyter / CLI

**时间**:2026-05-02
**状态**:已采纳(范围决定)

**理由**:
- ML 训练是离线长任务,启动后跑数小时
- 把它塞进 web 后端会污染状态、占资源、复杂化
- 训练好的模型可以 export ONNX → 后端加载做实时推理(Phase 4)
- 用 jupyter / `python train.py` 命令行做训练,职责分明

---

## D-12:DAQ 驱动改走 Windows VM,不再走 Ubuntu 容器

**时间**:2026-05-03
**状态**:已采纳,supersedes D-04

**背景**:对 `USB-6002` 的第一轮远程落地里,已经确认:

- `6514` 串口链路正常,`*IDN?` 和 `FUNC?` 都能通
- `NI Linux Device Drivers 2026Q2` 官方仓库在 Ubuntu 24.04 容器内可装
- 但 `ni-daqmx` 实际会拉一大批 **与 Ubuntu generic kernel 绑定的 DKMS 模块**
- 宿主机是真正负责 USB 枚举和内核驱动的 `Manjaro 6.18`,不是容器里的 `Ubuntu 6.8`

这意味着“容器里 apt 装上了”不等于“宿主机上的 USB-6002 真能稳定工作”。

**备选**:
- A. 继续硬顶 `Ubuntu 24.04 container + NI Linux drivers`
- B. 宿主机改装原生 Ubuntu
- C. **Manjaro 做 KVM 宿主机 + Windows VM 跑 NI-DAQmx** ← 选择

**理由**:
- Windows 是 `USB-6002 + NI-DAQmx` 的主支持平台
- 虚拟机把 `Windows/NI` 的复杂度和 `Linux/开发环境` 隔离开
- 保留当前 Manjaro 桌面、Tailscale、SSH、文件环境,不必重装宿主机
- `USB-6002` 和 `6514 USB-Serial` 都可以通过 libvirt 直通给 guest

**选择的 guest OS**:
- **Windows 10 Enterprise LTSC 2021 x64**

这是一个**工程判断**:
- “支持”来自 NI 的 Windows 兼容矩阵
- “更轻”来自 Microsoft 对 LTSC 的专用设备定位

若后续发现某个 `NI-DAQmx` 版本对 LTSC 有额外限制,退回 `Windows 10 22H2 x64`。

---

# 推翻日志(decisions reversed)

- `D-04` ── 被 `D-12` 取代

---

# 引用本文档

代码注释里如需引用某条决策,直接写 `# See docs/decisions.md D-04`。
