"""DAQ daemon — runs inside pickup-win10-ltsc, talks NI-DAQmx + 6514 SCPI.

The Linux WebUI never imports this package directly. It is only loaded
in the Windows VM where ``nidaqmx`` and ``pyserial`` are installed and
where the actual hardware is attached. See docs/phase2-design.md.
"""
__all__ = ["FRAME_HEADER_FMT"]

# struct format for the binary frame header on /ws/raw_stream:
#   uint32 LE seq, uint32 LE n (samples per channel),
#   float32 LE sample_rate_hz, uint32 LE channel_count
FRAME_HEADER_FMT = "<IIfI"
