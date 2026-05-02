#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  create_windows_vm.sh --iso /path/to/windows.iso [options]

Options:
  --name NAME         VM name (default: pickup-win10-ltsc)
  --iso PATH          Windows ISO path on the host
  --disk PATH         Disk image path (default: /var/lib/libvirt/images/<name>.qcow2)
  --disk-size GB      Disk size in GiB (default: 80)
  --memory MB         Memory in MiB (default: 8192)
  --vcpus N           vCPU count (default: 4)
  --dry-run           Print libvirt XML instead of creating the VM

Notes:
  - Requires libvirt, virt-install, qemu-img, OVMF, swtpm
  - Passes through:
      3923:76c4  NI USB-6002
      067b:23a3  Keithley 6514 USB-Serial bridge
EOF
}

NAME="pickup-win10-ltsc"
ISO=""
DISK=""
DISK_SIZE_GB="80"
MEMORY_MB="8192"
VCPUS="4"
DRY_RUN="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      NAME="$2"
      shift 2
      ;;
    --iso)
      ISO="$2"
      shift 2
      ;;
    --disk)
      DISK="$2"
      shift 2
      ;;
    --disk-size)
      DISK_SIZE_GB="$2"
      shift 2
      ;;
    --memory)
      MEMORY_MB="$2"
      shift 2
      ;;
    --vcpus)
      VCPUS="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ISO" ]]; then
  echo "--iso is required" >&2
  usage >&2
  exit 2
fi

if [[ ! -f "$ISO" ]]; then
  echo "ISO not found: $ISO" >&2
  exit 1
fi

if [[ -z "$DISK" ]]; then
  DISK="/var/lib/libvirt/images/${NAME}.qcow2"
fi

if [[ ! -f "$DISK" ]]; then
  mkdir -p "$(dirname "$DISK")"
  qemu-img create -f qcow2 "$DISK" "${DISK_SIZE_GB}G" >/dev/null
fi

ARGS=(
  --connect qemu:///system
  --name "$NAME"
  --memory "$MEMORY_MB"
  --vcpus "$VCPUS"
  --cpu host-passthrough
  --os-variant win10
  --disk "path=${DISK},format=qcow2,bus=virtio"
  --cdrom "$ISO"
  --network network=default,model=e1000e
  --host-device 3923:76c4
  --host-device 067b:23a3
  --boot uefi
  --tpm backend.type=emulator,backend.version=2.0,model=tpm-crb
  --graphics spice
)

if [[ "$DRY_RUN" == "1" ]]; then
  exec virt-install "${ARGS[@]}" --noautoconsole --print-xml
fi

exec virt-install "${ARGS[@]}"
