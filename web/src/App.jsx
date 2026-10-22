import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, fmt } from "./api.js";

const TABS = [
  { id: "play", label: "Reproducir", icon: "▶" },
  { id: "search", label: "Buscar", icon: "⌕" },
  { id: "episodes", label: "Capítulos", icon: "☰" },
  { id: "log", label: "Registro", icon: "≡" },
];

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("autonext.theme") || "dark"; } catch { return "dark"; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("autonext.theme", theme); } catch {}
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

export default function App() {
  const [state, setState] = useState(null);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("play");
  const [theme, toggleTheme] = useTheme();
  const lastLog = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const s = await api.state(lastLog.current);
      if (s.logs.length) {
        lastLog.current = s.logs[s.logs.length - 1].id;
        setLogs((l) => [...l, ...s.logs].slice(-200));
      }
      setState(s);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 1000);
    return () => clearInterval(id);
  }, [refresh]);

  const run = (fn) => async (...a) => {
    try { await fn(...a); setTimeout(refresh, 250); } catch (e) { setError(e.message); }
  };

  if (!api.hasToken()) {
    return <Center>Abre el enlace completo que muestra el panel de la PC (incluye <code>?t=</code>).</Center>;
  }
  if (!state) return <Center>{error ? `Sin conexión: ${error}` : "Conectando…"}</Center>;

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>AutoNext</h1>
          <span className={`pill ${state.running ? (state.status.paused ? "warn" : "ok") : ""}`}>
            {!state.running ? "Detenido" : state.status.mode === "browsing" ? "Navegando" : state.status.paused ? "En pausa" : "Reproduciendo"}
          </span>
        </div>
        <div className="row">
          <button className="icon" onClick={run(() => api.cmd("back"))} disabled={!state.running}
            aria-label="Atrás">←</button>
          <button className="icon" onClick={toggleTheme} aria-label="Modo noche">{theme === "dark" ? "☀" : "☾"}</button>
        </div>
      </header>
      {error && <div className="error">{error}</div>}

      <main>
        {tab === "play" && <><SearchBox s={state} onSearch={() => setTab("search")} /><PlayTab s={state} run={run} /></>}
        {tab === "search" && <SearchTab s={state} run={run} goEpisodes={() => setTab("episodes")} />}
        {tab === "episodes" && <EpisodesTab s={state} run={run} goPlay={() => setTab("play")} />}
        {tab === "log" && <LogTab logs={logs} url={state.server_url} />}
      </main>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            <span className="ti">{t.icon}</span>{t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}

function Center({ children }) {
  return <div className="center">{children}</div>;
}

function PlayTab({ s, run }) {
  const st = s.status;
  const [drag, setDrag] = useState(null);
  const pos = drag ?? st.position;
  const prog = s.progress[s.active];
  const [count, setCount] = useState(s.limit.count);
  useEffect(() => setCount(s.limit.count), [s.limit.count]);

  return (
    <>
      <section className="card">
        <div className="row between">
          <div className="chips">
            {s.profiles.map((p) => (
              <button key={p} className={`chip ${p === s.active ? "on" : ""}`} disabled={s.running}
                onClick={run(() => api.profile(p))}>{p}</button>
            ))}
          </div>
        </div>
        {s.running ? (
          <button className="btn danger wide" onClick={run(api.stop)}>■ Detener</button>
        ) : (
          <button className="btn primary wide" onClick={run(() => api.start(s.active))}>
            ▶ {prog ? "Continuar donde quedé" : "Iniciar"}
          </button>
        )}
        {!s.running && prog && (
          <p className="muted small">Último: {prog.title || prog.url} · {fmt(prog.position)}</p>
        )}
      </section>

      <section className="card now">
        <p className="muted small">AHORA</p>
        <h2 className="title">{st.title || (s.running ? "Cargando…" : "Nada en reproducción")}</h2>
        <div className="stats">
          <div><b>{st.episode}</b><span>capítulos</span></div>
          <div><b>{st.server}</b><span>servidor</span></div>
          <div><b>{st.duration ? fmt(st.duration - pos) : "--:--"}</b><span>faltan</span></div>
        </div>
        <input type="range" className="seek" min="0" max={st.duration || 1} step="1" value={pos}
          disabled={!st.duration}
          onChange={(e) => setDrag(Number(e.target.value))}
          onPointerUp={run(async () => { if (drag != null) { await api.cmd("seek", { position: drag }); setDrag(null); } })}
          onTouchEnd={run(async () => { if (drag != null) { await api.cmd("seek", { position: drag }); setDrag(null); } })} />
        <div className="row between small muted"><span>{fmt(pos)}</span><span>{fmt(st.duration)}</span></div>

        <div className="controls">
          <button onClick={run(() => api.cmd("seek_relative", { delta: -30 }))}>-30</button>
          <button onClick={run(() => api.cmd("seek_relative", { delta: -10 }))}>-10</button>
          <button className="big" onClick={run(() => api.cmd("toggle_pause"))}>{st.paused ? "▶" : "❚❚"}</button>
          <button onClick={run(() => api.cmd("seek_relative", { delta: 10 }))}>+10</button>
          <button onClick={run(() => api.cmd("seek_relative", { delta: 30 }))}>+30</button>
        </div>
        <div className="row volume">
          <button className="btn" onClick={run(() => api.cmd("mute"))} aria-label="Silenciar">{st.muted ? "🔇" : "🔈"}</button>
          <button className="btn" onClick={run(() => api.cmd("volume", { delta: -0.1 }))}>− Vol</button>
          <b className="vol">{st.volume == null ? "--" : st.muted ? "0" : st.volume}%</b>
          <button className="btn" onClick={run(() => api.cmd("volume", { delta: 0.1 }))}>+ Vol</button>
        </div>
        {s.running && s.servers.length > 0 && (
          <div className="chips scroll servers">
            {s.servers.map((n) => (
              <button key={n} className={`chip ${n === st.server || n.includes(st.server) ? "on" : ""}`}
                onClick={run(() => api.cmd("server", { name: n }))}>{n}</button>
            ))}
          </div>
        )}
        <div className="grid3">
          <button className="btn" onClick={run(() => api.cmd("skip"))}>⏭ Siguiente</button>
          <button className="btn" onClick={run(() => api.cmd("switch_server"))}>⇄ Servidor</button>
          <button className="btn" onClick={run(() => api.cmd("fullscreen", { on: !st.fullscreen }))}>
            {st.fullscreen ? "🗗 Ventana" : "⛶ Pantalla"}
          </button>
        </div>
      </section>

      <section className="card">
        <div className="row between">
          <div>
            <b>Calidad más alta</b>
            <p className="muted small">Si el reproductor tiene opciones de calidad · idioma: {s.language}</p>
          </div>
          <label className="switch">
            <input type="checkbox" checked={s.quality} onChange={run((e) => api.quality(e.target.checked))} />
            <span />
          </label>
        </div>
      </section>

      <section className="card">
        <div className="row between">
          <div>
            <b>Límite de capítulos</b>
            <p className="muted small">Se detiene al terminar el último</p>
          </div>
          <label className="switch">
            <input type="checkbox" checked={s.limit.enabled}
              onChange={run((e) => api.limit(e.target.checked, count))} />
            <span />
          </label>
        </div>
        {s.limit.enabled && (
          <div className="row stepper">
            <button onClick={run(() => api.limit(true, Math.max(1, count - 1)))}>−</button>
            <b>{count}</b>
            <button onClick={run(() => api.limit(true, count + 1))}>+</button>
            <span className="muted small">vistos en esta sesión: {st.episode}</span>
          </div>
        )}
      </section>

      {st.ranking?.length > 0 && (
        <section className="card">
          <b>Salud de servidores</b>
          {st.ranking.map(([n, sc]) => (
            <div key={n} className="health">
              <span>{n}</span>
              <div className="bar"><i style={{ width: `${sc * 100}%`, background: sc >= 0.6 ? "var(--ok)" : sc >= 0.35 ? "var(--warn)" : "var(--danger)" }} /></div>
            </div>
          ))}
        </section>
      )}
    </>
  );
}

function SearchBox({ s, onSearch }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    try { await api.cmd("search", { query: q.trim() }); onSearch?.(); } finally { setTimeout(() => setBusy(false), 4000); }
  };
  return (
    <form className="card search" onSubmit={submit}>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Buscar serie en ${s.active}…`} />
      <button className="btn primary" disabled={busy}>{busy ? "…" : "Buscar"}</button>
    </form>
  );
}

function SearchTab({ s, run, goEpisodes }) {
  return (
    <>
      <SearchBox s={s} />
      <div className="results">
        {s.results.map((r) => (
          <button key={r.url} className="result" onClick={run(async () => { await api.cmd("open", { url: r.url }); goEpisodes(); })}>
            {r.image ? <img src={r.image} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <div className="noimg">▶</div>}
            <span>{r.title}</span>
          </button>
        ))}
      </div>
      {!s.results.length && <p className="muted center-text">Escribe el nombre de una serie. Se busca en el sitio del perfil activo.</p>}
    </>
  );
}

function EpisodesTab({ s, run, goPlay }) {
  // Al entrar sin lista, pedirla a la pagina abierta
  useEffect(() => {
    if (s.running && !s.episodes.length) run(() => Promise.all([api.cmd("episodes"), api.cmd("seasons")]))();
  }, []);
  return (
    <>
      <section className="card">
        <div className="row between">
          <b>Capítulos</b>
          <button className="btn small" onClick={run(() => Promise.all([api.cmd("episodes"), api.cmd("seasons")]))}>↻ Leer página</button>
        </div>
        {s.seasons.length > 0 && (
          <div className="chips scroll">
            {s.seasons.map((name, i) => (
              <button key={i} className="chip" onClick={run(() => api.cmd("season", { index: i }))}>{name}</button>
            ))}
          </div>
        )}
      </section>
      <div className="list">
        {s.episodes.map((e) => (
          <button key={e.url} className={`ep ${e.current || e.url === s.status.url ? "on" : ""}`}
            onClick={run(async () => { await api.cmd("open", { url: e.url }); goPlay(); })}>
            <span>{e.title}</span><small>{decodeURIComponent(e.url.split("/").filter(Boolean).pop())}</small>
          </button>
        ))}
      </div>
      {!s.episodes.length && <p className="muted center-text">Abre una serie desde Buscar o pulsa “Leer página”.</p>}
    </>
  );
}

function LogTab({ logs, url }) {
  const end = useRef(null);
  useEffect(() => end.current?.scrollIntoView(), [logs.length]);
  return (
    <>
      <section className="card">
        <b>Servidor local</b>
        <p className="mono small">{url}</p>
      </section>
      <section className="card log">
        {logs.map((l) => (
          <div key={l.id} className={`l ${l.kind}`}>
            <span>{new Date(l.at * 1000).toLocaleTimeString()}</span> {l.message}
          </div>
        ))}
        <div ref={end} />
      </section>
    </>
  );
}
