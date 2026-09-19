/**
 * カメラアプリ共通ユーティリティ。
 * ブラウザ API に依存しない純粋関数だけを置き、Node からもテストできるようにする。
 */

const pad = (value, width = 2) => String(value).padStart(width, "0");

/** Date を `20260919-143005` 形式の文字列にする。 */
export function formatTimestamp(date) {
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  );
}

/** 保存用のファイル名を組み立てる。拡張子は先頭のドット有無どちらでも可。 */
export function buildPhotoFilename(date, extension = "png") {
  const ext = String(extension).replace(/^\./, "").toLowerCase() || "png";
  return `photo-${formatTimestamp(date)}.${ext}`;
}

/** 前面カメラと背面カメラを交互に切り替える。 */
export function pickNextFacingMode(current) {
  return current === "environment" ? "user" : "environment";
}

/** バイト数を人が読みやすい単位に整形する。 */
export function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  if (bytes < 1024) return `${bytes} B`;

  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

/**
 * getUserMedia に渡す制約を組み立てる。
 * deviceId が指定されていればそのカメラを優先し、無ければ facingMode で選ぶ。
 */
export function buildConstraints({
  deviceId = "",
  facingMode = "user",
  width = 1280,
  height = 720,
} = {}) {
  const video = {
    width: { ideal: width },
    height: { ideal: height },
  };

  if (deviceId) {
    video.deviceId = { exact: deviceId };
  } else {
    video.facingMode = { ideal: facingMode };
  }

  return { video, audio: false };
}

const ERROR_MESSAGES = {
  NotAllowedError:
    "カメラの使用が許可されませんでした。ブラウザのアドレスバーのカメラアイコンから許可してください。",
  NotFoundError:
    "利用できるカメラが見つかりませんでした。デバイスの接続を確認してください。",
  NotReadableError:
    "カメラを起動できませんでした。他のアプリがカメラを使用していないか確認してください。",
  OverconstrainedError:
    "指定した設定に対応するカメラがありません。別のカメラまたは解像度を選んでください。",
  SecurityError:
    "セキュリティ設定によりカメラを利用できません。https:// または localhost で開いてください。",
  AbortError: "カメラの起動が中断されました。もう一度お試しください。",
};

/** 例外を日本語の案内メッセージに変換する。 */
export function describeCameraError(error) {
  if (!error) return "不明なエラーが発生しました。";

  const known = ERROR_MESSAGES[error.name];
  if (known) return known;

  return error.message
    ? `カメラエラー: ${error.message}`
    : "不明なエラーが発生しました。";
}

/** デバイス一覧のラベルが空のときに代替名を作る（許可前はラベルが空になる）。 */
export function describeDevice(device, index) {
  if (device && device.label) return device.label;
  return `カメラ ${index + 1}`;
}
