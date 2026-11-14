(() => {
  const $ = (id) => document.getElementById(id);
  const { modes: MODES, platforms: PLATFORMS } = JSON.parse($("config-data").textContent);
  const UNSUPPORTED = "Enlace no admitido. Vale de: " + Object.keys(PLATFORMS).join(", ") + ".";
  const STATUS = {
    queued: "Preparando…",
    downloading: "Descargando…",
    clipping: "Recortando…",
    processing: "Convirtiendo…",
  };
  const BARS = 48;
  const RECENT_KEY = "saca.recent";
  const ACTIVE_KEY = "saca.active";

  const form = $("form"), input = $("url"), btn = $("btn"), hint = $("hint");
  const preview = $("preview"), wave = $("wave"), cancelBtn = $("cancel");
  const startIn = $("start"), endIn = $("end");

  const state = {
    mode: form.elements.mode.value,
    picked: {},        // calidad elegida por modalidad
    info: null,        // datos del vídeo analizado
    infoUrl: "",
    busy: false,
    jobId: null,
  };
  let infoAbort = null, debounce = null;

  // ---------- utilidades ----------
  const platformOf = (u) => {
    try {
      const { protocol, hostname } = new URL(u);
      if (!/^https?:$/.test(protocol)) return null;
      const host = hostname.toLowerCase();
      const hit = Object.entries(PLATFORMS)
        .find(([, domains]) => domains.some((d) => host === d || host.endsWith("." + d)));
      return hit ? hit[0] : null;
    } catch { return null; }
  };
  const say = (msg, kind = "") => { hint.textContent = msg; hint.className = "hint " + kind; };
  const fmt = (s) => {
    s = Math.max(0, Math.floor(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
  };
  const fmtBytes = (b) => {
    if (b >= 1e9) return (b / 1e9).toFixed(b >= 1e10 ? 0 : 1).replace(".", ",") + " GB";
    if (b >= 1e6) return Math.round(b / 1e6) + " MB";
    return Math.max(1, Math.round(b / 1e3)) + " kB";
  };
  // '90', '1:30' o '1:02:03' -> segundos; null si está vacío, NaN si no se entiende.
  const parseTime = (v) => {
    v = v.trim().replace(",", ".");
    if (!v) return null;
    const parts = v.split(":");
    if (parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return NaN;
    return parts.reduce((t, p) => t * 60 + parseFloat(p), 0);
  };
  const api = async (url, opts) => {
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(data.error || "No se pudo conectar con el servidor."), { status: r.status });
    return data;
  };
  const store = {
    get: (k, def) => { try { return JSON.parse(localStorage.getItem(k)) ?? def; } catch { return def; } },
    set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } },
    del: (k) => { try { localStorage.removeItem(k); } catch { /* sin almacenamiento */ } },
  };

  // ---------- onda de progreso ----------
  for (let i = 0; i < BARS; i++) {
    const el = document.createElement("i");
    const h = 22 + Math.abs(Math.sin(i * 1.7) * Math.cos(i * 0.45)) * 78;
    el.style.setProperty("--h", h + "%");
    el.style.setProperty("--d", (i % 9) * 0.08 + "s");
    wave.appendChild(el);
  }
  const setProgress = (p) => {
    const n = Math.round(p * BARS);
    [...wave.children].forEach((el, i) => el.classList.toggle("on", i < n));
  };

  // ---------- recorte ----------
  // Devuelve { start, end } (textos para el servidor), { error } o null si no hay recorte.
  const readClip = () => {
    if (state.mode === "thumb") return null;
    const s = parseTime(startIn.value), e = parseTime(endIn.value);
    if (Number.isNaN(s) || Number.isNaN(e)) return { error: "Tiempo no válido: usa mm:ss o h:mm:ss." };
    if (!s && e === null) return null;
    const dur = state.info && state.info.duration;
    if (e !== null && e <= (s || 0)) return { error: "El final del recorte tiene que ir después del inicio." };
    if (dur && (s || 0) >= dur) return { error: "El recorte empieza después del final del vídeo." };
    const from = s || 0, to = e === null ? dur : dur ? Math.min(e, dur) : e;
    return {
      start: startIn.value.trim(), end: endIn.value.trim(),
      seconds: to ? to - from : null,
      text: `${fmt(from)}–${to ? fmt(to) : "final"}`,
    };
  };

  // ---------- modalidad y calidad ----------
  const qualitiesFor = (mode) => {
    const max = state.info && state.info.max_res;
    return MODES[mode].qualities
      .filter((q) => !max || !/^\d+$/.test(q.id) || +q.id < max) // la más alta ya es "Máxima"
      .map((q) => (q.id === "best" && max ? { ...q, label: `Máxima · ${max}p` } : q));
  };
  const currentQuality = () => {
    const list = qualitiesFor(state.mode);
    const want = state.picked[state.mode] || MODES[state.mode].default;
    return list.find((q) => q.id === want) || list[0];
  };

  // Tamaño aproximado de lo que se va a descargar, teniendo en cuenta el recorte.
  const renderSize = () => {
    const info = state.info, clip = readClip();
    let bytes = info && info.sizes && (info.sizes[state.mode] || {})[currentQuality().id];
    if (bytes && clip && !clip.error) {
      bytes = clip.seconds && info.duration ? bytes * clip.seconds / info.duration : null;
    }
    $("size").textContent = bytes ? "≈ " + fmtBytes(bytes) : "";
  };

  const renderQualities = () => {
    const box = $("quals");
    const current = currentQuality();
    box.replaceChildren(...qualitiesFor(state.mode).map((q) => {
      const label = document.createElement("label");
      label.className = "chip";
      const radio = Object.assign(document.createElement("input"), {
        type: "radio", name: "quality", value: q.id, checked: q.id === current.id,
      });
      const span = document.createElement("span");
      span.textContent = q.label;
      label.append(radio, span);
      return label;
    }));
    renderButton();
  };

  const renderButton = () => {
    renderSize();
    if (state.busy) return;
    const m = MODES[state.mode];
    $("btnLabel").textContent = "Descargar " + [m.tag, currentQuality().label].filter(Boolean).join(" · ");
    $("pct").textContent = "";
  };

  const setMode = (mode, animate = true) => {
    state.mode = mode;
    document.body.dataset.mode = mode;
    form.elements.mode.value = mode;
    const noun = $("noun");
    noun.textContent = MODES[mode].noun;
    if (animate) {
      noun.classList.remove("swap");
      void noun.offsetWidth; // reinicia la animación
      noun.classList.add("swap");
    }
    renderQualities();
  };

  form.addEventListener("change", (e) => {
    if (e.target.name === "mode") setMode(e.target.value);
    if (e.target.name === "quality") { state.picked[state.mode] = e.target.value; renderButton(); }
  });
  [startIn, endIn].forEach((el) => el.addEventListener("input", () => {
    const clip = readClip();
    if (!state.busy) say(clip && clip.error ? clip.error : "", "error");
    renderSize();
  }));

  // ---------- vista previa ----------
  const markPlatform = (p) =>
    document.querySelectorAll(".platforms li").forEach((li) => li.classList.toggle("on", li.dataset.p === p));

  const thumb = $("thumb");
  thumb.addEventListener("load", () =>
    thumb.parentElement.classList.toggle("wide", thumb.naturalWidth > thumb.naturalHeight));

  const resetPreview = () => {
    state.info = null; state.infoUrl = "";
    preview.dataset.state = "empty";
    thumb.hidden = true;
    thumb.removeAttribute("src");
    thumb.parentElement.classList.remove("wide");
    $("dur").textContent = "";
    $("title").textContent = "Aquí aparecerá tu vídeo";
    $("meta").textContent = "Pega un enlace para verlo antes de descargar.";
    endIn.placeholder = "final";
    renderQualities();
  };

  const analyse = async (url) => {
    if (url === state.infoUrl && state.info) return state.info;
    if (infoAbort) infoAbort.abort();
    infoAbort = new AbortController();
    resetPreview();
    preview.dataset.state = "loading";
    $("title").textContent = "Leyendo el vídeo…";
    $("meta").textContent = platformOf(url) || "";
    try {
      const data = await api(`/api/info?url=${encodeURIComponent(url)}`, { signal: infoAbort.signal });
      state.info = data; state.infoUrl = url;
      preview.dataset.state = "ready";
      $("title").textContent = data.title || "Vídeo sin título";
      $("meta").textContent = [data.author, data.platform, data.max_res && `hasta ${data.max_res}p`]
        .filter(Boolean).join(" · ");
      $("dur").textContent = data.live ? "EN DIRECTO" : data.duration ? fmt(data.duration) : "";
      if (data.duration) endIn.placeholder = fmt(data.duration);
      if (data.thumbnail) { thumb.src = data.thumbnail; thumb.hidden = false; }
      renderQualities();
      if (!state.busy) say("");
      return data;
    } catch (err) {
      if (err.name === "AbortError") return null;
      resetPreview();
      say(err.message, "error");
      throw err;
    }
  };

  const onUrlChange = () => {
    clearTimeout(debounce);
    const url = input.value.trim();
    const p = platformOf(url);
    markPlatform(p);
    if (!url) { if (infoAbort) infoAbort.abort(); resetPreview(); return say(""); }
    if (!p) return say(url.length > 12 ? UNSUPPORTED : "", "error");
    say("");
    debounce = setTimeout(() => analyse(url).catch(() => {}), 450);
  };
  input.addEventListener("input", onUrlChange);

  if (navigator.clipboard && navigator.clipboard.readText) {
    const paste = $("paste");
    paste.hidden = false;
    paste.addEventListener("click", async () => {
      try {
        input.value = (await navigator.clipboard.readText()).trim();
        onUrlChange();
      } catch { input.focus(); say("Tu navegador no deja leer el portapapeles: pega el enlace a mano."); }
    });
  }

  // ---------- descarga ----------
  const setBusy = (busy) => {
    state.busy = busy;
    btn.disabled = busy;
    cancelBtn.hidden = !busy;
    cancelBtn.disabled = false;
    document.body.classList.toggle("busy", busy);
    if (!busy) { state.jobId = null; renderButton(); }
  };

  const MAX_NET_FAILS = 20; // en el móvil la red va y viene: no abandonar al primer fallo
  const poll = (id) => new Promise((resolve, reject) => {
    let fails = 0;
    const tick = async () => {
      let job;
      try {
        job = await api(`/api/jobs/${id}`);
        fails = 0;
      } catch (err) {
        if (err.status || ++fails > MAX_NET_FAILS) return reject(err);
        say("Sin conexión, reintentando…");
        return setTimeout(tick, 2000);
      }
      if (job.status === "error") return reject(new Error(job.error || "La descarga falló."));
      if (job.status === "cancelled") return reject(Object.assign(new Error("Descarga cancelada."), { cancelled: true }));
      if (job.status === "done") return resolve(job);
      const known = job.status === "downloading";
      $("btnLabel").textContent = STATUS[job.status] || "Trabajando…";
      $("pct").textContent = known ? Math.round(job.progress * 100) + "%" : "···";
      setProgress(known ? job.progress : job.status === "queued" ? 0 : 1);
      say(known && job.speed
        ? [fmtBytes(job.speed) + "/s", job.eta != null && `quedan ${fmt(job.eta)}`].filter(Boolean).join(" · ")
        : job.status === "clipping" ? "Recortando el tramo elegido; puede tardar un poco." : "");
      setTimeout(tick, 500);
    };
    tick();
  });

  // Sigue un trabajo hasta el final. `meta` = { id, url, mode, quality, label }.
  const follow = async (meta) => {
    state.jobId = meta.id;
    store.set(ACTIVE_KEY, meta);
    try {
      const done = await poll(meta.id);
      setProgress(1);
      const a = Object.assign(document.createElement("a"), { href: `/api/jobs/${meta.id}/file`, download: "" });
      document.body.appendChild(a); a.click(); a.remove();
      say(`Listo: «${done.filename}»${done.size ? ` (${fmtBytes(done.size)})` : ""} está en tus descargas.`);
      remember({ ...meta, id: undefined, title: done.title || meta.url });
    } catch (err) {
      setProgress(0);
      say(err.message || "No se pudo completar la descarga.", err.cancelled ? "" : "error");
    } finally {
      store.del(ACTIVE_KEY);
      setBusy(false);
    }
  };

  const startBusy = () => {
    setBusy(true);
    setProgress(0);
    say("");
    $("btnLabel").textContent = STATUS.queued;
    $("pct").textContent = "···";
  };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.busy) return;
    const url = input.value.trim();
    if (!platformOf(url)) return say(UNSUPPORTED, "error");
    const clip = readClip();
    if (clip && clip.error) return say(clip.error, "error");

    const mode = state.mode, quality = currentQuality();
    clearTimeout(debounce);
    startBusy();
    analyse(url).catch(() => {}); // la vista previa no bloquea la descarga
    try {
      const job = await api("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, mode, quality: quality.id, start: clip && clip.start, end: clip && clip.end }),
      });
      await follow({
        id: job.id, url, mode, quality: quality.id,
        label: [quality.label, clip && clip.text].filter(Boolean).join(" · "),
        start: clip ? clip.start : "", end: clip ? clip.end : "",
      });
    } catch (err) {
      say(err.message || "No se pudo completar la descarga.", "error");
      setBusy(false);
    }
  });

  cancelBtn.addEventListener("click", () => {
    if (!state.jobId) return;
    cancelBtn.disabled = true;
    fetch(`/api/jobs/${state.jobId}`, { method: "DELETE" }).catch(() => {});
  });

  // ---------- recientes (solo en este navegador) ----------
  const sameItem = (a, b) => ["url", "mode", "quality", "start", "end"].every((k) => (a[k] || "") === (b[k] || ""));
  const remember = (item) => {
    const list = [item, ...store.get(RECENT_KEY, []).filter((r) => !sameItem(r, item))].slice(0, 6);
    store.set(RECENT_KEY, list);
    renderRecent(list);
  };
  const renderRecent = (list = store.get(RECENT_KEY, [])) => {
    list = list.filter((r) => MODES[r.mode]);
    $("recent").hidden = !list.length;
    $("recentList").replaceChildren(...list.map((r) => {
      const li = document.createElement("li");
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = `var(--a-${r.mode})`;
      const t = document.createElement("span");
      t.className = "t"; t.textContent = r.title;
      const q = document.createElement("span");
      q.className = "q"; q.textContent = `${MODES[r.mode].label} · ${r.label}`;
      const again = document.createElement("button");
      again.type = "button"; again.textContent = "Repetir";
      again.addEventListener("click", () => {
        if (state.busy) return;
        input.value = r.url;
        startIn.value = r.start || ""; endIn.value = r.end || "";
        state.picked[r.mode] = r.quality;
        setMode(r.mode);
        onUrlChange();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
      li.append(dot, t, q, again);
      return li;
    }));
  };

  // ---------- arranque ----------
  // Enlace recibido con "Compartir" (app instalada) o como /?url=…
  const shared = new URLSearchParams(location.search);
  const sharedUrl = [shared.get("url"), shared.get("text"), shared.get("title")]
    .map((v) => ((v || "").match(/https?:\/\/\S+/) || [])[0])
    .find(Boolean);
  if (sharedUrl) {
    input.value = sharedUrl;
    history.replaceState(null, "", location.pathname);
  }

  setMode(state.mode, false);
  renderRecent();
  if (input.value.trim()) onUrlChange();

  // Si se recargó la página (o el móvil cerró la pestaña) a media descarga, se retoma.
  const active = store.get(ACTIVE_KEY, null);
  if (active && active.id && MODES[active.mode]) {
    if (!sharedUrl) {
      input.value = active.url;
      startIn.value = active.start || ""; endIn.value = active.end || "";
      state.picked[active.mode] = active.quality;
      setMode(active.mode, false);
      onUrlChange();
    }
    startBusy();
    follow(active);
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
})();
