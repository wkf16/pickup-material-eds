# scripts/

实验/调试脚本,**不属于核心代码**(核心代码在 `src/pickup_eds/`,Phase 2 才填)。
这里都是单文件可跑、依赖最少的小工具。

## 现有

| 文件 | 在哪跑 | 用途 |
|---|---|---|
| `gen_chirp.py` | Mac(本机) | 生成扫频 wav 用作激励信号 |
| `capture_freqresp.py` | Lab Linux | 配置 6514 + USB-6002 同步采集 |
| `analyze_bode.py` | 任意 | 时域/频谱/1/3 倍频程能量 + 可选 Bode |

## 快速用法

### 在 Mac 上(生成激励)
```bash
cd ~/projects/pickup-material-eds
python scripts/gen_chirp.py
# 生成 chirp_50_20k_10s.wav
afplay chirp_50_20k_10s.wav   # 实验时播
```

### 在 Lab Linux 上(采集)
```bash
# 一次性装依赖(系统 Python 即可)
sudo pacman -S python-pyserial python-numpy python-scipy
pip install --user nidaqmx soundfile

# 跑采集
mkdir -p data/exp01
python scripts/capture_freqresp.py \
    --duration 12 \
    --range 2 \
    --out data/exp01/02_speaker_chirp.npy
# 看到 ">>> Start the stimulus NOW <<<" 时,在 Mac 上 afplay
```

### 分析(本机或 Lab 都行)
```bash
python scripts/analyze_bode.py data/exp01/02_speaker_chirp.npy --plot
# 加 --ref 同时给参考麦录音,得到 Bode 曲线
python scripts/analyze_bode.py data/exp01/02_speaker_chirp.npy \
    --ref data/exp01/reference_phone.wav --plot
```

## 关于 6514 SCPI 速记(见 `docs/exp-01-bandwidth-test.md` §5.2)

`capture_freqresp.py` 默认每次都重新发一次 6514 配置。如果你想自己手动 telnet/screen 串口
配好了,在脚本上加 `--skip-6514`。
