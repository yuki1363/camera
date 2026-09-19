import assert from "node:assert/strict";
import test from "node:test";

import {
  buildConstraints,
  buildPhotoFilename,
  describeCameraError,
  describeDevice,
  formatFileSize,
  formatTimestamp,
  pickNextFacingMode,
} from "../src/lib/camera-utils.js";

test("formatTimestamp は 0 埋めした日時文字列を返す", () => {
  assert.equal(formatTimestamp(new Date(2026, 8, 19, 14, 30, 5)), "20260919-143005");
  assert.equal(formatTimestamp(new Date(2026, 0, 1, 0, 0, 0)), "20260101-000000");
});

test("buildPhotoFilename は拡張子を正規化する", () => {
  const date = new Date(2026, 8, 19, 14, 30, 5);
  assert.equal(buildPhotoFilename(date), "photo-20260919-143005.png");
  assert.equal(buildPhotoFilename(date, ".JPG"), "photo-20260919-143005.jpg");
  assert.equal(buildPhotoFilename(date, ""), "photo-20260919-143005.png");
});

test("pickNextFacingMode は前面と背面を交互に返す", () => {
  assert.equal(pickNextFacingMode("user"), "environment");
  assert.equal(pickNextFacingMode("environment"), "user");
  assert.equal(pickNextFacingMode(undefined), "environment");
});

test("formatFileSize は単位を切り上げて整形する", () => {
  assert.equal(formatFileSize(0), "0 B");
  assert.equal(formatFileSize(512), "512 B");
  assert.equal(formatFileSize(1536), "1.5 KB");
  assert.equal(formatFileSize(1024 * 1024), "1.0 MB");
  assert.equal(formatFileSize(3.5 * 1024 * 1024 * 1024), "3.5 GB");
  assert.equal(formatFileSize(-1), "-");
  assert.equal(formatFileSize(Number.NaN), "-");
});

test("buildConstraints は deviceId を優先し、無ければ facingMode を使う", () => {
  const byFacing = buildConstraints({ facingMode: "environment", width: 640, height: 480 });
  assert.deepEqual(byFacing, {
    video: {
      width: { ideal: 640 },
      height: { ideal: 480 },
      facingMode: { ideal: "environment" },
    },
    audio: false,
  });

  const byDevice = buildConstraints({ deviceId: "cam-1", facingMode: "user" });
  assert.deepEqual(byDevice.video.deviceId, { exact: "cam-1" });
  assert.equal("facingMode" in byDevice.video, false);
});

test("buildConstraints は引数なしでも既定値を返す", () => {
  const constraints = buildConstraints();
  assert.deepEqual(constraints.video.width, { ideal: 1280 });
  assert.deepEqual(constraints.video.facingMode, { ideal: "user" });
  assert.equal(constraints.audio, false);
});

test("describeCameraError は既知のエラーを日本語に変換する", () => {
  const denied = describeCameraError(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
  assert.match(denied, /許可されませんでした/);

  const unknown = describeCameraError(Object.assign(new Error("boom"), { name: "WeirdError" }));
  assert.equal(unknown, "カメラエラー: boom");

  assert.equal(describeCameraError(null), "不明なエラーが発生しました。");
});

test("describeDevice はラベルが空のとき連番名を返す", () => {
  assert.equal(describeDevice({ label: "FaceTime HD" }, 0), "FaceTime HD");
  assert.equal(describeDevice({ label: "" }, 1), "カメラ 2");
  assert.equal(describeDevice(undefined, 2), "カメラ 3");
});
