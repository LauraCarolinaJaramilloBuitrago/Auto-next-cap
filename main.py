"""Punto de entrada.

    python main.py          panel de escritorio + servidor movil
    python main.py --web    solo servidor movil (sin ventana; util en Linux sin escritorio)
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

from autonext.application.controller import AppController  # noqa: E402
from autonext.infrastructure.brave_browser import BraveBrowser  # noqa: E402
from autonext.infrastructure.credential_store import CredentialStore  # noqa: E402
from autonext.infrastructure.json_repository import JsonProfileRepository  # noqa: E402
from autonext.infrastructure.web_server import WebServer  # noqa: E402


def main():
    repo = JsonProfileRepository(os.path.join(BASE, "perfiles.json"))

    def browser_factory():
        s = repo.settings()
        return BraveBrowser(s.get("brave_path") or None, s.get("profile_dir", "brave_profile"), int(s.get("port", 9222)))

    credentials = CredentialStore(os.path.join(BASE, "credenciales.json"))  # ignorado por git
    controller = AppController(repo, browser_factory, credentials)
    s = repo.settings()
    web = WebServer(controller, os.path.join(BASE, "web", "dist"), int(s["web_port"]), s["token"])
    url = web.start()
    print(f"Control movil: {url}", flush=True)

    if "--web" in sys.argv:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            controller.stop()
        return

    from autonext.presentation.app import App
    App(controller, repo, credentials).mainloop()
    web.stop()


if __name__ == "__main__":
    main()
