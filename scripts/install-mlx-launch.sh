#!/usr/bin/env bash

set -euo pipefail

PYTHON_FORMULA="${PYTHON_FORMULA:-python@3.13}"
MLX_VERSION="${MLX_VERSION:-0.31.1}"
INSTALL_PREFIX="${INSTALL_PREFIX:-/opt/homebrew}"
VENV_DIR="${VENV_DIR:-$HOME/.mlx-jaccl-venv}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 2
  }
}

need_cmd brew

if ! brew list --versions "${PYTHON_FORMULA}" >/dev/null 2>&1; then
  echo "Installing ${PYTHON_FORMULA} with Homebrew..."
  brew install "${PYTHON_FORMULA}"
fi

python_bin="${INSTALL_PREFIX}/opt/${PYTHON_FORMULA}/bin/python3.13"
if [[ ! -x "${python_bin}" ]]; then
  echo "Expected python interpreter not found at ${python_bin}" >&2
  exit 1
fi

echo "Using python: ${python_bin}"
if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Creating virtualenv at ${VENV_DIR}..."
  "${python_bin}" -m venv "${VENV_DIR}"
fi

venv_python="${VENV_DIR}/bin/python"
venv_mlx_launch="${VENV_DIR}/bin/mlx.launch"

"${venv_python}" -m pip install --upgrade pip setuptools wheel
"${venv_python}" -m pip install --upgrade "mlx==${MLX_VERSION}" "mlx-metal==${MLX_VERSION}"

echo
echo "Verification:"
"${venv_python}" -m pip show mlx
echo "---"
"${venv_python}" -m pip show mlx-metal
echo "---"
"${venv_mlx_launch}" --print-python
echo "---"
"${venv_mlx_launch}" --help | sed -n '1,24p'
echo "---"
echo "Export this before running validation scripts on this Mac:"
echo "export MLX_LAUNCH_BIN=${venv_mlx_launch}"
