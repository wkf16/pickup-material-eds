#!/usr/bin/env python3
"""WinRM helper for pushing scripts/files to the pickup-win10-ltsc VM.

Designed to run on lab4070 (which has the winrm-venv). Provides three
operations:

  - ``ps <script-file>``  Run a PowerShell script file (passed via base64 to
    avoid quote escaping). Reads the script from stdin if path is ``-``.
  - ``put <local> <remote>``  Copy a small file (< 1 MB) from lab4070 to the
    VM via base64 chunks.
  - ``run-cmd <cmd>``  Run a single cmd.exe one-liner (for `py -c` etc).

VM endpoint is fixed to ``http://192.168.122.8:5985/wsman`` with
``Admin / Lab2026!`` NTLM auth. Override via ``VM_HOST`` / ``VM_USER`` /
``VM_PASS`` env vars if those drift.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

import winrm  # type: ignore[import-not-found]


def _session() -> winrm.Session:
    host = os.environ.get("VM_HOST", "192.168.122.8")
    user = os.environ.get("VM_USER", "Admin")
    pw = os.environ.get("VM_PASS", "Lab2026!")
    # Long timeouts for slow ops like pip install (which can take 5+ min
    # if downloading numpy from PyPI). pywinrm defaults are too short.
    op_timeout = int(os.environ.get("VM_OP_TIMEOUT", "600"))
    read_timeout = op_timeout + 30
    return winrm.Session(
        f"http://{host}:5985/wsman",
        auth=(user, pw),
        transport="ntlm",
        operation_timeout_sec=op_timeout,
        read_timeout_sec=read_timeout,
    )


def _print_result(r: winrm.Response, *, strip_clixml: bool = True) -> int:
    sys.stdout.write(r.std_out.decode(errors="replace"))
    err = r.std_err.decode(errors="replace")
    if strip_clixml:
        # PowerShell emits CLIXML progress noise on stderr even on success.
        # Drop it unless it carries actual error content.
        import re
        err = re.sub(r"#< CLIXML\s*<Objs[^>]*>.*?</Objs>", "", err, flags=re.S)
    if err.strip():
        sys.stderr.write(err)
    return r.status_code


def cmd_ps(args: argparse.Namespace) -> int:
    if args.script == "-":
        script = sys.stdin.read()
    else:
        script = Path(args.script).read_text()
    s = _session()
    # Wrap the script with -EncodedCommand to bypass any quoting issues.
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    r = s.run_cmd(f"powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}")
    return _print_result(r)


def cmd_put(args: argparse.Namespace) -> int:
    src = Path(args.local)
    data = src.read_bytes()
    if len(data) > 5 * 1024 * 1024:
        sys.exit(f"file too big for chunked base64 push ({len(data)} bytes)")
    b64 = base64.b64encode(data).decode("ascii")
    # Push in ~1500-char chunks. After UTF-16-LE -> base64 wrapping by
    # pywinrm's -EncodedCommand path, each PS command roughly doubles in
    # size, so 1500 stays comfortably under the 8191-char cmd line limit.
    chunk_size = 1500
    chunks = [b64[i : i + chunk_size] for i in range(0, len(b64), chunk_size)]
    s = _session()
    remote = args.remote.replace("/", "\\")
    parent = remote.rsplit("\\", 1)[0]
    # Ensure parent dir exists; truncate target.
    setup = (
        f"$ErrorActionPreference='Stop';"
        f"New-Item -ItemType Directory -Path '{parent}' -Force | Out-Null;"
        f"[IO.File]::WriteAllBytes('{remote}', [byte[]]@())"
    )
    r = s.run_ps(setup)
    if r.status_code != 0:
        sys.stderr.write(r.std_err.decode(errors="replace"))
        return r.status_code
    for i, chunk in enumerate(chunks):
        ps = (
            f"$b=[Convert]::FromBase64String('{chunk}');"
            f"$s=[IO.File]::Open('{remote}',[IO.FileMode]::Append);"
            f"$s.Write($b,0,$b.Length); $s.Close()"
        )
        r = s.run_ps(ps)
        if r.status_code != 0:
            sys.stderr.write(f"chunk {i}/{len(chunks)} failed:\n")
            sys.stderr.write(r.std_err.decode(errors="replace"))
            return r.status_code
    print(f"pushed {len(data)} bytes -> {remote} ({len(chunks)} chunks)", file=sys.stderr)
    return 0


def cmd_run_cmd(args: argparse.Namespace) -> int:
    s = _session()
    r = s.run_cmd(args.cmdline)
    return _print_result(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_ps = sub.add_parser("ps", help="Run PowerShell from file (or stdin via -)")
    p_ps.add_argument("script")
    p_ps.set_defaults(func=cmd_ps)
    p_put = sub.add_parser("put", help="Copy small file to VM (base64 chunks)")
    p_put.add_argument("local")
    p_put.add_argument("remote")
    p_put.set_defaults(func=cmd_put)
    p_run = sub.add_parser("run-cmd", help="Run cmd.exe one-liner")
    p_run.add_argument("cmdline")
    p_run.set_defaults(func=cmd_run_cmd)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
