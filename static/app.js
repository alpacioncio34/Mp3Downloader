(() => {
  const $ = (id) => document.getElementById(id);
  const MODES = JSON.parse($("modes-data").textContent);
  const PLATFORMS = [
    [/(^|\.)(youtube\.com|youtu\.be)$/i, "YouTube"],
    [/(^|\.)tiktok\.com$/i, "TikTok"],
    [/(^|\.)instagram\.com$/i, "Instagram"],
  ];
  const STATUS = {
    queued: "Preparando…",
    downloading: "Descargando…",
    processing: "Convirtiendo…",
  };
  const BARS = 48;
  const RECENT_KEY = "saca.recent";

  const form = $("form"), input = $("url"), btn = $("btn"), hint = $("hint");
  const preview = $("preview"), wave = $("wave");

  const state = {
    mode: form.elements.mode.value,
    picked: {},        // calidad elegida por modalidad
    info: null,        // datos del vídeo analizado
    infoUrl: "",
    busy: false,
  };
  let infoAbort = null, debounce = null;

  // ---------- utilidades ----------
  const platformOf = (u) => {
    try {
      const { protocol, hostname } = new URL(u);
      if (!/^https?:$/.test(protocol)) return null;
      return (PLATFORMS.find(([re]) => re.test(hostname)) || [])[1] || null;
    } catch { return null; }
  };
  const say = (msg, kind = "") => { hint.textContent = msg; hint.className = "hint " + kind; };
  const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const api = async (url, opts) => {
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "No se pudo conectar con el servidor.");
    return data;
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

  // ---------- modalidad y calidad ----------
  const qualitiesFor = (mode) => {
    const max = state.info && state.info.max_res;
    return MODES[mode].qualities
      .filter((q) => !max || !/^\d+$/.test(q.id) || +q.id <= max)
      .map((q) => (q.id === "best" && max ? { ...q, label: `Máxima · ${max}p` } : q));
  };
  const currentQuality = () => {
    const list = qualitiesFor(state.mode);
    const want = state.picked[state.mode] || MODES[state.mode].default;
    return list.find((q) => q.id === want) || list[0];
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

  // ---------- vista previa ----------
  const markPlatform = (p) =>
    document.querySelectorAll(".platforms li").forEach((li) => li.classList.toggle("on", li.dataset.p === p));

  const resetPreview = () => {
    state.info = null; state.infoUrl = "";
    preview.dataset.state = "empty";
    $("thumb").hidden = true;
    $("thumb").removeAttribute("src");
    $("dur").textContent = "";
    $("title").textContent = "Aquí aparecerá tu vídeo";
    $("meta").textContent = "Pega un enlace para verlo antes de descargar.";
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
      $("dur").textContent = data.duration ? fmt(data.duration) : "";
      if (data.thumbnail) { $("thumb").src = data.thumbnail; $("thumb").hidden = false; }
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
    if (!p) return say(url.length > 12 ? "Ese enlace no es de YouTube, TikTok ni Instagram." : "", "error");
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
      } catch { input.focus(); say("Tu navegador no deja leer el portapapeles: pega con Ctrl+V."); }
    });
  }

  // ---------- descarga ----------
  const setBusy = (busy) => {
    state.busy = busy;
    btn.disabled = busy;
    document.body.classList.toggle("busy", busy);
    if (!busy) renderButton();
  };

  const poll = (id) => new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const job = await api(`/api/jobs/${id}`);
        if (job.status === "error") return reject(new Error(job.error || "La descarga falló."));
        if (job.status === "done") return resolve(job);
        const pct = Math.round(job.progress * 100);
        $("btnLabel").textContent = STATUS[job.status] || "Trabajando…";
        $("pct").textContent = job.status === "downloading" ? pct + "%" : "···";
        setProgress(job.status === "queued" ? 0 : job.progress);
        setTimeout(tick, 500);
      } catch (err) { reject(err); }
    };
    tick();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.busy) return;
    const url = input.value.trim();
    if (!platformOf(url)) return say("Ese enlace no es de YouTube, TikTok ni Instagram.", "error");

    const mode = state.mode, quality = currentQuality();
    clearTimeout(debounce);
    setBusy(true);
    setProgress(0);
    say("");
    $("btnLabel").textContent = STATUS.queued;
    $("pct").textContent = "···";

    try {
      analyse(url).catch(() => {}); // la vista previa no bloquea la descarga
      const job = await api("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, mode, quality: quality.id }),
      });
      const done = await poll(job.id);
      setProgress(1);

      const a = Object.assign(document.createElement("a"), { href: `/api/jobs/${job.id}/file`, download: "" });
      document.body.appendChild(a); a.click(); a.remove();

      say(`Listo: «${done.filename}» está en tus descargas.`);
      remember({ url, mode, quality: quality.id, label: quality.label, title: done.title || url });
    } catch (err) {
      setProgress(0);
      say(err.message || "No se pudo completar la descarga.", "error");
    } finally {
      setBusy(false);
    }
  });

  // ---------- recientes (solo en este navegador) ----------
  const loadRecent = () => {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch { return []; }
  };
  const remember = (item) => {
    const list = [item, ...loadRecent().filter((r) => !(r.url === item.url && r.mode === item.mode && r.quality === item.quality))].slice(0, 6);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* sin almacenamiento */ }
    renderRecent(list);
  };
  const renderRecent = (list = loadRecent()) => {
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
  setMode(state.mode, false);
  renderRecent();
  if (input.value.trim()) onUrlChange();
})();
