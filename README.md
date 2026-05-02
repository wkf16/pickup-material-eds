# pickup-material-eds

Web-based 控制 + 数据采集系统,用于表征 SLTS 类 TENG/压电"拾音"材料。
最终部署在实验室 Linux 工作站上,通过内网访问。

## 硬件

| 件 | 型号 | 备注 |
|---|---|---|
| 静电计 | Keithley 6514 | RS-232,9600/8N1/CR/XonXoff,S/N 4691930 |
| DAQ | NI USB-6002 | 16-bit, 50 kS/s, ±10V |
| 实验主机 | Dell Precision 3660 / Manjaro Linux | i7-13700K, 125 GiB RAM, RTX 4070, IP 10.24.32.98 |

数据流:

```
拾音材料 → Keithley 6514 (高阻前置放大 + 量程缩放)
              ├─ RS-232  → SCPI:量程/功能/慢速读数
              └─ 2V BNC  → USB-6002:50 kS/s 时域波形
```

## 项目状态

- **Phase 0** ── 项目骨架 ✅
- **Phase 1**(进行中) ── NI-DAQmx 驱动 + 端到端链路验证
- **Phase 2** ── WebUI MVP(实时显示 + 6514 控制 + 录制)
- **Phase 3** ── 用 WebUI 跑实验 01 + 录 ML 数据集
- **Phase 4** ── ML 训练 + 推理集成回 WebUI

详细见 [`docs/roadmap.md`](docs/roadmap.md)。

## 文档导航

按"想看什么 → 看哪份"组织:

| 想了解 | 看 |
|---|---|
| **现在该做什么、整体进度** | [`docs/roadmap.md`](docs/roadmap.md) |
| **目标系统怎么设计的、模块怎么分** | [`docs/architecture.md`](docs/architecture.md) |
| **为什么选 X 不选 Y(技术选型理由)** | [`docs/decisions.md`](docs/decisions.md) |
| **下一个实验怎么做(测 TENG 材料带宽)** | [`docs/exp-01-bandwidth-test.md`](docs/exp-01-bandwidth-test.md) |
| **这次 WebUI 交付了什么、怎么部署** | [`docs/webui-mvp-delivery.md`](docs/webui-mvp-delivery.md) |
| **当前 WebUI 的 REST / WS 契约** | [`docs/api-reference.md`](docs/api-reference.md) |
| **现有脚本怎么用** | [`scripts/README.md`](scripts/README.md) |

未来加入(标记位置):
- `docs/exp-01-results.md` ── 实验 01 结果与决策
- `docs/exp-02-*.md` ── 后续实验

## 快速开始

```bash
# 本地开发
cd ~/projects/pickup-material-eds
python scripts/gen_chirp.py

# Lab Linux(SSH)
ssh a203@10.24.32.98     # 当前直连;后续会切到 Tailscale
# 或: ssh a203@203-precision3660    (Tailscale 启用后)
cd <项目同步目录>
python scripts/capture_freqresp.py --help

# WebUI 本地预览
cd /Users/okonfu/Projects/pickup-material-eds-webui-wt
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m uvicorn pickup_eds.api.main:app --host 0.0.0.0 --port 8000
```

## 参考

- Zhang et al., *Chem. Eng. J.* 524 (2025) 169299 ── SLTS 论文,本项目的起点
- Keithley 6514 Instruction Manual (Document 6514-901-01 Rev. D)
- NI USB-6002 Specifications (374371A-01)
