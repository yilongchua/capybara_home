#!/usr/bin/env bash

set -euo pipefail

TARGET_SERVICE="${TARGET_SERVICE:-EXO Thunderbolt 3}"
DISABLE_WIFI="${DISABLE_WIFI:-1}"
TB_IP="${TB_IP:-}"
TB_MASK="${TB_MASK:-255.255.255.0}"
TB_ROUTER="${TB_ROUTER:-}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 2
  }
}

need_cmd networksetup
need_cmd ifconfig
need_cmd system_profiler

echo "Current services:"
networksetup -listallnetworkservices
echo

if [[ "${DISABLE_WIFI}" == "1" ]]; then
  echo "Disabling Wi-Fi power for validation..."
  networksetup -setairportpower en0 off || true
fi

echo "Moving ${TARGET_SERVICE} to the front of network service order..."
networksetup -ordernetworkservices "${TARGET_SERVICE}" "Wi-Fi" "EXO Thunderbolt 1" "EXO Thunderbolt 2" || true

if [[ -n "${TB_IP}" ]]; then
  echo "Assigning manual IP ${TB_IP}/${TB_MASK} to ${TARGET_SERVICE}..."
  networksetup -setmanual "${TARGET_SERVICE}" "${TB_IP}" "${TB_MASK}" "${TB_ROUTER}" || true
fi

echo
echo "Post-change snapshot:"
networksetup -listnetworkserviceorder
echo "---"
ifconfig bridge100 2>/dev/null || true
echo "---"
system_profiler SPThunderboltDataType | sed -n '1,160p'

nat_config="$(defaults read /Library/Preferences/SystemConfiguration/com.apple.nat 2>/dev/null || true)"
if [[ "${nat_config}" == *"Enabled = 1;"* ]] && [[ "${nat_config}" == *"en3"* ]]; then
  echo
  echo "Internet Sharing is still configured on en3."
  echo "Turn off System Settings > General > Sharing > Internet Sharing before retrying JACCL."
fi

if ifconfig bridge100 >/dev/null 2>&1; then
  echo
  echo "bridge100 is still present."
  echo "Next manual step:"
  echo "  1. Turn off Internet Sharing if it is enabled on en3."
  echo "  2. Unplug the Thunderbolt cable."
  echo "  3. Remove the bridge with sudo:"
  echo "     sudo ifconfig bridge100 deletem en3"
  echo "     sudo ifconfig bridge100 destroy"
  echo "  4. Replug the cable into the dedicated EXO port."
  echo "  5. Re-run this script, then re-run scripts/check-jaccl-preflight.sh."
fi
