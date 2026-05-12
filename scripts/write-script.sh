#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TB_SERVICE="${TB_SERVICE:-EXO Thunderbolt 2}"
MLX_LAUNCH_BIN="${MLX_LAUNCH_BIN:-$HOME/mlx-env/bin/mlx.launch}"
OUTFILE="${OUTFILE:-$HOME/Desktop/other-mac-ssh-and-diag.txt}"
LOCAL_MAC_PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAcUBu07BY8Dfhkfah9oMp0qgAo/yPA3ByR+HjcgNl2V ryan_chua@MacBook-Pro.local'

mkdir -p "$(dirname "${OUTFILE}")"
exec > >(tee "${OUTFILE}") 2>&1

echo "=== date ==="
date
echo

echo "=== ssh authorized_keys setup ==="
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
if ! grep -Fqx "${LOCAL_MAC_PUBKEY}" "$HOME/.ssh/authorized_keys"; then
  printf '%s\n' "${LOCAL_MAC_PUBKEY}" >> "$HOME/.ssh/authorized_keys"
  echo "Added local Mac public key to authorized_keys."
else
  echo "Local Mac public key already present."
fi
echo

echo "=== mlx launcher check ==="
if [[ -x "${MLX_LAUNCH_BIN}" ]]; then
  echo "MLX_LAUNCH_BIN=${MLX_LAUNCH_BIN}"
  "${MLX_LAUNCH_BIN}" --print-python
else
  echo "MLX launcher not found at ${MLX_LAUNCH_BIN}"
  echo "Override with:"
  echo "  MLX_LAUNCH_BIN=/absolute/path/to/mlx.launch bash ${SCRIPT_DIR}/write-script.sh"
fi
echo

echo "=== quick network snapshot ==="
networksetup -getinfo "${TB_SERVICE}" || true
echo
ifconfig bridge100 2>/dev/null || echo "bridge100 absent"
echo
ibv_devices || true
echo

echo "=== exo state snapshot ==="
if curl -fsS http://localhost:52415/state >/dev/null 2>&1; then
  curl -fsS http://localhost:52415/state | jq '.nodeNetwork, .topology, .nodeIdentities'
else
  echo "EXO API unreachable at http://localhost:52415"
fi
echo

echo "=== capture-jaccl-diag ==="
if [[ -x "${SCRIPT_DIR}/capture-jaccl-diag.sh" ]]; then
  TB_SERVICE="${TB_SERVICE}" "${SCRIPT_DIR}/capture-jaccl-diag.sh" "$HOME/Desktop/other-mac-post-ssh-diag.txt"
else
  echo "Missing ${SCRIPT_DIR}/capture-jaccl-diag.sh"
fi
echo

echo "=== done ==="
echo "Main log: ${OUTFILE}"
echo "Diag log: $HOME/Desktop/other-mac-post-ssh-diag.txt"
