#!/usr/bin/env bash
# ラズパイのWi-FiをアクセスポイントモードにするOSレベルの一度きりのセットアップ。
# Raspberry Pi OS Bookworm以降（NetworkManagerがデフォルト）を前提とする。
#
# 注意:
#   - Wi-FiをAP化すると、同じ無線インターフェースで同時にインターネット接続（子機モード）は
#     できなくなる。ラズパイ本体のインターネット接続が別途必要な場合は、有線LANまたは
#     USB Wi-Fiドングルの追加を検討すること。
#   - セキュリティのため、必ずWPA2パスフレーズを設定する（オープンAPにはしない）。
#
# 使い方:
#   sudo ./scripts/setup_wifi_ap.sh <SSID> <パスフレーズ(8文字以上)> [接続名]

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "root権限で実行してください（sudo ./scripts/setup_wifi_ap.sh ...）" >&2
  exit 1
fi

SSID="${1:-}"
PASSPHRASE="${2:-}"
CON_NAME="${3:-capper-monitor-ap}"
IFACE="${WIFI_IFACE:-wlan0}"

if [ -z "$SSID" ] || [ -z "$PASSPHRASE" ]; then
  echo "使い方: sudo $0 <SSID> <パスフレーズ(8文字以上)> [接続名]" >&2
  exit 1
fi

if [ "${#PASSPHRASE}" -lt 8 ]; then
  echo "WPA2パスフレーズは8文字以上にしてください" >&2
  exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli が見つかりません。NetworkManagerがインストールされているか確認してください。" >&2
  exit 1
fi

echo "Wi-Fiインターフェース: ${IFACE}"
echo "接続名: ${CON_NAME}"
echo "SSID: ${SSID}"

if nmcli connection show "${CON_NAME}" >/dev/null 2>&1; then
  echo "既存の接続 '${CON_NAME}' を削除します"
  nmcli connection delete "${CON_NAME}"
fi

nmcli connection add \
  type wifi \
  ifname "${IFACE}" \
  con-name "${CON_NAME}" \
  autoconnect yes \
  ssid "${SSID}"

nmcli connection modify "${CON_NAME}" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  ipv4.method shared \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "${PASSPHRASE}"

nmcli connection up "${CON_NAME}"

echo ""
echo "Wi-Fiアクセスポイントを起動しました。"
echo "スマホ側で SSID '${SSID}' に接続し、ブラウザで"
echo "  http://<ラズパイのAP側IPアドレス>:<web.port>/"
echo "を開いてください（web.port は config/config.yaml の web.port、既定値は8080）。"
echo ""
echo "AP側のIPアドレスを確認する: nmcli -f IP4.ADDRESS connection show '${CON_NAME}'"
echo "元の子機モードに戻す:       nmcli connection down '${CON_NAME}'"
