#!/usr/bin/env bash
# Detach + re-attach the USB-6002 and 6514 USB-Serial passthrough on
# pickup-win10-ltsc. Workaround for qemu-xhci + Windows USB stack losing
# state across host or VM reboots (see docs/windows-vm-plan.md §10).
#
# Idempotent: detach errors are non-fatal; only attach failures fail the
# script.

set -u

readonly VM='pickup-win10-ltsc'
readonly XML_DIR='/etc/libvirt/qemu/usb-passthrough'
readonly LOG_TAG='pickup-eds-vm-recovery'

log() { logger -t "$LOG_TAG" "$*"; echo "[refresh-vm-usb] $*" >&2; }

reattach() {
    local xml="$1"
    local name="$2"
    log "detaching $name from $VM (best-effort)"
    virsh --connect qemu:///system detach-device "$VM" "$xml" --live 2>&1 \
        | sed "s/^/[detach $name] /" | logger -t "$LOG_TAG"
    sleep 2
    log "attaching $name to $VM"
    if ! virsh --connect qemu:///system attach-device "$VM" "$xml" --live 2>&1 \
            | sed "s/^/[attach $name] /" | tee >(logger -t "$LOG_TAG"); then
        log "attach $name FAILED"
        return 1
    fi
    return 0
}

# Wait until the VM is actually running before touching it. systemd
# orders us After=libvirtd, but libvirt may take a moment to start the
# autostart domains; we retry up to 60 s.
for i in $(seq 1 30); do
    state=$(virsh --connect qemu:///system domstate "$VM" 2>/dev/null || echo missing)
    if [ "$state" = "running" ]; then
        break
    fi
    log "waiting for $VM (state=$state, attempt $i/30)"
    sleep 2
done
if [ "$state" != "running" ]; then
    log "VM never reached running state; aborting"
    exit 1
fi

rc=0
reattach "$XML_DIR/usb_pl.xml" '6514-pl2303' || rc=$?
reattach "$XML_DIR/usb_ni.xml" 'usb-6002'    || rc=$?

if [ $rc -eq 0 ]; then
    log 'USB passthrough refresh OK'
else
    log "USB passthrough refresh completed with errors (rc=$rc)"
fi
exit $rc
