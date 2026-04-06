from __future__ import annotations

import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, StringVar, Tk, messagebox, ttk

from dotenv import dotenv_values

from linkedin_agent.automation.browser import BrowserSession
from linkedin_agent.config.settings import load_settings

ROOT = Path(__file__).resolve().parent
APP_URL = "http://localhost:8501"


class LauncherApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("LinkedIn Growth Agent Launcher")
        self.root.geometry("760x520")
        self.root.minsize(700, 480)

        self.streamlit_process: subprocess.Popen | None = None
        self.browser_session: BrowserSession | None = None
        self.settings = None

        self.status_var = StringVar(value="Pronto.")
        self.streamlit_var = StringVar(value="App web non avviata.")
        self.linkedin_var = StringVar(value="Sessione LinkedIn non verificata.")
        self.gemini_var = StringVar(value="Configurazione Gemini non verificata.")

        self._build_ui()
        self.refresh_status()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=BOTH, expand=True)

        title = ttk.Label(frame, text="Avvio guidato LinkedIn Growth Agent", font=("Helvetica", 18, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            frame,
            text="Usa questi pulsanti per avviare l'app, fare login su LinkedIn e controllare che tutto sia pronto.",
            wraplength=700,
        )
        subtitle.pack(anchor="w", pady=(6, 14))

        status_card = ttk.LabelFrame(frame, text="Stato")
        status_card.pack(fill="x", pady=(0, 14))

        ttk.Label(status_card, textvariable=self.streamlit_var, wraplength=680).pack(anchor="w", padx=12, pady=(10, 4))
        ttk.Label(status_card, textvariable=self.linkedin_var, wraplength=680).pack(anchor="w", padx=12, pady=4)
        ttk.Label(status_card, textvariable=self.gemini_var, wraplength=680).pack(anchor="w", padx=12, pady=(4, 10))

        actions = ttk.LabelFrame(frame, text="Azioni")
        actions.pack(fill="x", pady=(0, 14))

        row1 = ttk.Frame(actions)
        row1.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Button(row1, text="1. Avvia app web", command=self.start_streamlit).pack(side=LEFT, padx=(0, 8))
        ttk.Button(row1, text="2. Apri app nel browser", command=self.open_app_in_browser).pack(side=LEFT, padx=8)
        ttk.Button(row1, text="Ferma app web", command=self.stop_streamlit).pack(side=LEFT, padx=8)

        row2 = ttk.Frame(actions)
        row2.pack(fill="x", padx=10, pady=6)
        ttk.Button(row2, text="3. Apri login LinkedIn", command=self.open_linkedin_login).pack(side=LEFT, padx=(0, 8))
        ttk.Button(row2, text="4. Ho finito il login, salva sessione", command=self.finalize_linkedin_login).pack(side=LEFT, padx=8)

        row3 = ttk.Frame(actions)
        row3.pack(fill="x", padx=10, pady=(6, 10))
        ttk.Button(row3, text="Aggiorna stato", command=self.refresh_status).pack(side=LEFT, padx=(0, 8))
        ttk.Button(row3, text="Apri cartella progetto", command=self.open_project_folder).pack(side=LEFT, padx=8)

        help_box = ttk.LabelFrame(frame, text="Istruzioni rapide")
        help_box.pack(fill="x", pady=(0, 14))
        help_text = (
            "1. Premi 'Avvia app web'.\n"
            "2. Premi 'Apri app nel browser'.\n"
            "3. Se LinkedIn non e' collegato, premi 'Apri login LinkedIn'.\n"
            "4. Fai login nel browser che si apre e poi premi 'Ho finito il login, salva sessione'.\n"
            "5. Torna nell'app web e genera il piano giornaliero."
        )
        ttk.Label(help_box, text=help_text, justify=LEFT, wraplength=680).pack(anchor="w", padx=12, pady=10)

        log_box = ttk.LabelFrame(frame, text="Messaggi")
        log_box.pack(fill=BOTH, expand=True)
        self.log = ttk.Treeview(log_box, columns=("msg",), show="tree", height=8)
        self.log.pack(fill=BOTH, expand=True, padx=10, pady=10)

        footer = ttk.Label(frame, textvariable=self.status_var)
        footer.pack(anchor="w")

    def add_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log.insert("", END, text=f"[{timestamp}] {message}")
        self.log.yview_moveto(1)
        self.status_var.set(message)

    def start_streamlit(self) -> None:
        if self.streamlit_process and self.streamlit_process.poll() is None:
            self.add_log("L'app web e' gia' in esecuzione.")
            return

        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "linkedin_agent/scripts/app.py",
        ]
        try:
            self.streamlit_process = subprocess.Popen(
                cmd,
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.add_log("Avvio dell'app web in corso...")
            self.root.after(2500, self.refresh_status)
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile avviare l'app web:\n{e}")

    def stop_streamlit(self) -> None:
        if self.streamlit_process and self.streamlit_process.poll() is None:
            self.streamlit_process.terminate()
            self.streamlit_process = None
            self.add_log("App web fermata.")
        else:
            self.add_log("Nessuna app web in esecuzione.")
        self.refresh_status()

    def open_app_in_browser(self) -> None:
        webbrowser.open(APP_URL)
        self.add_log("Apertura dell'app nel browser.")

    def open_linkedin_login(self) -> None:
        if self.browser_session is not None:
            self.add_log("Una sessione browser LinkedIn e' gia' aperta.")
            return

        def worker() -> None:
            try:
                settings = load_settings()
                session = BrowserSession(settings)
                session.open_manual_login()
                self.browser_session = session
                self.root.after(0, lambda: self.add_log("Browser LinkedIn aperto. Completa il login e poi premi 'salva sessione'."))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Errore", f"Impossibile aprire LinkedIn:\n{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def finalize_linkedin_login(self) -> None:
        if not self.browser_session:
            self.add_log("Nessuna sessione LinkedIn aperta da salvare.")
            return

        try:
            saved = self.browser_session.finalize_manual_login()
            self.browser_session.stop()
            self.browser_session = None
            if saved:
                self.add_log("Sessione LinkedIn salvata correttamente.")
            else:
                self.add_log("Login non rilevato. Controlla di essere sulla home/feed di LinkedIn e riprova.")
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile salvare la sessione LinkedIn:\n{e}")
        finally:
            self.refresh_status()

    def open_project_folder(self) -> None:
        try:
            subprocess.Popen(["open", str(ROOT)])
            self.add_log("Cartella progetto aperta nel Finder.")
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile aprire la cartella:\n{e}")

    def refresh_status(self) -> None:
        self._refresh_gemini_status()
        self._refresh_streamlit_status()
        self._refresh_linkedin_status()

    def _refresh_gemini_status(self) -> None:
        env = dotenv_values(ROOT / ".env")
        model = env.get("GEMINI_MODEL") or "gemini-2.0-flash-lite"
        has_key = bool(env.get("GEMINI_API_KEY"))
        if has_key:
            self.gemini_var.set(f"Gemini configurato. Modello: {model}")
        else:
            self.gemini_var.set("Gemini non configurato: manca GEMINI_API_KEY nel file .env")

    def _refresh_streamlit_status(self) -> None:
        if self.streamlit_process and self.streamlit_process.poll() is None:
            self.streamlit_var.set(f"App web avviata. Aprila su {APP_URL}")
        else:
            self.streamlit_var.set("App web non avviata.")

    def _refresh_linkedin_status(self) -> None:
        try:
            settings = load_settings()
            ok, detail = BrowserSession.probe_saved_session(settings)
            if ok:
                self.linkedin_var.set(f"LinkedIn collegato via browser. {detail}")
            else:
                self.linkedin_var.set(f"LinkedIn non ancora collegato. {detail}")
        except Exception as e:
            self.linkedin_var.set(f"Impossibile verificare LinkedIn: {e}")

    def on_close(self) -> None:
        if self.browser_session:
            try:
                self.browser_session.stop()
            except Exception:
                pass
        self.root.destroy()


def main() -> None:
    root = Tk()
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    app = LauncherApp(root)
    app.add_log("Launcher pronto.")
    root.mainloop()


if __name__ == "__main__":
    main()
