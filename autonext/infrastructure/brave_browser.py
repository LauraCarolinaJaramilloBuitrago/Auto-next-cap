"""Adaptador BrowserPort: Brave controlado por Playwright via CDP (puerto de depuracion)."""
from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import quote_plus, urljoin, urlparse

from playwright.sync_api import sync_playwright

from ..domain.models import Episode, PlaybackState, SearchResult, Server, SiteProfile
from ..domain.ports import BrowserPort

if sys.platform.startswith("win"):
    BRAVE_CANDIDATES = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
elif sys.platform == "darwin":
    BRAVE_CANDIDATES = ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
else:
    BRAVE_CANDIDATES = [
        shutil.which("brave-browser") or "", shutil.which("brave") or "",
        shutil.which("brave-browser-stable") or "",
        "/usr/bin/brave-browser", "/opt/brave.com/brave/brave", "/snap/bin/brave",
        "/var/lib/flatpak/exports/bin/com.brave.Browser",
    ]


def find_brave() -> str:
    return next((p for p in BRAVE_CANDIDATES if p and os.path.exists(p)), next(p for p in BRAVE_CANDIDATES if p))


# Elige el <video> real: el de mayor duracion por encima del minimo (ignora anuncios cortos)
JS_PICK = """(min) => [...document.querySelectorAll('video')]
    .filter(v => isFinite(v.duration) && v.duration >= min)
    .sort((a, b) => b.duration - a.duration)[0]"""

JS_STATE = f"""(min) => {{
  const v = ({JS_PICK})(min);
  if (!v) return null;
  return {{position: v.currentTime, duration: v.duration, paused: v.paused,
          ended: v.ended, error: !!v.error, volume: v.volume, muted: v.muted}};
}}"""

JS_PLAY = """() => {
  for (const v of document.querySelectorAll('video')) {
    if (v.paused) v.play().catch(() => {});
  }
  return document.querySelectorAll('video').length;
}"""

JS_SEEK = f"""([pos, min]) => {{
  const v = ({JS_PICK})(min);
  if (v) v.currentTime = pos;
  return !!v;
}}"""

JS_PAUSE = f"""([paused, min]) => {{
  const v = ({JS_PICK})(min);
  if (!v) return false;
  if (paused) v.pause(); else v.play().catch(() => {{}});
  return true;
}}"""

JS_VOLUME = f"""([delta, min]) => {{
  const v = ({JS_PICK})(min);
  if (!v) return null;
  v.muted = false;
  v.volume = Math.max(0, Math.min(1, Math.round((v.volume + delta) * 100) / 100));
  return v.volume;
}}"""

JS_MUTE = f"""(min) => {{
  const v = ({JS_PICK})(min);
  if (!v) return null;
  v.muted = !v.muted;
  return v.muted;
}}"""

JS_FULLSCREEN = f"""(min) => {{
  const v = ({JS_PICK})(min);
  if (!v || document.fullscreenElement) return false;
  const box = v.closest('.plyr, .jwplayer, .video-js, [class*=player]') || v;
  box.requestFullscreen().catch(() => {{}});
  return true;
}}"""

JS_EXIT_FS = """() => {
  try { if (document.fullscreenElement) document.exitFullscreen(); } catch (e) {}
  try { if (document.webkitFullscreenElement) document.webkitExitFullscreen(); } catch (e) {}
}"""

# Anuncios "clickjack": enlaces transparentes que tapan media pagina y abren pestañas
JS_KILL_CLICKJACK = """() => {
  const area = innerWidth * innerHeight; let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'absolute') continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height < area * 0.4) continue;
    const z = parseInt(cs.zIndex) || 0;
    const adLink = el.tagName === 'A' && el.target === '_blank';
    const onlyLinks = el.children.length && [...el.children].every(c => c.tagName === 'A' && c.target === '_blank');
    if ((adLink || onlyLinks) && z >= 100) { el.remove(); n++; }
  }
  return n;
}"""

JS_LINKS = """(re) => {
  const rx = new RegExp(re), seen = new Set(), out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    if ((a.getAttribute('href') || '').includes('#')) continue;  // "mostrar mas", anclas internas
    const href = new URL(a.getAttribute('href'), location.href).href;  // absoluta siempre
    if (!rx.test(href)) continue;
    const img = a.querySelector('img');
    const title = (a.innerText || a.title || (img && img.alt) || '').trim().replace(/\\s+/g, ' ')
      .replace(/^(image|imagen|poster)\\s+/i, '');
    const image = img ? (img.dataset.src || img.getAttribute('data-lazy-src') || img.src || '') : '';
    const prev = out.find(o => o.url === href);
    if (prev) {  // mismo enlace repetido: quedarse con el titulo/imagen mas completos
      if (title.length > prev.title.length) prev.title = title;  // "22m" < "E1 - Maomao"
      if (!prev.image && image) prev.image = image;
      continue;
    }
    seen.add(href);
    out.push({url: href, title, image, current: href === location.href.split('#')[0]});
  }
  return out;
}"""


# Reproductores conocidos: elegir el nivel de mayor altura/bitrate. Devuelve etiqueta o null.
JS_MAX_QUALITY = r"""() => {
  const best = (arr, f) => arr.reduce((b, x, i) => (f(x) > f(arr[b]) ? i : b), 0);
  const num = (x) => parseInt(String(x).replace(/\D/g, '')) || 0;
  try {
    if (window.jwplayer) {
      const p = window.jwplayer(), q = (p.getQualityLevels && p.getQualityLevels()) || [];
      if (q.length > 1) {
        const i = best(q, (l) => l.height || num(l.label));
        if (p.getCurrentQuality() !== i) p.setCurrentQuality(i);
        return q[i].label || (q[i].height + 'p');
      }
    }
  } catch (e) {}
  try {
    for (const p of Object.values((window.videojs && window.videojs.getPlayers && window.videojs.getPlayers()) || {})) {
      const ql = p && p.qualityLevels && p.qualityLevels();
      if (ql && ql.length > 1) {
        let b = 0;
        for (let i = 0; i < ql.length; i++) if ((ql[i].height || 0) > (ql[b].height || 0)) b = i;
        for (let i = 0; i < ql.length; i++) ql[i].enabled = i === b;
        return ql[b].height + 'p';
      }
    }
  } catch (e) {}
  try {
    for (const el of document.querySelectorAll('.plyr, video')) {
      const p = el.plyr, q = p && p.options && p.options.quality;
      if (q && q.length > 1) {
        const m = Math.max(...q.map(Number).filter((n) => !isNaN(n)));
        if (isFinite(m)) { if (p.quality !== m) p.quality = m; return m + 'p'; }
      }
    }
  } catch (e) {}
  try {
    const a = window.art || (window.Artplayer && window.Artplayer.instances && window.Artplayer.instances[0]);
    const q = a && a.option && a.option.quality;
    if (q && q.length > 1) {
      const i = best(q, (x) => num(x.html));
      if (!q[i].default) { q.forEach((x, j) => (x.default = j === i)); a.switchQuality(q[i].url, q[i].html); }
      return q[i].html;
    }
  } catch (e) {}
  for (const k of Object.keys(window)) {  // hls.js: instancia guardada en alguna variable global
    try {  // window[k] de iframes ajenos lanza SecurityError
      const o = window[k];
      if (o && typeof o === 'object' && Array.isArray(o.levels) && 'currentLevel' in o && o.levels.length > 1) {
        const i = best(o.levels, (l) => l.height || l.bitrate || 0);
        if (o.currentLevel !== i) o.currentLevel = i;
        return (o.levels[i].height || '') + 'p';
      }
    } catch (e) {}
  }
  return null;
}"""


class BraveBrowser(BrowserPort):
    def __init__(self, exe: str | None = None, profile_dir: str = "brave_profile", port: int = 9222):
        self.exe = exe if exe and os.path.exists(exe) else find_brave()  # ruta guardada de otro SO: buscar
        self.profile_dir = os.path.abspath(profile_dir)
        self.port = port
        self._pw = None
        self._browser = None
        self.ctx = None
        self.page = None

    # ---------- ciclo de vida ----------
    def _cdp_up(self) -> bool:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=2)
            return True
        except Exception:
            return False

    def start(self, url: str, reuse_host: str | None) -> None:
        if not self._cdp_up():
            subprocess.Popen([
                self.exe, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile_dir}",
                "--autoplay-policy=no-user-gesture-required", "--start-maximized",
                "--no-first-run", "--no-default-browser-check", url,
            ])
            for _ in range(40):
                if self._cdp_up():
                    break
                time.sleep(0.5)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.ctx = self._browser.contexts[0]
        tabs = []
        for _ in range(10):  # Brave recien abierto tarda en registrar la pestaña
            tabs = [p for p in self.ctx.pages if reuse_host and reuse_host in p.url]
            if tabs or not reuse_host:
                break
            time.sleep(0.5)
        if tabs:
            self.page = tabs[-1]
        else:
            same = [p for p in self.ctx.pages if p.url.rstrip("/") == url.rstrip("/")]
            self.page = same[-1] if same else (self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page())
            if self.page.url.rstrip("/") != url.rstrip("/"):
                self.page.goto(url, wait_until="domcontentloaded")
        self.page.bring_to_front()
        self.page.wait_for_timeout(1500)

    def close(self) -> None:
        # Desconecta sin cerrar Brave (sigue abierto para el usuario)
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None

    def is_alive(self) -> bool:
        try:
            return self.page is not None and not self.page.is_closed() and self._browser.is_connected()
        except Exception:
            return False

    def current_url(self) -> str:
        try:
            return self.page.url
        except Exception:
            return ""

    def page_title(self) -> str:
        try:
            return self.page.title()
        except Exception:
            return ""

    def wait(self, seconds: float) -> None:
        # wait_for_timeout deja a Playwright procesar eventos (frames y pestañas nuevas)
        try:
            self.page.wait_for_timeout(max(0, seconds) * 1000)
        except Exception:
            time.sleep(max(0, seconds))

    # ---------- video ----------
    def _video_frame(self, min_duration: float):
        best = (None, None)
        for fr in self.page.frames:
            try:
                st = fr.evaluate(JS_STATE, min_duration)
            except Exception:
                continue
            if st and (best[1] is None or st["duration"] > best[1]["duration"]):
                best = (fr, st)
        return best

    def video_state(self, min_duration: float) -> PlaybackState | None:
        _, st = self._video_frame(min_duration)
        return PlaybackState(**st) if st else None

    def seek(self, position: float, min_duration: float) -> None:
        fr, _ = self._video_frame(min_duration)
        if fr:
            fr.evaluate(JS_SEEK, [position, min_duration])

    def set_paused(self, paused: bool, min_duration: float) -> None:
        fr, _ = self._video_frame(min_duration)
        if fr:
            fr.evaluate(JS_PAUSE, [paused, min_duration])

    # Pantalla completa del elemento solo llena la pestaña; la ventana de Brave
    # se pasa a pantalla completa aparte por CDP.
    def _window(self):
        cdp = self.ctx.new_cdp_session(self.page)
        win = cdp.send("Browser.getWindowForTarget")
        return cdp, win["windowId"], win["bounds"].get("windowState", "normal")

    def _set_window_state(self, state: str) -> None:
        try:
            cdp, wid, current = self._window()
            if current == state:
                return
            if current != "normal":  # Chromium exige pasar por normal entre estados
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": state}})
            cdp.detach()
        except Exception:
            pass

    def enter_fullscreen(self) -> None:
        fr, _ = self._video_frame(60)
        if not fr:
            return
        try:
            fr.evaluate(JS_FULLSCREEN, 60)
        except Exception:
            pass
        self._set_window_state("fullscreen")

    def is_fullscreen(self) -> bool:
        try:
            cdp, _, state = self._window()
            cdp.detach()
            return state == "fullscreen"
        except Exception:
            return False

    def exit_fullscreen(self) -> None:
        for fr in self.page.frames:
            try:
                fr.evaluate(JS_EXIT_FS)
            except Exception:
                pass
        try:
            self.page.keyboard.press("Escape")
        except Exception:
            pass
        self._set_window_state("maximized")
        self.wait(0.8)

    def press_play(self, profile: SiteProfile) -> None:
        clicked = False
        for fr in self.page.frames:
            try:  # frame con video corriendo: no tocar (el boton seria pausa)
                if fr.evaluate("() => [...document.querySelectorAll('video')].some(v => !v.paused && v.currentTime > 0)"):
                    continue
            except Exception:
                continue
            for sel in profile.play_selectors:
                try:
                    loc = fr.locator(sel).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=2000)
                        clicked = True
                except Exception:
                    pass
            try:
                fr.evaluate(JS_PLAY)
            except Exception:
                pass
        if not clicked:
            ifr = self._player_iframe()
            if ifr:
                self._human_click(ifr)

    def _player_iframe(self):
        best, area = None, 0
        for loc in self.page.locator("iframe").all():
            try:
                b = loc.bounding_box()
                if b and loc.is_visible() and b["width"] * b["height"] > area:
                    best, area = loc, b["width"] * b["height"]
            except Exception:
                pass
        return best

    # ---------- navegacion ----------
    def _human_click(self, locator) -> None:
        """Mueve el mouse en pasos hasta el centro del elemento y hace clic."""
        locator.scroll_into_view_if_needed(timeout=5000)
        box = locator.bounding_box()
        if not box:
            locator.click(timeout=5000)
            return
        x = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
        y = box["y"] + box["height"] / 2 + random.uniform(-2, 2)
        self.page.mouse.move(x, y, steps=random.randint(15, 30))
        self.wait(0.2)
        self.page.mouse.click(x, y)

    def _click(self, locator) -> bool:
        """Clic humano; si algo lo tapa o esta oculto, clic directo por JS."""
        try:
            if locator.is_visible():
                self._human_click(locator)
                return True
        except Exception:
            pass
        try:
            locator.evaluate("el => el.click()")
            return True
        except Exception:
            return False

    def select_server(self, server: Server, profile: SiteProfile) -> bool:
        self.close_popups(profile)
        try:
            if server.opener:
                op = self.page.locator(server.opener).first
                if op.count():
                    self._click(op)
                    self.wait(0.8)
                    self.close_popups(profile, deep=False)
            # con pestañas de idioma hay botones repetidos ocultos: usar el visible
            all_ = self.page.locator(server.selector, has_text=server.match_text)
            vis = all_.filter(visible=True)
            loc = (vis if vis.count() else all_).first
            if not loc.count():
                return False
            return self._click(loc)
        except Exception:
            return False

    def _find_next(self, profile: SiteProfile):
        for sel in [s.strip() for s in profile.next_selector.split(",") if s.strip()]:
            loc = self.page.locator(sel).first
            try:
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                pass
        if profile.next_text:
            loc = self.page.locator("a, button", has_text=profile.next_text).first
            if loc.count():
                return loc
        return None

    def click_next(self, profile: SiteProfile) -> bool:
        href = None
        for _ in range(4):
            self.close_popups(profile)
            loc = self._find_next(profile)
            if not loc:
                return False
            href = loc.get_attribute("href") or href
            old = self.page.url
            try:
                self._human_click(loc)
            except Exception:
                pass
            for _ in range(6):
                self.wait(0.5)
                if self.page.url != old:
                    self.close_popups(profile)
                    self.page.wait_for_load_state("domcontentloaded")
                    return True
        if href:
            self.page.goto(urljoin(self.page.url, href), wait_until="domcontentloaded")
            return True
        return False

    def open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.bring_to_front()
        self.wait(2)

    def change_volume(self, delta: float, min_duration: float) -> float | None:
        fr, _ = self._video_frame(min_duration)
        return fr.evaluate(JS_VOLUME, [delta, min_duration]) if fr else None

    def toggle_mute(self, min_duration: float) -> bool | None:
        fr, _ = self._video_frame(min_duration)
        return fr.evaluate(JS_MUTE, min_duration) if fr else None

    def list_servers(self, profile: SiteProfile) -> list[Server]:
        out: list[Server] = []
        for sel in dict.fromkeys(s.selector for s in profile.servers if s.selector):
            try:
                texts = self.page.locator(sel).filter(visible=True).all_inner_texts()
            except Exception:
                continue
            for t in texts:
                name = re.sub(r"^\W+", "", " ".join(t.split()))  # quita emojis/iconos del inicio
                if name and all(o.name != name for o in out):
                    out.append(Server(name, sel))
        return out[:20]

    def select_language(self, profile: SiteProfile) -> bool:
        lang = profile.preferred_language.strip()
        if not (lang and profile.language_selector):
            return False
        try:
            tab = self.page.locator(profile.language_selector, has_text=re.compile(re.escape(lang), re.I)).first
            if not tab.count():
                return False
            if "active" not in (tab.get_attribute("class") or ""):
                self._click(tab)
                self.wait(1)
            return True
        except Exception:
            return False

    def max_quality(self) -> str | None:
        for fr in self.page.frames:
            try:
                label = fr.evaluate(JS_MAX_QUALITY)
                if label:
                    return str(label)
            except Exception:
                pass
        return None

    def go_back(self) -> bool:
        resp = self.page.go_back(wait_until="domcontentloaded")
        self.wait(2)
        return resp is not None

    def search(self, profile: SiteProfile, query: str) -> list[SearchResult]:
        done = False
        if profile.search_input_selector:
            try:
                self.close_popups(profile)
                box = self.page.locator(profile.search_input_selector).first
                if box.count():
                    self._click(box)
                    box.fill("")
                    box.type(query, delay=random.randint(40, 90))  # escribir como persona
                    box.press("Enter")
                    self.page.wait_for_load_state("domcontentloaded")
                    done = True
            except Exception:
                done = False
        if not done and profile.search_url:
            self.page.goto(profile.search_url.format(q=quote_plus(query)), wait_until="domcontentloaded")
        self.wait(2.5)
        self.close_popups(profile)
        return self.results_here(profile)

    def results_here(self, profile: SiteProfile) -> list[SearchResult]:
        links = self.page.evaluate(JS_LINKS, profile.result_pattern)
        return [SearchResult(l["title"] or l["url"].rstrip("/").rsplit("/", 1)[-1], l["url"], l["image"])
                for l in links][:60]

    def has_element(self, selector: str) -> bool:
        try:
            return self.page.locator(selector).count() > 0  # puede estar dentro de un menu cerrado
        except Exception:
            return False

    def episodes(self, profile: SiteProfile) -> list[Episode]:
        links = self.page.evaluate(JS_LINKS, profile.episode_pattern)
        out = []
        for l in links:
            title = l["title"]
            # Boton "Siguiente → T1E2: ..." / "Anterior": quitar la palabra y la flecha
            title = re.sub(r"^(siguiente|anterior|next|previous)\b\W*", "", title, flags=re.I).strip()
            if re.match(r"(comenzar|continuar|seguir) a ver\b", title, re.I):
                continue  # boton destacado de la serie, no un capitulo de la lista
            # Etiqueta T1 E3 sacada de la URL (1x3, temporada-1/episodio-3, s01e03)
            m = (re.search(r"(\d+)x(\d+)/?$", l["url"]) or re.search(r"temporada-(\d+)/episodio-(\d+)", l["url"])
                 or re.search(r"s(\d+)-?e(\d+)", l["url"], re.I))
            label = f"T{int(m.group(1))} E{int(m.group(2))}" if m else ""
            if label and label.replace(" ", "") not in title.replace(" ", ""):
                title = f"{label} · {title}" if title else label
            key = (int(m.group(1)), int(m.group(2))) if m else (9999, len(out))
            out.append((key, Episode(title or l["url"].rstrip("/").rsplit("/", 1)[-1], l["url"], l["current"])))
        return [e for _, e in sorted(out, key=lambda x: x[0])][:300]

    def _season_items(self, profile: SiteProfile):
        if not profile.season_selector:
            return None, []
        loc = self.page.locator(profile.season_selector)
        try:
            first = loc.first
            if first.count() and first.evaluate("e => e.tagName") == "SELECT":
                return first, first.locator("option").all_inner_texts()
            return loc, loc.all_inner_texts()
        except Exception:
            return None, []

    def seasons(self, profile: SiteProfile) -> list[str]:
        _, labels = self._season_items(profile)
        return [" ".join(l.split()) for l in labels]

    def choose_season(self, profile: SiteProfile, index: int) -> None:
        loc, labels = self._season_items(profile)
        if loc is None or not labels:
            return
        if loc.first.evaluate("e => e.tagName") == "SELECT":
            loc.first.select_option(index=index)
        else:
            self._click(loc.nth(index))  # puede ser enlace a la pagina de la temporada
        try:
            self.page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        self.wait(2)

    # ---------- emergentes ----------
    def _allowed(self, profile: SiteProfile, url: str) -> bool:
        if url.startswith(("chrome:", "brave:", "devtools:")):
            return True
        host = urlparse(url).hostname or ""
        doms = set(profile.allowed_domains) | {urlparse(profile.url).hostname or ""}
        return any(host == d or host.endswith("." + d) for d in doms if d)

    def close_popups(self, profile: SiteProfile, deep: bool = True) -> int:
        closed = 0
        for p in list(self.ctx.pages):
            if p != self.page and not self._allowed(profile, p.url):
                try:
                    p.close()
                    closed += 1
                except Exception:
                    pass
        if not deep:
            if closed:
                self.page.bring_to_front()
            return closed
        for sel in profile.popup_selectors:
            try:
                loc = self.page.locator(sel)
                for i in range(min(loc.count(), 5)):
                    if loc.nth(i).is_visible():
                        loc.nth(i).click(timeout=1500)
                        closed += 1
            except Exception:
                pass
        for sel in profile.overlay_selectors:
            try:
                closed += self.page.evaluate(
                    "s => { const e=[...document.querySelectorAll(s)]; e.forEach(x=>x.remove()); return e.length; }", sel)
            except Exception:
                pass
        try:
            closed += self.page.evaluate(JS_KILL_CLICKJACK)
        except Exception:
            pass
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        return closed
