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
  return ` · ${(bytesPerSecond / 1048576).toFixed(1)} MB/s`;
}

function setBusy(busy) {
  $("fetch").disabled = busy;
  $("download").disabled = busy;
}

function setProgress(percent, text) {
  $("bar").value = percent;
  $("status").textContent = text;
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
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
  show($("card"), true);
}

function triggerDownload(jobId) {
  const link = document.createElement("a");
  link.href = `/api/jobs/${jobId}/file`;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

async function pollJob(jobId) {
  for (;;) {
    const job = await api(`/api/jobs/${jobId}`);
    if (job.status === "error") {
      throw new Error(job.error_message || "Falló la descarga.");
    }
    if (job.status === "done") {
      setProgress(100, `Listo: ${job.filename}`);
      triggerDownload(jobId);
      return;
    }
    if (job.status === "processing") {
      setProgress(100, "Procesando…");
    } else if (job.status === "downloading") {
      setProgress(job.percent, `Descargando ${Math.floor(job.percent)}%${formatSpeed(job.speed)}`);
    } else {
      setProgress(0, "En cola…");
    }
    await sleep(1000);
  }
}

$("url-form").addEventListener("submit", async (event) => {
  event.preventDefault();
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
  radio.addEventListener("change", () => {
    const audio = selectedMode() === "audio";
    show($("video-opt"), !audio);
    show($("audio-opt"), audio);
  });
}

$("download").addEventListener("click", async () => {
  showError("");
  setBusy(true);
  show($("progress"), true);
  setProgress(0, "En cola…");
  try {
    const { job_id: jobId } = await postJson("/api/jobs", {
      url: $("url").value.trim(),
      mode: selectedMode(),
      height: $("height").value || "best",
      audio_format: $("audio-format").value,
    });
    await pollJob(jobId);
  } catch (error) {
    showError(error.message);
    show($("progress"), false);
  } finally {
    setBusy(false);
  }
});
