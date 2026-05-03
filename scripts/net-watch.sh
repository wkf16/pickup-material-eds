#!/usr/bin/env bash
# Connectivity watchdog — passive logging, no interference.
#
# Polls every 30 s:
#   - LAN gateway reachable? (rules out box-internal stalls)
#   - External HTTP reachable? (rules out auth/uplink)
#   - DNS working?
# Writes a TSV line ONLY on state transitions, plus an hourly heartbeat.
# On any DOWN transition snapshots: nmcli state, default route, recent
# NetworkManager warnings, dhcp lease age. Replay the file later to see
# whether drops cluster around fixed times (auth session expiry) or are
# random (uplink/cable).
#
# Install (one time, on lab box):
#   mkdir -p ~/.config/systemd/user ~/log
#   cp scripts/net-watch.sh ~/.local/bin/net-watch
#   chmod +x ~/.local/bin/net-watch
#   cp scripts/net-watch.service ~/.config/systemd/user/
#   systemctl --user daemon-reload
#   systemctl --user enable --now net-watch
#   loginctl enable-linger a203   # so it keeps running after logout
#
# Inspect:
#   tail -f ~/log/net-watch.tsv
#   awk -F'\t' '$2=="DOWN"{print $1,$3}' ~/log/net-watch.tsv | tail -20
set -uo pipefail

LOG="${HOME}/log/net-watch.tsv"
mkdir -p "$(dirname "$LOG")"

# Header (only if file is empty)
[[ -s "$LOG" ]] || printf 'ts\tstate\twhat\n' >> "$LOG"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Quick reachability probes; each returns 0 (ok) or 1 (fail).
check_gw()   { ip route get 1.1.1.1 2>/dev/null | awk '{print $3; exit}' \
               | xargs -r -I{} ping -W2 -c1 {} >/dev/null 2>&1; }
check_http() { curl -sS --max-time 4 -o /dev/null -w '%{http_code}' \
               https://www.gstatic.com/generate_204 2>/dev/null \
               | grep -q '^204$'; }
check_dns()  { getent hosts www.cloudflare.com >/dev/null 2>&1; }

# Snapshot on transition — kept tight so the log doesn't explode.
diag() {
  printf '  nmcli=%s\n' "$(nmcli -t -f STATE general status 2>/dev/null)"
  printf '  default-route=%s\n' "$(ip route show default | head -1)"
  printf '  resolv=%s\n' "$(awk '/^nameserver/{print $2}' /etc/resolv.conf | xargs)"
  printf '  recent-NM-warn=\n'
  journalctl -u NetworkManager --since "3 min ago" -p warning --no-pager 2>/dev/null \
    | tail -8 | sed 's/^/    /'
  printf '  link-stats=%s\n' "$(ip -s -j link show \
      "$(ip route show default | awk '/default/ {print $5; exit}')" 2>/dev/null \
      | grep -oE '"errors":[0-9]+|"dropped":[0-9]+' | xargs)"
}

prev_state=""
hb_at=0

while :; do
  gw=0 http=0 dns=0
  check_gw   && gw=1
  check_http && http=1
  check_dns  && dns=1

  if   (( http==1 )); then state="UP"
  elif (( dns==0 && gw==1 )); then state="DNS_DOWN"
  elif (( dns==1 && gw==1 )); then state="UPLINK_DOWN"
  elif (( gw==0 )); then state="LAN_DOWN"
  else state="DOWN"
  fi

  now=$(date +%s)

  if [[ "$state" != "$prev_state" ]]; then
    printf '%s\t%s\tgw=%d http=%d dns=%d\n' "$(ts)" "$state" "$gw" "$http" "$dns" >> "$LOG"
    if [[ "$state" != "UP" ]]; then
      { diag ; } >> "$LOG" 2>&1
    fi
    prev_state="$state"
    hb_at=$now
  elif (( now - hb_at >= 3600 )); then
    printf '%s\tHEARTBEAT\t%s\n' "$(ts)" "$state" >> "$LOG"
    hb_at=$now
  fi

  sleep 30
done
