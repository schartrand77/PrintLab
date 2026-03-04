#!/usr/bin/env sh
set -eu

REPO_URL="${HA_BAMBULAB_REPO:-https://github.com/greghesp/ha-bambulab.git}"
REPO_REF="${HA_BAMBULAB_REF:-main}"
CONFIG_DIR="${HA_CONFIG_DIR:-/config}"
TARGET_DIR="${CONFIG_DIR}/custom_components/bambu_lab"
TMP_DIR="/tmp/ha-bambulab"

if [ ! -d "${CONFIG_DIR}" ]; then
  echo "[ha-bambulab] ERROR: Config directory '${CONFIG_DIR}' was not found."
  exit 1
fi

rm -rf "${TMP_DIR}"

echo "[ha-bambulab] Installing ${REPO_URL}@${REPO_REF}"

git clone --depth 1 --branch "${REPO_REF}" "${REPO_URL}" "${TMP_DIR}"

if [ ! -d "${TMP_DIR}/custom_components/bambu_lab" ]; then
  echo "[ha-bambulab] ERROR: custom_components/bambu_lab not found in repo."
  exit 1
fi

mkdir -p "${CONFIG_DIR}/custom_components"
rm -rf "${TARGET_DIR}"
cp -a "${TMP_DIR}/custom_components/bambu_lab" "${TARGET_DIR}"

rm -rf "${TMP_DIR}"

echo "[ha-bambulab] Integration installed to ${TARGET_DIR}"
