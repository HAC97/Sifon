"use strict";

const $ = (id) => document.getElementById(id);

function show(el, visible) {
  el.hidden = !visible;
}

function showError(message) {
  const el = $("error");
  el.textContent = message || "";
  show(el, Boolean(message));
}

async function api(path, options) {
  let res;
  try {
    res = await fetch(path, options);
  } catch {
    throw new Error("No se pudo conectar con el servidor local.");
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    // non-JSON body, handled below
  }
  if (!res.ok) {
    throw new Error((body && body.error_message) || "La solicitud no es válida.");
  }
  return body;
}

function postJson(path, data) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function formatDuration(seconds) {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond) return "";
  return `${(bytesPerSecond / 1048576).toFixed(1)} MB/s`;
}

function setBusy(busy) {
  $("fetch").disabled = busy;
  $("paste").disabled = busy;
  $("download").disabled = busy;
  document.body.classList.toggle("busy", busy);
}

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let shownPercent = 0;
let tween = 0;

// The big percentage counts up to the target instead of jumping once per poll.
function setPercent(target, instant) {
  cancelAnimationFrame(tween);
  const to = Math.max(0, Math.min(100, target));
  const from = shownPercent;
  if (instant || reduceMotion.matches || to === from) {
    shownPercent = to;
    $("pct").textContent = String(Math.floor(to));
    return;
  }
  const start = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - start) / 700);
    shownPercent = from + (to - from) * k;
    $("pct").textContent = String(Math.floor(shownPercent));
    if (k < 1) tween = requestAnimationFrame(step);
  };
  tween = requestAnimationFrame(step);
}

// `status` is a live region: only rewrite it when the phase changes, so a screen reader
// is not interrupted once per second. Speed goes to `detail`, which is not announced.
function setProgress(percent, text, detail = "", instant = false) {
  $("bar").value = percent;
  setPercent(percent, instant);
  if ($("status").textContent !== text) $("status").textContent = text;
  $("detail").textContent = detail;
}

let lastJobId = null;
let locked = false;
// Bumped by every reset. A download that started in an earlier session stops quietly:
// it neither updates the screen nor saves the file.
let session = 0;

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function syncModeOptions() {
  const audio = selectedMode() === "audio";
  show($("video-opt"), !audio);
  show($("audio-opt"), audio);
}

// Once the video is found the link is fixed and the x is the only way to start over.
function setLocked(on) {
  locked = on;
  $("url").readOnly = on;
  $("url-form").classList.toggle("locked", on);
  show($("paste"), !on);
  show($("fetch"), !on);
  show($("clear"), on);
}

function resetToSearch() {
  session += 1;
  setBusy(false);
  setLocked(false);
  $("url").value = "";
  showError("");
  show($("card"), false);
  show($("progress"), false);
  show($("again"), false);
  setProgress(0, "", "", true);
  lastJobId = null;
  document.querySelector('input[name="mode"][value="video"]').checked = true;
  $("audio-format").value = "mp3";
  syncModeOptions();
  $("url").focus();
}

function renderInfo(info) {
  $("title").textContent = info.title;
  $("byline").textContent = [info.uploader, formatDuration(info.duration)].filter(Boolean).join(" · ");

  const thumb = $("thumb");
  if (info.thumbnail) {
    thumb.src = info.thumbnail;
    show(thumb, true);
  } else {
    thumb.removeAttribute("src");
    show(thumb, false);
  }

  const select = $("height");
  select.replaceChildren();
  const best = document.createElement("option");
  best.value = "best";
  best.textContent = "Mejor calidad";
  select.append(best);
  for (const height of info.heights) {
    const option = document.createElement("option");
    option.value = String(height);
    option.textContent = `${height}p`;
    select.append(option);
  }

  show($("progress"), false);
  show($("again"), false);
  show($("card"), true);
  setLocked(true);
}

function triggerDownload(jobId) {
  const link = document.createElement("a");
  link.href = `/api/jobs/${jobId}/file`;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

async function pollJob(jobId, mine) {
  for (;;) {
    if (session !== mine) return;
    const job = await api(`/api/jobs/${jobId}`);
    if (session !== mine) return;
    if (job.status === "error") {
      throw new Error(job.error_message || "Falló la descarga.");
    }
    if (job.status === "done") {
      setProgress(100, `Listo: ${job.filename}`);
      lastJobId = jobId;
      show($("again"), true);
      triggerDownload(jobId);
      return;
    }
    if (job.status === "processing") {
      setProgress(100, "Procesando…");
    } else if (job.status === "downloading") {
      setProgress(job.percent, "Descargando", formatSpeed(job.speed));
    } else {
      setProgress(0, "En cola…");
    }
    await sleep(1000);
  }
}

$("url-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (locked) return; // Enter in the fixed link must not search again
  showError("");
  show($("card"), false);
  setBusy(true);
  $("fetch").textContent = "Buscando…";
  try {
    renderInfo(await postJson("/api/info", { url: $("url").value.trim() }));
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
    $("fetch").textContent = "Buscar";
  }
});

for (const radio of document.querySelectorAll('input[name="mode"]')) {
  radio.addEventListener("change", syncModeOptions);
}

$("clear").addEventListener("click", resetToSearch);

$("paste").addEventListener("click", async () => {
  showError("");
  let text = "";
  try {
    text = (await navigator.clipboard.readText()).trim();
  } catch {
    showError("No pude leer el portapapeles. Pegá el enlace con Ctrl+V.");
    return;
  }
  if (!text) {
    showError("El portapapeles está vacío. Copiá un enlace y probá de nuevo.");
    return;
  }
  $("url").value = text;
  $("url-form").requestSubmit();
});

// Ctrl+V straight into the field: search right away when it looks like a link.
$("url").addEventListener("paste", () => {
  setTimeout(() => {
    if (/^https?:\/\//i.test($("url").value.trim())) $("url-form").requestSubmit();
  }, 0);
});

$("again").addEventListener("click", () => {
  if (lastJobId) triggerDownload(lastJobId);
});

$("download").addEventListener("click", async () => {
  const mine = session;
  showError("");
  setBusy(true);
  show($("again"), false);
  show($("progress"), true);
  setProgress(0, "En cola…", "", true);
  try {
    const { job_id: jobId } = await postJson("/api/jobs", {
      url: $("url").value.trim(),
      mode: selectedMode(),
      height: $("height").value || "best",
      audio_format: $("audio-format").value,
    });
    await pollJob(jobId, mine);
  } catch (error) {
    if (session !== mine) return;
    showError(error.message);
    show($("progress"), false);
  } finally {
    // After a reset the busy state already belongs to the new session; leave it alone.
    if (session === mine) setBusy(false);
  }
});
