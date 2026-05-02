const state = {
  appState: null,
  datasets: [],
  liveFrame: { time_s: [], value: [] },
  autoPreviewedId: null,
};

const el = {
  modeBadge: document.getElementById("modeBadge"),
  streamBadge: document.getElementById("streamBadge"),
  stateBadge: document.getElementById("stateBadge"),
  updatedAt: document.getElementById("updatedAt"),
  sampleRateStat: document.getElementById("sampleRateStat"),
  rmsStat: document.getElementById("rmsStat"),
  peakStat: document.getElementById("peakStat"),
  windowStat: document.getElementById("windowStat"),
  waveLabel: document.getElementById("waveLabel"),
  recordingStateText: document.getElementById("recordingStateText"),
  recordingSamples: document.getElementById("recordingSamples"),
  lastDatasetId: document.getElementById("lastDatasetId"),
  datasetCount: document.getElementById("datasetCount"),
  datasetList: document.getElementById("datasetList"),
  previewLabel: document.getElementById("previewLabel"),
  toast: document.getElementById("toast"),
  startRecordingBtn: document.getElementById("startRecordingBtn"),
  stopRecordingBtn: document.getElementById("stopRecordingBtn"),
  recordingLabel: document.getElementById("recordingLabel"),
  recordingDuration: document.getElementById("recordingDuration"),
  zeroCheckToggle: document.getElementById("zeroCheckToggle"),
  zeroCorrectToggle: document.getElementById("zeroCorrectToggle"),
  waveCanvas: document.getElementById("waveCanvas"),
  spectrumCanvas: document.getElementById("spectrumCanvas"),
  previewCanvas: document.getElementById("previewCanvas"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.text();
    throw new Error(payload || response.statusText);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function showToast(message, tone = "normal") {
  el.toast.textContent = message;
  el.toast.dataset.tone = tone;
  el.toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    el.toast.classList.remove("visible");
  }, 2400);
}

function formatNumber(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

function setActiveButtons(containerId, activeValue, key) {
  const buttons = document.querySelectorAll(`#${containerId} button`);
  buttons.forEach((button) => {
    button.classList.toggle("active", button.dataset[key] === String(activeValue));
  });
}

function renderState(appState) {
  state.appState = appState;
  el.modeBadge.textContent = "SIM";
  el.updatedAt.textContent = new Date(appState.updated_at).toLocaleString();
  el.sampleRateStat.textContent = `${appState.daq.sample_rate_hz} Hz`;
  el.rmsStat.textContent = formatNumber(appState.daq.live_rms);
  el.peakStat.textContent = formatNumber(appState.daq.live_peak);
  el.windowStat.textContent = `${formatNumber(appState.daq.display_window_s, 1)} s`;
  el.recordingStateText.textContent = appState.recording.active
    ? `recording: ${appState.recording.label}`
    : "idle";
  el.recordingSamples.textContent = String(appState.recording.sample_count);
  el.lastDatasetId.textContent = appState.recording.last_dataset_id || "-";
  el.zeroCheckToggle.checked = appState.control.zero_check;
  el.zeroCorrectToggle.checked = appState.control.zero_correct;
  setActiveButtons("functionButtons", appState.control.function, "func");
  setActiveButtons("rangeButtons", appState.control.range, "range");
  renderDatasets(appState.datasets || []);
  if (
    appState.recording.last_dataset_id &&
    appState.recording.last_dataset_id !== state.autoPreviewedId
  ) {
    state.autoPreviewedId = appState.recording.last_dataset_id;
    previewDataset(appState.recording.last_dataset_id);
  }
}

function renderDatasets(items) {
  state.datasets = items;
  el.datasetCount.textContent = `${items.length} items`;
  if (!items.length) {
    el.datasetList.innerHTML = `<p class="empty">还没有录制数据。</p>`;
    return;
  }
  el.datasetList.innerHTML = items
    .map(
      (item) => `
        <article class="dataset-row">
          <div>
            <strong>${item.label}</strong>
            <span>${new Date(item.created_at).toLocaleString()}</span>
          </div>
          <div>
            <span>${item.sample_count} samples</span>
            <span>${formatNumber(item.duration_s, 2)} s</span>
          </div>
          <div class="dataset-actions">
            <button data-preview="${item.id}">预览</button>
            <a href="/api/data/${item.id}/download">下载</a>
          </div>
        </article>
      `
    )
    .join("");
  document.querySelectorAll("[data-preview]").forEach((button) => {
    button.addEventListener("click", () => previewDataset(button.dataset.preview));
  });
}

function drawSeries(canvas, xs, ys, { accent = "#7effb2", fill = true } = {}) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#09131a";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 6; i += 1) {
    const y = (height / 6) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  if (!xs.length || !ys.length) {
    return;
  }

  const minX = xs[0];
  const maxX = xs[xs.length - 1];
  let minY = Math.min(...ys);
  let maxY = Math.max(...ys);
  if (Math.abs(maxY - minY) < 1e-9) {
    minY -= 1;
    maxY += 1;
  }

  const xScale = (value) => ((value - minX) / (maxX - minX || 1)) * width;
  const yScale = (value) => height - ((value - minY) / (maxY - minY || 1)) * height;

  if (fill) {
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "rgba(126,255,178,0.26)");
    gradient.addColorStop(1, "rgba(126,255,178,0)");
    ctx.beginPath();
    ctx.moveTo(xScale(xs[0]), height);
    ys.forEach((value, index) => {
      ctx.lineTo(xScale(xs[index]), yScale(value));
    });
    ctx.lineTo(xScale(xs[xs.length - 1]), height);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
  }

  ctx.beginPath();
  ys.forEach((value, index) => {
    const x = xScale(xs[index]);
    const y = yScale(value);
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.strokeStyle = accent;
  ctx.lineWidth = 2;
  ctx.stroke();
}

function computeSpectrum(values) {
  const windowSize = Math.min(256, values.length);
  if (windowSize < 32) {
    return { freqs: [], mags: [] };
  }
  const slice = values.slice(values.length - windowSize);
  const freqs = [];
  const mags = [];
  for (let k = 1; k < 64; k += 1) {
    let real = 0;
    let imag = 0;
    for (let n = 0; n < windowSize; n += 1) {
      const angle = (2 * Math.PI * k * n) / windowSize;
      real += slice[n] * Math.cos(angle);
      imag -= slice[n] * Math.sin(angle);
    }
    freqs.push(k);
    mags.push(Math.sqrt(real * real + imag * imag) / windowSize);
  }
  return { freqs, mags };
}

function renderLiveFrame(frame) {
  state.liveFrame = frame;
  el.waveLabel.textContent = `${frame.value.length} points`;
  drawSeries(el.waveCanvas, frame.time_s, frame.value, { accent: "#7effb2", fill: true });
  const spectrum = computeSpectrum(frame.value);
  drawSeries(el.spectrumCanvas, spectrum.freqs, spectrum.mags, {
    accent: "#ffb24d",
    fill: false,
  });
}

async function previewDataset(datasetId) {
  try {
    const payload = await api(`/api/data/${datasetId}/preview`);
    el.previewLabel.textContent = `${payload.label} / ${datasetId}`;
    drawSeries(el.previewCanvas, payload.time_s, payload.value, {
      accent: "#59b8ff",
      fill: false,
    });
  } catch (error) {
    showToast(`预览失败: ${error.message}`, "error");
  }
}

async function submitJSON(path, body) {
  return api(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

function bindControls() {
  document.querySelectorAll("#functionButtons button").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await submitJSON("/api/control/function", { func: button.dataset.func });
        showToast(`Function -> ${button.dataset.func}`);
      } catch (error) {
        showToast(`切换失败: ${error.message}`, "error");
      }
    });
  });

  document.querySelectorAll("#rangeButtons button").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await submitJSON("/api/control/range", { range: Number(button.dataset.range) });
        showToast(`Range -> ${button.dataset.range}`);
      } catch (error) {
        showToast(`切换失败: ${error.message}`, "error");
      }
    });
  });

  el.zeroCheckToggle.addEventListener("change", async () => {
    try {
      await submitJSON("/api/control/zero-check", { on: el.zeroCheckToggle.checked });
      showToast(`Zero Check -> ${el.zeroCheckToggle.checked ? "on" : "off"}`);
    } catch (error) {
      showToast(`切换失败: ${error.message}`, "error");
    }
  });

  el.zeroCorrectToggle.addEventListener("change", async () => {
    try {
      await submitJSON("/api/control/zero-correct", { on: el.zeroCorrectToggle.checked });
      showToast(`Zero Correct -> ${el.zeroCorrectToggle.checked ? "on" : "off"}`);
    } catch (error) {
      showToast(`切换失败: ${error.message}`, "error");
    }
  });

  el.startRecordingBtn.addEventListener("click", async () => {
    try {
      await submitJSON("/api/recording/start", {
        label: el.recordingLabel.value.trim() || "baseline",
        duration_s: Number(el.recordingDuration.value),
      });
      showToast("录制已开始", "ok");
    } catch (error) {
      showToast(`开始失败: ${error.message}`, "error");
    }
  });

  el.stopRecordingBtn.addEventListener("click", async () => {
    try {
      const payload = await submitJSON("/api/recording/stop", {});
      if (payload.dataset) {
        showToast(`录制已保存: ${payload.dataset.label}`, "ok");
        await previewDataset(payload.dataset.id);
      } else {
        showToast("当前没有活动录制", "error");
      }
    } catch (error) {
      showToast(`停止失败: ${error.message}`, "error");
    }
  });
}

async function connectStream() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${window.location.host}/ws/stream`);
  ws.addEventListener("open", () => {
    el.streamBadge.textContent = "已连接";
  });
  ws.addEventListener("message", (event) => {
    renderLiveFrame(JSON.parse(event.data));
  });
  ws.addEventListener("close", () => {
    el.streamBadge.textContent = "重连中";
    window.setTimeout(connectStream, 1200);
  });
}

async function connectState() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${window.location.host}/ws/state`);
  ws.addEventListener("open", () => {
    el.stateBadge.textContent = "已连接";
  });
  ws.addEventListener("message", (event) => {
    renderState(JSON.parse(event.data));
  });
  ws.addEventListener("close", () => {
    el.stateBadge.textContent = "重连中";
    window.setTimeout(connectState, 1200);
  });
}

async function bootstrap() {
  bindControls();
  try {
    const appState = await api("/api/state");
    renderState(appState);
    const datasets = await api("/api/data/list");
    renderDatasets(datasets.items || []);
    connectStream();
    connectState();
  } catch (error) {
    showToast(`启动失败: ${error.message}`, "error");
  }
}

bootstrap();
