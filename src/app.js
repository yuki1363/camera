import {
  buildConstraints,
  buildPhotoFilename,
  describeCameraError,
  describeDevice,
  formatFileSize,
  pickNextFacingMode,
} from "./lib/camera-utils.js";

const el = (id) => document.getElementById(id);

const ui = {
  viewport: el("viewport"),
  preview: el("preview"),
  placeholder: el("placeholder"),
  flash: el("flash"),
  status: el("status"),
  startBtn: el("startBtn"),
  shutterBtn: el("shutterBtn"),
  switchBtn: el("switchBtn"),
  stopBtn: el("stopBtn"),
  deviceSelect: el("deviceSelect"),
  resolutionSelect: el("resolutionSelect"),
  mirrorToggle: el("mirrorToggle"),
  gallery: el("gallery"),
  galleryEmpty: el("galleryEmpty"),
  photoCount: el("photoCount"),
  clearBtn: el("clearBtn"),
  canvas: el("canvas"),
};

const state = {
  stream: null,
  facingMode: "user",
  photos: [],
};

function setStatus(message, isError = false) {
  ui.status.textContent = message;
  ui.status.classList.toggle("is-error", isError);
}

function applyAspectRatio() {
  const { videoWidth: width, videoHeight: height } = ui.preview;
  // 映像の縦横比に枠を合わせ、不要な余白が出ないようにする。
  ui.viewport.style.aspectRatio = width && height ? `${width} / ${height}` : "";
}

function isStreaming() {
  return Boolean(state.stream);
}

function syncControls() {
  const live = isStreaming();
  ui.shutterBtn.disabled = !live;
  ui.switchBtn.disabled = !live;
  ui.stopBtn.disabled = !live;
  ui.deviceSelect.disabled = !live;
  ui.startBtn.textContent = live ? "カメラを再起動" : "カメラを開始";
  ui.viewport.classList.toggle("is-live", live);
  ui.clearBtn.disabled = state.photos.length === 0;
}

function selectedResolution() {
  const [width, height] = ui.resolutionSelect.value.split("x").map(Number);
  return { width, height };
}

function stopStream() {
  if (!state.stream) return;
  for (const track of state.stream.getTracks()) track.stop();
  state.stream = null;
  ui.preview.srcObject = null;
  ui.viewport.style.aspectRatio = "";
}

async function refreshDeviceList() {
  if (!navigator.mediaDevices?.enumerateDevices) return;

  const devices = await navigator.mediaDevices.enumerateDevices();
  const cameras = devices.filter((device) => device.kind === "videoinput");
  const current = ui.deviceSelect.value;

  ui.deviceSelect.innerHTML = "";
  const auto = document.createElement("option");
  auto.value = "";
  auto.textContent = "自動選択";
  ui.deviceSelect.append(auto);

  cameras.forEach((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = describeDevice(device, index);
    ui.deviceSelect.append(option);
  });

  // 再描画でユーザーの選択が失われないように戻す。
  if (cameras.some((device) => device.deviceId === current)) {
    ui.deviceSelect.value = current;
  }
  ui.switchBtn.disabled = !isStreaming();
}

async function startCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    setStatus(
      "このブラウザはカメラ API に対応していません。最新の Chrome / Safari / Firefox をお試しください。",
      true,
    );
    return;
  }

  if (!window.isSecureContext) {
    setStatus(
      "カメラを使うには https:// または localhost で開く必要があります。README の起動手順を参照してください。",
      true,
    );
    return;
  }

  setStatus("カメラを起動しています…");
  stopStream();

  const { width, height } = selectedResolution();
  const constraints = buildConstraints({
    deviceId: ui.deviceSelect.value,
    facingMode: state.facingMode,
    width,
    height,
  });

  try {
    state.stream = await navigator.mediaDevices.getUserMedia(constraints);
    ui.preview.srcObject = state.stream;
    await ui.preview.play();
    applyAspectRatio();

    // 許可後はデバイス名が取得できるようになるので一覧を更新する。
    await refreshDeviceList();

    const [track] = state.stream.getVideoTracks();
    const settings = track?.getSettings?.() ?? {};
    if (settings.deviceId) ui.deviceSelect.value = settings.deviceId;

    const actual =
      settings.width && settings.height
        ? `${settings.width} × ${settings.height}`
        : "不明";
    setStatus(`カメラを起動しました（解像度 ${actual}）。`);
  } catch (error) {
    stopStream();
    setStatus(describeCameraError(error), true);
  } finally {
    syncControls();
  }
}

function stopCamera() {
  stopStream();
  syncControls();
  setStatus("カメラを停止しました。");
}

async function switchCamera() {
  state.facingMode = pickNextFacingMode(state.facingMode);
  // facingMode で切り替えるため、特定デバイスの固定は解除する。
  ui.deviceSelect.value = "";
  await startCamera();
}

function playFlash() {
  ui.flash.classList.remove("is-active");
  void ui.flash.offsetWidth; // アニメーションを再生し直すためのリフロー
  ui.flash.classList.add("is-active");
}

function renderGallery() {
  ui.gallery.innerHTML = "";

  for (const photo of state.photos) {
    const item = document.createElement("li");
    item.className = "photo";

    const image = document.createElement("img");
    image.src = photo.url;
    image.alt = photo.filename;

    const meta = document.createElement("div");
    meta.className = "photo-meta";
    meta.innerHTML = `
      <span class="photo-name"></span>
      <span class="photo-detail"></span>
      <div class="photo-actions"></div>
    `;
    meta.querySelector(".photo-name").textContent = photo.filename;
    meta.querySelector(".photo-detail").textContent =
      `${photo.width} × ${photo.height} / ${formatFileSize(photo.size)}`;

    const download = document.createElement("a");
    download.href = photo.url;
    download.download = photo.filename;
    download.textContent = "ダウンロード";

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "削除";
    remove.addEventListener("click", () => removePhoto(photo.id));

    meta.querySelector(".photo-actions").append(download, remove);
    item.append(image, meta);
    ui.gallery.append(item);
  }

  ui.photoCount.textContent = `${state.photos.length} 枚`;
  ui.galleryEmpty.hidden = state.photos.length > 0;
  ui.clearBtn.disabled = state.photos.length === 0;
}

function removePhoto(id) {
  const index = state.photos.findIndex((photo) => photo.id === id);
  if (index === -1) return;

  URL.revokeObjectURL(state.photos[index].url);
  state.photos.splice(index, 1);
  renderGallery();
}

function clearPhotos() {
  for (const photo of state.photos) URL.revokeObjectURL(photo.url);
  state.photos = [];
  renderGallery();
  setStatus("撮影した写真をすべて削除しました。");
}

function capture() {
  if (!isStreaming()) return;

  const width = ui.preview.videoWidth;
  const height = ui.preview.videoHeight;
  if (!width || !height) {
    setStatus("映像の準備ができていません。少し待ってからもう一度撮影してください。", true);
    return;
  }

  ui.canvas.width = width;
  ui.canvas.height = height;
  const context = ui.canvas.getContext("2d");
  // 左右反転はプレビュー表示のみの設定なので、保存する画像には適用しない。
  context.drawImage(ui.preview, 0, 0, width, height);
  playFlash();

  ui.canvas.toBlob((blob) => {
    if (!blob) {
      setStatus("画像の生成に失敗しました。", true);
      return;
    }

    const filename = buildPhotoFilename(new Date(), "png");
    state.photos.unshift({
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      url: URL.createObjectURL(blob),
      filename,
      size: blob.size,
      width,
      height,
    });

    renderGallery();
    setStatus(`${filename} を撮影しました。`);
  }, "image/png");
}

function applyMirror() {
  ui.viewport.classList.toggle("is-mirrored", ui.mirrorToggle.checked);
}

ui.startBtn.addEventListener("click", startCamera);
ui.stopBtn.addEventListener("click", stopCamera);
ui.switchBtn.addEventListener("click", switchCamera);
ui.shutterBtn.addEventListener("click", capture);
ui.clearBtn.addEventListener("click", clearPhotos);
ui.mirrorToggle.addEventListener("change", applyMirror);
ui.preview.addEventListener("loadedmetadata", applyAspectRatio);
ui.deviceSelect.addEventListener("change", startCamera);
ui.resolutionSelect.addEventListener("change", () => {
  if (isStreaming()) startCamera();
});

document.addEventListener("keydown", (event) => {
  const tag = event.target instanceof HTMLElement ? event.target.tagName : "";
  if (tag === "SELECT" || tag === "INPUT" || tag === "TEXTAREA") return;

  if (event.code === "Space") {
    event.preventDefault();
    capture();
  }
});

navigator.mediaDevices?.addEventListener?.("devicechange", refreshDeviceList);

window.addEventListener("pagehide", () => {
  stopStream();
  for (const photo of state.photos) URL.revokeObjectURL(photo.url);
});

applyMirror();
renderGallery();
syncControls();
refreshDeviceList();
setStatus("「カメラを開始」を押すとブラウザが権限を確認します。");
