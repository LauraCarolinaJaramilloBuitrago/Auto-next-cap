"""Capa de presentacion: panel de control de escritorio con customtkinter."""
from __future__ import annotations

import queue
import time
from tkinter import messagebox

import customtkinter as ctk
import qrcode

from ..application.autonext_service import fmt
from ..application.controller import AppController
from ..domain import events as ev
from ..domain.models import Server, SiteProfile, default_profile
from ..infrastructure.brave_browser import find_brave
from ..infrastructure.json_repository import JsonProfileRepository

ACCENT = "#7c3aed"
ACCENT_HOVER = "#6d28d9"
DANGER = "#dc2626"
OK = "#22c55e"
WARN = "#f59e0b"
BG_CARD = ("#ffffff", "#18181b")
BG_PANEL = ("#ececf1", "#0f0f12")
BG_SOFT = ("#e4e4e7", "#27272a")
HOVER = ("#d4d4d8", "#3f3f46")
TEXT = ("#18181b", "#fafafa")
MUTED = ("#52525b", "#a1a1aa")
LOG_COLORS = {"info": "#8b8b96", "ok": OK, "warn": WARN, "error": "#f87171"}


def small_btn(master, text, cmd, width=44, **kw):
    return ctk.CTkButton(master, text=text, width=width, height=34, fg_color=BG_SOFT, hover_color=HOVER,
                         text_color=TEXT, command=cmd, **kw)


class StatCard(ctk.CTkFrame):
    def __init__(self, master, title, value="-"):
        super().__init__(master, fg_color=BG_CARD, corner_radius=12)
        ctk.CTkLabel(self, text=title.upper(), font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=14, pady=(10, 0))
        self.value = ctk.CTkLabel(self, text=value, font=ctk.CTkFont(size=20, weight="bold"))
        self.value.pack(anchor="w", padx=14, pady=(0, 10))

    def set(self, text, color=None):
        self.value.configure(text=text, text_color=color or TEXT)


class ServerRow(ctk.CTkFrame):
    def __init__(self, master, server: Server, on_move, on_delete):
        super().__init__(master, fg_color=BG_CARD, corner_radius=10)
        self.enabled = ctk.BooleanVar(value=server.enabled)
        self.name = ctk.StringVar(value=server.name)
        self.selector = ctk.StringVar(value=server.selector)
        self.text = ctk.StringVar(value=server.text)
        self.opener = ctk.StringVar(value=server.opener)
        ctk.CTkSwitch(self, text="", variable=self.enabled, width=40,
                      progress_color=ACCENT).grid(row=0, column=0, padx=(10, 0), pady=6)
        ctk.CTkEntry(self, textvariable=self.name, width=110, placeholder_text="Nombre").grid(row=0, column=1, padx=3)
        ctk.CTkEntry(self, textvariable=self.selector, placeholder_text="Selector CSS").grid(
            row=0, column=2, padx=3, sticky="ew")
        ctk.CTkEntry(self, textvariable=self.text, width=100, placeholder_text="Texto").grid(row=0, column=3, padx=3)
        ctk.CTkEntry(self, textvariable=self.opener, placeholder_text="Abrir antes (opcional)").grid(
            row=1, column=1, columnspan=3, padx=3, pady=(0, 6), sticky="ew")
        self.health = ctk.CTkProgressBar(self, width=60, progress_color=OK)
        self.health.grid(row=0, column=4, padx=6)
        self.health.set(0.5)
        for col, (txt, cmd) in enumerate([("▲", lambda: on_move(self, -1)), ("▼", lambda: on_move(self, 1)),
                                          ("✕", lambda: on_delete(self))], start=5):
            ctk.CTkButton(self, text=txt, width=28, height=28, fg_color="transparent", hover_color=HOVER,
                          text_color=TEXT, command=cmd).grid(row=0, column=col, padx=1)
        self.columnconfigure(2, weight=1)

    def to_server(self) -> Server:
        return Server(self.name.get().strip(), self.selector.get().strip() or "button.server-btn",
                      self.text.get().strip(), self.enabled.get(), self.opener.get().strip())

    def set_health(self, score: float):
        self.health.set(score)
        self.health.configure(progress_color=OK if score >= 0.6 else WARN if score >= 0.35 else DANGER)


class App(ctk.CTk):
    def __init__(self, controller: AppController, repo: JsonProfileRepository):
        super().__init__()
        self.repo = repo
        self.ctl = controller
        self._qr_url = ""
        ctk.set_appearance_mode(self.repo.settings().get("theme", "dark"))
        self.title("AutoNext · Control de capítulos")
        self.geometry("1240x820")
        self.minsize(1040, 700)
        self.events: queue.Queue[ev.DomainEvent] = queue.Queue()
        self.ctl.subscribe(self.events.put)
        self.profile: SiteProfile = self.repo.all()[self.repo.active_name()]
        self.server_rows: list[ServerRow] = []
        self.fields: dict[str, ctk.Variable] = {}
        self._seeking = False
        self._duration = 0.0

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._sidebar()
        self._main()
        self._load(self.profile)
        self.after(150, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================= layout =================
    def _sidebar(self):
        sb = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color=BG_PANEL)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        ctk.CTkLabel(sb, text="AutoNext", font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w", padx=20, pady=(22, 0))
        ctk.CTkLabel(sb, text="Capítulos sin parar", text_color=MUTED).pack(anchor="w", padx=20)

        ctk.CTkLabel(sb, text="PERFILES", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=20, pady=(20, 4))
        self.profile_list = ctk.CTkScrollableFrame(sb, fg_color="transparent", height=150)
        self.profile_list.pack(fill="x", padx=10)
        row = ctk.CTkFrame(sb, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=6)
        ctk.CTkButton(row, text="+ Nuevo", width=95, fg_color="transparent", border_width=1, text_color=TEXT,
                      border_color=ACCENT, command=self._new_profile).pack(side="left")
        ctk.CTkButton(row, text="Borrar", width=95, fg_color="transparent", border_width=1, text_color=TEXT,
                      border_color=DANGER, hover_color="#3f1d1d", command=self._delete_profile).pack(side="right")

        # Control desde el celular
        mob = ctk.CTkFrame(sb, fg_color=BG_CARD, corner_radius=12)
        mob.pack(fill="x", padx=14, pady=(14, 0))
        ctk.CTkLabel(mob, text="📱 CONTROL MÓVIL", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=12, pady=(10, 0))
        self.lbl_mobile = ctk.CTkLabel(mob, text=self.ctl.server_url or "Servidor apagado", wraplength=200,
                                       justify="left", font=ctk.CTkFont(family="Consolas", size=12))
        self.lbl_mobile.pack(anchor="w", padx=12, pady=4)
        self.lbl_qr = ctk.CTkLabel(mob, text="")
        self.lbl_qr.pack(pady=(0, 6))
        ctk.CTkButton(mob, text="Copiar enlace", height=28, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._copy_url).pack(fill="x", padx=12, pady=(0, 10))

        night = ctk.CTkFrame(sb, fg_color="transparent")
        night.pack(fill="x", padx=20, pady=12)
        self.var_night = ctk.BooleanVar(value=ctk.get_appearance_mode().lower() == "dark")
        ctk.CTkSwitch(night, text="🌙  Modo noche", variable=self.var_night, progress_color=ACCENT,
                      command=self._toggle_theme).pack(anchor="w")

        bottom = ctk.CTkFrame(sb, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=20, pady=20)
        self.btn_start = ctk.CTkButton(bottom, text="▶  Iniciar", height=44, fg_color=ACCENT,
                                       hover_color=ACCENT_HOVER, font=ctk.CTkFont(size=15, weight="bold"),
                                       command=self._start)
        self.btn_start.pack(fill="x")
        self.btn_stop = ctk.CTkButton(bottom, text="■  Detener", height=38, fg_color=BG_SOFT, text_color=TEXT,
                                      hover_color=DANGER, state="disabled", command=self._stop)
        self.btn_stop.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(bottom, text="Guardar perfil", height=34, fg_color="transparent", border_width=1,
                      text_color=TEXT, border_color=("#a1a1aa", "#3f3f46"), command=self._save).pack(fill="x", pady=(8, 0))
        self._refresh_profile_list()

    def _main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=18, pady=16)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        # --- tarjetas en vivo ---
        cards = ctk.CTkFrame(main, fg_color="transparent")
        cards.grid(row=0, column=0, sticky="ew")
        for i in range(4):
            cards.columnconfigure(i, weight=1)
        self.card_state = StatCard(cards, "Estado", "Detenido")
        self.card_ep = StatCard(cards, "Capítulos vistos", "0")
        self.card_server = StatCard(cards, "Servidor", "-")
        self.card_left = StatCard(cards, "Faltan", "--:--")
        for i, c in enumerate([self.card_state, self.card_ep, self.card_server, self.card_left]):
            c.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))

        # --- reproductor ---
        prog = ctk.CTkFrame(main, fg_color=BG_CARD, corner_radius=12)
        prog.grid(row=1, column=0, sticky="ew", pady=10)
        prog.columnconfigure(1, weight=1)
        self.lbl_title = ctk.CTkLabel(prog, text="Nada en reproducción", anchor="w",
                                      font=ctk.CTkFont(size=15, weight="bold"))
        self.lbl_title.grid(row=0, column=0, columnspan=3, sticky="ew", padx=14, pady=(10, 0))
        self.lbl_time = ctk.CTkLabel(prog, text="00:00", width=70)
        self.lbl_time.grid(row=1, column=0, padx=(14, 4), pady=8)
        self.seek = ctk.CTkSlider(prog, from_=0, to=1, progress_color=ACCENT, button_color=ACCENT,
                                  button_hover_color=ACCENT_HOVER, command=self._on_seek_drag)
        self.seek.grid(row=1, column=1, sticky="ew")
        self.seek.set(0)
        self.seek.bind("<ButtonRelease-1>", self._on_seek_release)
        self.lbl_dur = ctk.CTkLabel(prog, text="00:00", width=70)
        self.lbl_dur.grid(row=1, column=2, padx=(4, 14))
        ctrl = ctk.CTkFrame(prog, fg_color="transparent")
        ctrl.grid(row=2, column=0, columnspan=3, pady=(0, 10))
        self.play_buttons = [
            small_btn(ctrl, "−30", lambda: self.ctl.command("seek_relative", delta=-30)),
            small_btn(ctrl, "−10", lambda: self.ctl.command("seek_relative", delta=-10)),
            ctk.CTkButton(ctrl, text="⏯", width=60, height=40, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          font=ctk.CTkFont(size=18), command=lambda: self.ctl.command("toggle_pause")),
            small_btn(ctrl, "+10", lambda: self.ctl.command("seek_relative", delta=10)),
            small_btn(ctrl, "+30", lambda: self.ctl.command("seek_relative", delta=30)),
            small_btn(ctrl, "⏭ Siguiente", lambda: self.ctl.command("skip"), width=110),
            small_btn(ctrl, "⇄ Servidor", lambda: self.ctl.command("switch_server"), width=110),
            small_btn(ctrl, "⛶ Pantalla", lambda: self.ctl.command("fullscreen"), width=100),
        ]
        for i, b in enumerate(self.play_buttons):
            b.grid(row=0, column=i, padx=4)
            b.configure(state="disabled")
        self.lbl_url = ctk.CTkLabel(prog, text="", text_color=MUTED, anchor="w")
        self.lbl_url.grid(row=3, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 8))

        # --- configuracion + registro ---
        bottom = ctk.CTkFrame(main, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(bottom, fg_color=BG_CARD, segmented_button_selected_color=ACCENT,
                                   segmented_button_selected_hover_color=ACCENT_HOVER)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        for t in ["General", "Buscar", "Servidores", "Sitio", "Navegador"]:
            self.tabs.add(t)
        self._tab_general(self.tabs.tab("General"))
        self._tab_search(self.tabs.tab("Buscar"))
        self._tab_servers(self.tabs.tab("Servidores"))
        self._tab_site(self.tabs.tab("Sitio"))
        self._tab_browser(self.tabs.tab("Navegador"))

        logf = ctk.CTkFrame(bottom, fg_color=BG_CARD, corner_radius=12)
        logf.grid(row=0, column=1, sticky="nsew")
        hdr = ctk.CTkFrame(logf, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(hdr, text="Registro", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(hdr, text="Limpiar", width=60, height=24, fg_color="transparent", text_color=TEXT,
                      command=self._log_box_clear).pack(side="right")
        self.log = ctk.CTkTextbox(logf, font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
                                  fg_color=("#fafafa", "#09090b"))
        self.log.pack(fill="both", expand=True, padx=10, pady=10)
        for k, c in LOG_COLORS.items():
            self.log.tag_config(k, foreground=c)
        self.log.configure(state="disabled")

    # ---------- helpers de formulario ----------
    def _field(self, parent, row, key, label, kind="entry", hint=""):
        ctk.CTkLabel(parent, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=10, pady=5)
        if kind == "switch":
            var = ctk.BooleanVar()
            ctk.CTkSwitch(parent, text=hint, variable=var, progress_color=ACCENT).grid(
                row=row, column=1, sticky="w", padx=10)
        else:
            var = ctk.StringVar()
            ctk.CTkEntry(parent, textvariable=var, placeholder_text=hint).grid(
                row=row, column=1, sticky="ew", padx=10)
        self.fields[key] = var
        parent.columnconfigure(1, weight=1)

    def _textbox(self, parent, row, label, height=70):
        ctk.CTkLabel(parent, text=label, anchor="w").grid(row=row, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 0))
        tb = ctk.CTkTextbox(parent, height=height, font=ctk.CTkFont(family="Consolas", size=12))
        tb.grid(row=row + 1, column=0, columnspan=2, sticky="ew", padx=10)
        return tb

    def _tab_general(self, t):
        f = ctk.CTkScrollableFrame(t, fg_color="transparent")
        f.pack(fill="both", expand=True)
        self._field(f, 0, "url", "URL del capítulo inicial")
        self._field(f, 1, "seconds_before_end", "Segundos antes del final")
        self._field(f, 2, "fullscreen", "Pantalla completa", "switch", "al empezar cada capítulo")
        self._field(f, 3, "max_quality", "Calidad más alta", "switch", "si el reproductor la ofrece")
        self._field(f, 4, "preferred_language", "Idioma preferido", hint="Latino")
        self._field(f, 5, "resume", "Continuar donde quedé", "switch", "guarda capítulo y minuto")
        self._field(f, 6, "auto_resume", "Reanudar si se pausa solo", "switch", "las pausas tuyas se respetan")
        self._field(f, 7, "episode_limit_enabled", "Límite de capítulos", "switch", "detener al llegar")
        self._field(f, 8, "episode_limit", "Cuántos capítulos")
        self.lbl_progress = ctk.CTkLabel(f, text="", text_color=MUTED, anchor="w", justify="left", wraplength=520)
        self.lbl_progress.grid(row=9, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 0))
        ctk.CTkButton(f, text="Olvidar progreso", width=140, fg_color="transparent", border_width=1,
                      text_color=TEXT, command=self._forget_progress).grid(row=10, column=0, sticky="w", padx=10, pady=8)

    def _tab_search(self, t):
        top = ctk.CTkFrame(t, fg_color="transparent")
        top.pack(fill="x")
        self.var_query = ctk.StringVar()
        e = ctk.CTkEntry(top, textvariable=self.var_query, placeholder_text="Nombre de la serie…", height=36)
        e.pack(side="left", fill="x", expand=True, padx=(4, 6))
        e.bind("<Return>", lambda _: self._search())
        ctk.CTkButton(top, text="Buscar", width=90, height=36, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._search).pack(side="left")
        small_btn(top, "↻ Capítulos", self._read_episodes, width=110).pack(side="left", padx=6)
        cols = ctk.CTkFrame(t, fg_color="transparent")
        cols.pack(fill="both", expand=True, pady=(8, 0))
        cols.columnconfigure((0, 1), weight=1)
        cols.rowconfigure(1, weight=1)
        ctk.CTkLabel(cols, text="Resultados", text_color=MUTED).grid(row=0, column=0, sticky="w", padx=6)
        ctk.CTkLabel(cols, text="Temporadas / capítulos", text_color=MUTED).grid(row=0, column=1, sticky="w", padx=6)
        self.box_results = ctk.CTkScrollableFrame(cols, fg_color="transparent")
        self.box_results.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew")
        self.box_seasons = ctk.CTkScrollableFrame(right, fg_color="transparent", height=44, orientation="horizontal")
        self.box_seasons.pack(fill="x")
        self.box_episodes = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.box_episodes.pack(fill="both", expand=True)

    def _tab_servers(self, t):
        top = ctk.CTkFrame(t, fg_color="transparent")
        top.pack(fill="x")
        self._field(top, 0, "auto_rank_servers", "Orden automático", "switch", "probar primero el más estable")
        self._field(top, 1, "server_timeout", "Tiempo máx. para arrancar (s)")
        self._field(top, 2, "stall_seconds", "Congelado por más de (s) = caído")
        self._field(top, 3, "min_video_duration", "Duración mínima del video (s)", hint="ignora anuncios")
        head = ctk.CTkFrame(t, fg_color="transparent")
        head.pack(fill="x", pady=(8, 2))
        ctk.CTkLabel(head, text="Servidores en orden de prioridad  ·  barra = salud",
                     text_color=MUTED).pack(side="left", padx=10)
        ctk.CTkButton(head, text="Reiniciar salud", width=110, height=26, fg_color="transparent", text_color=TEXT,
                      border_width=1, command=self._reset_health).pack(side="right", padx=4)
        ctk.CTkButton(head, text="+ Servidor", width=90, height=26, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self._add_server).pack(side="right", padx=4)
        self.server_box = ctk.CTkScrollableFrame(t, fg_color="transparent")
        self.server_box.pack(fill="both", expand=True)

    def _tab_site(self, t):
        f = ctk.CTkScrollableFrame(t, fg_color="transparent")
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        self._field(f, 0, "next_selector", "Botón Siguiente (CSS)", hint="separar con coma")
        self._field(f, 1, "next_text", "Texto botón Siguiente", hint="respaldo")
        self._field(f, 2, "search_input_selector", "Caja de búsqueda (CSS)", hint="se le da clic y se escribe")
        self._field(f, 3, "search_url", "URL de búsqueda", hint="respaldo, usa {q}")
        self._field(f, 4, "result_pattern", "Patrón de resultados (regex)")
        self._field(f, 5, "episode_pattern", "Patrón de capítulos (regex)")
        self._field(f, 6, "season_selector", "Temporadas (CSS)", hint="<select> o pestañas")
        self._field(f, 7, "language_selector", "Pestañas de idioma (CSS)", hint="se pulsa la del idioma preferido")
        self._field(f, 8, "allowed_domains", "Dominios permitidos", hint="otras pestañas se cierran")
        self.tb_play = self._textbox(f, 9, "Botones de Play (uno por línea, se buscan en todos los iframes)")
        self.tb_popup = self._textbox(f, 11, "Botones para cerrar emergentes (uno por línea)")
        self.tb_overlay = self._textbox(f, 13, "Overlays que se eliminan (uno por línea)", 50)

    def _tab_browser(self, t):
        f = ctk.CTkFrame(t, fg_color="transparent")
        f.pack(fill="both", expand=True)
        s = self.repo.settings()
        self._field(f, 0, "brave_path", "Ruta de Brave")
        self._field(f, 1, "port", "Puerto de control (CDP)")
        self._field(f, 2, "profile_dir", "Carpeta del perfil")
        self._field(f, 3, "web_port", "Puerto del servidor móvil")
        self.fields["brave_path"].set(s.get("brave_path") or find_brave())
        self.fields["port"].set(str(s.get("port", 9222)))
        self.fields["profile_dir"].set(s.get("profile_dir", "brave_profile"))
        self.fields["web_port"].set(str(s.get("web_port", 8765)))
        ctk.CTkLabel(f, text="Brave se abre con su propio perfil y puerto de control.\n"
                             "El puerto del servidor móvil se aplica al reiniciar la app.",
                     text_color=MUTED, justify="left").grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=12)

    # ================= perfiles =================
    def _refresh_profile_list(self):
        for w in self.profile_list.winfo_children():
            w.destroy()
        for name in self.repo.all():
            active = name == self.profile.name
            ctk.CTkButton(self.profile_list, text=name, anchor="w", height=34,
                          fg_color=ACCENT if active else "transparent",
                          hover_color=ACCENT_HOVER if active else HOVER,
                          text_color="#ffffff" if active else TEXT,
                          command=lambda n=name: self._switch_profile(n)).pack(fill="x", pady=2)

    TEXT_FIELDS = ["url", "seconds_before_end", "next_selector", "next_text", "server_timeout", "stall_seconds",
                   "min_video_duration", "search_input_selector", "search_url", "result_pattern",
                   "episode_pattern", "season_selector", "episode_limit", "preferred_language", "language_selector"]
    BOOL_FIELDS = ["fullscreen", "max_quality", "auto_rank_servers", "resume", "auto_resume", "episode_limit_enabled"]

    def _load(self, p: SiteProfile):
        self.profile = p
        for k in self.TEXT_FIELDS:
            self.fields[k].set(str(getattr(p, k)))
        for k in self.BOOL_FIELDS:
            self.fields[k].set(getattr(p, k))
        self.fields["allowed_domains"].set(", ".join(p.allowed_domains))
        for tb, vals in [(self.tb_play, p.play_selectors), (self.tb_popup, p.popup_selectors),
                         (self.tb_overlay, p.overlay_selectors)]:
            tb.delete("1.0", "end")
            tb.insert("1.0", "\n".join(vals))
        for r in self.server_rows:
            r.destroy()
        self.server_rows = []
        for s in p.servers:
            self._add_server_row(s)
        self._update_health_bars()
        self._show_progress()

    def _show_progress(self):
        pr = self.repo.progress(self.profile.name)
        self.lbl_progress.configure(
            text=f"Último visto: {pr.title or pr.url}\nMinuto {fmt(pr.position)}" if pr else "Sin progreso guardado")

    def _collect(self) -> SiteProfile:
        def num(k, d):
            try:
                return float(self.fields[k].get())
            except ValueError:
                return d
        lines = lambda tb: [l.strip() for l in tb.get("1.0", "end").splitlines() if l.strip()]
        txt = lambda k: self.fields[k].get().strip()
        return SiteProfile(
            name=self.profile.name,
            url=txt("url"),
            seconds_before_end=num("seconds_before_end", 10),
            next_selector=txt("next_selector"),
            next_text=txt("next_text"),
            fullscreen=self.fields["fullscreen"].get(),
            max_quality=self.fields["max_quality"].get(),
            preferred_language=txt("preferred_language"),
            language_selector=txt("language_selector"),
            auto_rank_servers=self.fields["auto_rank_servers"].get(),
            server_timeout=num("server_timeout", 50),
            stall_seconds=num("stall_seconds", 20),
            min_video_duration=num("min_video_duration", 120),
            search_input_selector=txt("search_input_selector"),
            search_url=txt("search_url"),
            result_pattern=txt("result_pattern"),
            episode_pattern=txt("episode_pattern"),
            season_selector=txt("season_selector"),
            episode_limit_enabled=self.fields["episode_limit_enabled"].get(),
            episode_limit=int(num("episode_limit", 3)),
            resume=self.fields["resume"].get(),
            auto_resume=self.fields["auto_resume"].get(),
            allowed_domains=[d.strip() for d in txt("allowed_domains").split(",") if d.strip()],
            play_selectors=lines(self.tb_play),
            popup_selectors=lines(self.tb_popup),
            overlay_selectors=lines(self.tb_overlay),
            servers=[r.to_server() for r in self.server_rows if r.name.get().strip()],
            health=self.profile.health,
        )

    def _save(self, quiet=False):
        self.profile = self._collect()
        self.repo.save(self.profile)
        if self.ctl.running:  # el limite se aplica en caliente
            self.ctl.set_limit(self.profile.episode_limit_enabled, self.profile.episode_limit)
        self.repo.save_settings({"brave_path": self.fields["brave_path"].get().strip(),
                                 "port": int(self.fields["port"].get() or 9222),
                                 "profile_dir": self.fields["profile_dir"].get().strip() or "brave_profile",
                                 "web_port": int(self.fields["web_port"].get() or 8765)})
        if not quiet:
            self._write(ev.ok(f"Perfil '{self.profile.name}' guardado"))

    def _switch_profile(self, name):
        if self.ctl.running:
            return
        self._save(quiet=True)
        self._load(self.repo.all()[name])
        self.repo.save(self.profile)
        self._refresh_profile_list()

    def _new_profile(self):
        dlg = ctk.CTkInputDialog(text="Nombre del nuevo perfil (sitio):", title="Nuevo perfil")
        name = (dlg.get_input() or "").strip()
        if not name or name in self.repo.all():
            return
        self._save(quiet=True)
        p = default_profile()
        p.name, p.url, p.servers, p.allowed_domains = name, "https://", [], []
        p.search_input_selector = p.search_url = p.season_selector = ""
        self.repo.save(p)
        self._load(p)
        self._refresh_profile_list()

    def _delete_profile(self):
        if len(self.repo.all()) <= 1 or self.ctl.running:
            return
        if messagebox.askyesno("Borrar perfil", f"¿Borrar el perfil '{self.profile.name}'?"):
            self.repo.delete(self.profile.name)
            self._load(self.repo.all()[self.repo.active_name()])
            self._refresh_profile_list()

    def _forget_progress(self):
        self.repo.clear_progress(self.profile.name)
        self._show_progress()

    # ================= servidores =================
    def _add_server_row(self, s: Server):
        row = ServerRow(self.server_box, s, self._move_server, self._delete_server)
        row.pack(fill="x", pady=3, padx=2)
        self.server_rows.append(row)

    def _add_server(self):
        self._add_server_row(Server(f"Servidor {len(self.server_rows) + 1}"))

    def _move_server(self, row, d):
        i = self.server_rows.index(row)
        j = i + d
        if 0 <= j < len(self.server_rows):
            self.server_rows[i], self.server_rows[j] = self.server_rows[j], self.server_rows[i]
            for r in self.server_rows:
                r.pack_forget()
            for r in self.server_rows:
                r.pack(fill="x", pady=3, padx=2)

    def _delete_server(self, row):
        self.server_rows.remove(row)
        row.destroy()

    def _reset_health(self):
        self.profile.reset_health()
        self.repo.save_health(self.profile)
        if self.ctl.service:
            self.ctl.service.profile.reset_health()
        self._update_health_bars()
        self._write(ev.info("Salud de servidores reiniciada"))

    def _update_health_bars(self, profile: SiteProfile | None = None):
        p = profile or self.profile
        for r in self.server_rows:
            h = p.health.get(r.name.get())
            r.set_health(h.score if h else 0.5)

    # ================= busqueda =================
    def _search(self):
        q = self.var_query.get().strip()
        if q:
            self._save(quiet=True)
            self.ctl.command("search", query=q)

    def _read_episodes(self):
        self.ctl.command("episodes")
        self.ctl.command("seasons")

    def _fill(self, box, items, make, horizontal=False):
        for w in box.winfo_children():
            w.destroy()
        for it in items:
            w = make(box, it)
            if horizontal:
                w.pack(side="left", padx=2)
            else:
                w.pack(fill="x", pady=2, padx=2)

    def _show_results(self, results):
        self._fill(self.box_results, results, lambda b, r: ctk.CTkButton(
            b, text=r["title"][:60], anchor="w", height=32, fg_color=BG_SOFT, hover_color=HOVER, text_color=TEXT,
            command=lambda u=r["url"]: self.ctl.command("open", url=u)))

    def _show_episodes(self, eps):
        cur = self.ctl.status.get("url", "")
        self._fill(self.box_episodes, eps, lambda b, e: ctk.CTkButton(
            b, text=e["title"][:60], anchor="w", height=30,
            fg_color=ACCENT if e["url"] == cur else BG_SOFT, hover_color=HOVER,
            text_color="#ffffff" if e["url"] == cur else TEXT,
            command=lambda u=e["url"]: self.ctl.command("open", url=u)))

    def _show_seasons(self, seasons):
        self._fill(self.box_seasons, list(enumerate(seasons)), lambda b, s: ctk.CTkButton(
            b, text=s[1][:22], width=40, height=28, fg_color=BG_SOFT, hover_color=HOVER, text_color=TEXT,
            command=lambda i=s[0]: self.ctl.command("season", index=i)), horizontal=True)

    # ================= motor =================
    def _start(self):
        self._save(quiet=True)
        self.ctl.start(self.profile.name)
        self._set_running(True)
        self.card_state.set("Iniciando", WARN)

    def _stop(self):
        self.ctl.stop()
        self.card_state.set("Deteniendo", WARN)

    def _set_running(self, on: bool):
        self.btn_start.configure(state="disabled" if on else "normal")
        self.btn_stop.configure(state="normal" if on else "disabled")
        for b in self.play_buttons:
            b.configure(state="normal" if on else "disabled")

    def _finished(self):
        self.profile.health = self.repo.all()[self.profile.name].health
        self._set_running(False)
        self.card_state.set("Detenido", MUTED)
        self._show_progress()

    def _pump(self):
        try:
            while True:
                e = self.events.get_nowait()
                if e.kind == "status":
                    self._show_status(e.data)
                    self._set_running(True)
                elif e.kind == "results":
                    self._show_results(e.data["results"])
                    self.tabs.set("Buscar")
                elif e.kind == "episodes":
                    self._show_episodes(e.data["episodes"])
                elif e.kind == "seasons":
                    self._show_seasons(e.data["seasons"])
                if e.kind != "status" and e.message:
                    self._write(e)
                if e.data.get("finished"):
                    self._finished()
        except queue.Empty:
            pass
        if self.ctl.server_url and self._qr_url != self.ctl.server_url:
            self._qr_url = self.ctl.server_url
            self.lbl_mobile.configure(text=self._qr_url)
            self._draw_qr(self._qr_url)
        self.after(150, self._pump)

    def _show_status(self, d):
        pos, dur = d["position"], d["duration"]
        self._duration = dur
        if d.get("mode") == "browsing":
            self.card_state.set("Navegando", WARN)
        elif dur:
            self.card_state.set("En pausa" if d["paused"] else "Reproduciendo", WARN if d["paused"] else OK)
        else:
            self.card_state.set("Buscando video", WARN)
        if dur and not self._seeking:
            self.seek.configure(to=dur)
            self.seek.set(pos)
            self.lbl_time.configure(text=fmt(pos))
        self.lbl_dur.configure(text=fmt(dur))
        left = dur - pos
        self.card_left.set(fmt(left) if dur else "--:--",
                           DANGER if dur and left <= self.profile.seconds_before_end + 20 else None)
        self.card_ep.set(str(d["episode"]) + (f" / {d['limit']}" if d.get("limit_enabled") else ""))
        self.card_server.set(d["server"])
        self.lbl_title.configure(text=d.get("title") or "Cargando…")
        self.lbl_url.configure(text=d["url"])
        if self.ctl.service:
            self._update_health_bars(self.ctl.service.profile)

    def _on_seek_drag(self, value):
        self._seeking = True
        self.lbl_time.configure(text=fmt(value))

    def _on_seek_release(self, _):
        if self._seeking and self._duration:
            self.ctl.command("seek", position=float(self.seek.get()))
        self._seeking = False

    def _toggle_theme(self):
        mode = "dark" if self.var_night.get() else "light"
        ctk.set_appearance_mode(mode)
        self.repo.save_settings({"theme": mode})

    def _copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(self.ctl.server_url)
        self._write(ev.ok("Enlace copiado. Ábrelo en el celular (misma red Wi-Fi)"))

    def _draw_qr(self, url: str):
        img = qrcode.make(url, box_size=6, border=2).get_image().convert("RGB")
        self._qr_img = ctk.CTkImage(light_image=img, dark_image=img, size=(170, 170))
        self.lbl_qr.configure(image=self._qr_img)

    def _write(self, e: ev.DomainEvent):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S  ", time.localtime(e.at)), "info")
        self.log.insert("end", e.message + "\n", e.kind if e.kind in LOG_COLORS else "info")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_box_clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self):
        self.ctl.stop()
        self.destroy()
