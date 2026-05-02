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
**状态**:已采纳,待实施

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

## D-10:ML 训练不放 Web,留 Jupyter / CLI

**时间**:2026-05-02
**状态**:已采纳(范围决定)

**理由**:
- ML 训练是离线长任务,启动后跑数小时
- 把它塞进 web 后端会污染状态、占资源、复杂化
- 训练好的模型可以 export ONNX → 后端加载做实时推理(Phase 4)
- 用 jupyter / `python train.py` 命令行做训练,职责分明

---

# 推翻日志(decisions reversed)

(暂无)

---

# 引用本文档

代码注释里如需引用某条决策,直接写 `# See docs/decisions.md D-04`。
