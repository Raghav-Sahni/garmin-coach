"""garmin-coach desktop app: paste a trainer's plan -> preview -> send to your Garmin watch.

Built with tkinter (part of Python), so it can be packaged as a single .exe.
Run from source with:  python -m garmin_coach.app
"""

import queue
import subprocess
import sys
import shutil
import threading
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, data
from .profile import Profile
from .textplan import describe, parse_text
from .workouts import load_ledger, push_specs, remove_specs, spec_hash

APP_NAME = "Garmin Coach"
IS_MAC = sys.platform == "darwin"
UI_FONT = "Helvetica Neue" if IS_MAC else "Segoe UI"
MONO_FONT = "Menlo" if IS_MAC else "Consolas"
EXAMPLE = """Thu - Threshold run
- Warm-up: 12 min easy jog, drills, 4 x 20 sec strides
- 4 x 6 min @ T-pace, 1 min jog
- Cool-down 8 min

Sat - Upper body
- DB bench press 4 x 8 @ 20kg rest 90s
- Chin-ups 4 x 6
- Superset: face pulls 3 x 15 / curls 3 x 10
- Plank 3 x 45s
"""
HELP_URL = "https://github.com/Raghav-Sahni/garmin-coach/blob/main/TRAINER_GUIDE.md"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {__version__}")
        self.geometry("920x680")
        self.minsize(760, 560)
        self.profile = Profile("default")
        self.api = None
        self.jobs = queue.Queue()
        self.plan = None
        self.inbox_on = False
        self.inbox_folder = tk.StringVar(value=self.profile.config().get("inbox_folder", ""))

        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TButton", font=(UI_FONT, 11, "bold"), padding=(14, 8))
        style.configure("H.TLabel", font=(UI_FONT, 13, "bold"))
        style.configure("Status.TLabel", font=(UI_FONT, 10))

        top = ttk.Frame(self, padding=(12, 10, 12, 0))
        top.pack(fill="x")
        self.account_lbl = ttk.Label(top, text="", style="Status.TLabel")
        self.account_lbl.pack(side="left")
        ttk.Button(top, text="Help", command=self.show_help).pack(side="right")
        self.login_btn = ttk.Button(top, text="Log in to Garmin", command=self.login_dialog)
        self.login_btn.pack(side="right", padx=6)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=10)
        nb.add(self.build_send_tab(nb), text="  Send workouts  ")
        nb.add(self.build_folder_tab(nb), text="  Trainer folder  ")
        nb.add(self.build_report_tab(nb), text="  My training  ")

        self.status = ttk.Label(self, text="Ready.", anchor="w", style="Status.TLabel", padding=(12, 0, 12, 8))
        self.status.pack(fill="x")
        self.refresh_account()
        self.after(150, self.poll_jobs)
        self.after(300, self.preview)

    # ------------------------------------------------------------ background work
    def run_bg(self, label, fn, done=None):
        """Run fn() off the UI thread; call done(result) back on the UI thread."""
        self.set_status(label + " ...")

        def worker():
            try:
                res = fn()
                self.jobs.put((done, res, None))
            except Exception as e:  # noqa: BLE001
                self.jobs.put((done, None, e))
        threading.Thread(target=worker, daemon=True).start()

    def poll_jobs(self):
        try:
            while True:
                done, res, err = self.jobs.get_nowait()
                if err:
                    self.set_status("Something went wrong.")
                    messagebox.showerror(APP_NAME, friendly_error(err))
                elif done:
                    done(res)
        except queue.Empty:
            pass
        self.after(150, self.poll_jobs)

    def set_status(self, text):
        self.status.config(text=text)

    def ui(self, fn, *a):
        """Schedule fn on the UI thread (for use from worker threads)."""
        self.jobs.put((lambda _: fn(*a), None, None))

    # ------------------------------------------------------------ account
    def logged_in(self):
        t = self.profile.tokens
        return t.is_dir() and any(t.iterdir())

    def refresh_account(self):
        cfg = self.profile.config()
        if self.logged_in():
            who = cfg.get("account_name") or "your Garmin account"
            thr = (f"   •   Threshold {cfg['threshold_pace']}/km @ {cfg['threshold_hr']} bpm"
                   if cfg.get("threshold_pace") and cfg.get("threshold_hr") else "")
            self.account_lbl.config(text=f"✔ Connected to {who}{thr}")
            self.login_btn.config(text="Switch account")
        else:
            self.account_lbl.config(text="✖ Not connected to Garmin yet")
            self.login_btn.config(text="Log in to Garmin")

    def get_api(self):
        """Called from worker threads."""
        if self.api is None:
            self.api = self.profile.client(interactive=False)
        return self.api

    def login_dialog(self):
        dlg = LoginDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        email, password, remember = dlg.result

        def ask_mfa():
            box = {}
            ev = threading.Event()

            def ask():
                box["code"] = simpledialog.askstring(APP_NAME, "Garmin sent you a security code.\nEnter it here:",
                                                     parent=self)
                ev.set()
            self.ui(ask)
            ev.wait()
            return (box.get("code") or "").strip()

        def work():
            from garminconnect import Garmin
            if self.profile.tokens.exists():
                shutil.rmtree(self.profile.tokens, ignore_errors=True)
            api = Garmin(email=email, password=password, prompt_mfa=ask_mfa)
            api.login(str(self.profile.tokens))
            if remember:
                self.profile.env_file.write_text(f"email={email}\npassword={password}\n")
            elif self.profile.env_file.exists():
                self.profile.env_file.unlink()
            cfg = self.profile.config()
            cfg["account_name"] = api.full_name or api.display_name or email
            self.profile.save_config(cfg)
            try:
                data.thresholds(self.profile, api, quiet=True)
            except Exception:  # noqa: BLE001
                pass
            self.api = api
            return cfg["account_name"]

        def done(name):
            self.refresh_account()
            self.set_status(f"Connected to {name}.")
            self.preview()
            messagebox.showinfo(APP_NAME, f"Connected to {name}.\n\nYou stay logged in on this computer.")
        self.run_bg("Logging in to Garmin", work, done)

    # ------------------------------------------------------------ tab 1: send
    def build_send_tab(self, nb):
        f = ttk.Frame(nb, padding=10)
        ttk.Label(f, text="1.  Paste your trainer's plan (or open a file)", style="H.TLabel").grid(
            row=0, column=0, sticky="w")
        bar = ttk.Frame(f)
        bar.grid(row=0, column=1, sticky="e")
        ttk.Button(bar, text="Open file…", command=self.open_file).pack(side="left", padx=3)
        ttk.Button(bar, text="Show example", command=lambda: self.set_text(EXAMPLE)).pack(side="left", padx=3)
        ttk.Button(bar, text="Clear", command=lambda: self.set_text("")).pack(side="left", padx=3)

        self.text = tk.Text(f, wrap="word", font=(MONO_FONT, 11), undo=True, height=12)
        self.text.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(6, 10))
        self.text.insert("1.0", EXAMPLE)
        self.text.bind("<<Modified>>", self.on_text_change)

        ttk.Label(f, text="2.  Check what will go on your watch", style="H.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w")
        self.preview_box = tk.Text(f, wrap="none", font=(MONO_FONT, 10), height=12, state="disabled",
                                   background="#f6f7f9", relief="flat")
        self.preview_box.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(6, 10))
        self.preview_box.tag_config("warn", foreground="#b45309")
        self.preview_box.tag_config("head", font=(MONO_FONT, 10, "bold"))

        bottom = ttk.Frame(f)
        bottom.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Label(bottom, text="3.", style="H.TLabel").pack(side="left")
        self.send_btn = ttk.Button(bottom, text="Send to my watch", style="Big.TButton", command=self.send)
        self.send_btn.pack(side="left", padx=8)
        ttk.Button(bottom, text="Undo (remove these from Garmin)", command=self.undo).pack(side="left", padx=8)
        self.summary = ttk.Label(bottom, text="", style="Status.TLabel")
        self.summary.pack(side="left", padx=8)

        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        f.rowconfigure(3, weight=1)
        return f

    def set_text(self, s):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", s)
        self.preview()

    def open_file(self):
        p = filedialog.askopenfilename(title="Open a workout plan",
                                       filetypes=[("Text files", "*.txt *.md"), ("All files", "*.*")])
        if p:
            self.set_text(Path(p).read_text(encoding="utf-8-sig", errors="replace"))

    def on_text_change(self, _e=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if getattr(self, "_pending", None):
                self.after_cancel(self._pending)
            self._pending = self.after(500, self.preview)

    def preview(self):
        txt = self.text.get("1.0", "end")
        try:
            self.plan = parse_text(txt, self.profile.config())
            out = describe(self.plan).strip() or "Nothing recognised yet. Each day should start with a line like 'Mon - Legs'."
        except Exception as e:  # noqa: BLE001
            self.plan = None
            out = f"Couldn't read this: {e}"
        box = self.preview_box
        box.config(state="normal")
        box.delete("1.0", "end")
        for line in out.splitlines():
            tag = "warn" if "⚠" in line else ("head" if line and not line.startswith(" ") else None)
            box.insert("end", line + "\n", tag)
        box.config(state="disabled")
        n = len(self.plan.specs) if self.plan else 0
        warn = sum("check it" in w for w in self.plan.warnings) if self.plan else 0
        self.summary.config(text=f"{n} workout(s) ready" + (f"  •  {warn} name(s) to check" if warn else ""))

    def send(self):
        if not self.plan or not self.plan.specs:
            messagebox.showinfo(APP_NAME, "There's nothing to send yet. Paste a plan first.")
            return
        if not self.logged_in():
            messagebox.showinfo(APP_NAME, "First connect your Garmin account (button at the top right).")
            return
        unsure = [w for w in self.plan.warnings if "check it" in w]
        if unsure and not messagebox.askyesno(
                APP_NAME, "Some exercise names were a guess:\n\n" + "\n".join(unsure[:8]) +
                "\n\nSend anyway? (You can fix the wording and preview again.)"):
            return
        specs = self.plan.specs
        lines = []

        def work():
            push_specs(self.profile, self.get_api(), specs, source="app", log=lambda m: lines.append(m.strip()))
            return lines

        def done(lines):
            self.set_status("Sent. Open the Garmin Connect app to sync your watch.")
            messagebox.showinfo(APP_NAME, "\n".join(lines) +
                                "\n\nNow open the Garmin Connect app on your phone to sync your watch.")
        self.run_bg("Sending to Garmin", work, done)

    def undo(self):
        if not self.plan or not self.plan.specs:
            return
        ledger = load_ledger(self.profile)
        found = [w for w in self.plan.specs if spec_hash(w) in ledger]
        if not found:
            messagebox.showinfo(APP_NAME, "None of these workouts have been sent, so there's nothing to remove.")
            return
        if not messagebox.askyesno(APP_NAME, f"Remove {len(found)} workout(s) shown here from your Garmin calendar?"):
            return
        lines = []

        def work():
            remove_specs(self.profile, self.get_api(), found, log=lambda m: lines.append(m.strip()))
            return lines
        self.run_bg("Removing from Garmin", work,
                    lambda l: (self.set_status("Removed."), messagebox.showinfo(APP_NAME, "\n".join(l))))

    # ------------------------------------------------------------ tab 2: trainer folder
    def build_folder_tab(self, nb):
        f = ttk.Frame(nb, padding=16)
        ttk.Label(f, text="Let your trainer send workouts without your password", style="H.TLabel").pack(anchor="w")
        ttk.Label(f, wraplength=760, justify="left", text=(
            "1. Make a folder you both can open, for example a shared Google Drive or Dropbox folder.\n"
            "2. Choose it below and press Start.\n"
            "3. Your trainer saves plans as .txt files in that folder. While this app is open, it checks every "
            "10 minutes and sends new plans to your watch.\n\n"
            "Sent files move into a 'pushed' subfolder. If a plan has an unclear exercise name, it moves to "
            "'failed' with a note saying what to fix, and nothing is sent. A 'log.txt' in the folder lists what happened.")
        ).pack(anchor="w", pady=(6, 14))
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.inbox_folder).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Choose folder…", command=self.choose_folder).pack(side="left", padx=6)
        row2 = ttk.Frame(f)
        row2.pack(fill="x", pady=10)
        self.inbox_btn = ttk.Button(row2, text="Start", style="Big.TButton", command=self.toggle_inbox)
        self.inbox_btn.pack(side="left")
        ttk.Button(row2, text="Check now", command=self.check_inbox).pack(side="left", padx=8)
        ttk.Button(row2, text="Open folder", command=self.open_inbox_folder).pack(side="left")
        self.inbox_log = tk.Text(f, height=14, font=(MONO_FONT, 10), state="disabled", background="#f6f7f9",
                                 relief="flat")
        self.inbox_log.pack(fill="both", expand=True, pady=(6, 0))
        return f

    def choose_folder(self):
        p = filedialog.askdirectory(title="Choose the shared trainer folder")
        if p:
            self.inbox_folder.set(p)
            cfg = self.profile.config()
            cfg["inbox_folder"] = p
            self.profile.save_config(cfg)

    def open_inbox_folder(self):
        p = self.inbox_folder.get()
        if p and Path(p).is_dir():
            if IS_MAC:
                subprocess.run(["open", p], check=False)
            elif sys.platform.startswith("win"):
                import os
                os.startfile(p)  # noqa: S606
            else:
                subprocess.run(["xdg-open", p], check=False)

    def log_inbox(self, msg):
        self.inbox_log.config(state="normal")
        self.inbox_log.insert("end", f"{datetime.now():%d %b %H:%M}  {msg}\n")
        self.inbox_log.see("end")
        self.inbox_log.config(state="disabled")

    def toggle_inbox(self):
        if self.inbox_on:
            self.inbox_on = False
            self.inbox_btn.config(text="Start")
            self.log_inbox("Stopped.")
            return
        if not Path(self.inbox_folder.get()).is_dir():
            messagebox.showinfo(APP_NAME, "Choose the shared folder first.")
            return
        if not self.logged_in():
            messagebox.showinfo(APP_NAME, "First connect your Garmin account (button at the top right).")
            return
        self.inbox_on = True
        self.inbox_btn.config(text="Stop")
        self.log_inbox(f"Watching {self.inbox_folder.get()} (every 10 min while the app is open).")
        self.inbox_tick()

    def inbox_tick(self):
        if not self.inbox_on:
            return
        self.check_inbox()
        self.after(10 * 60 * 1000, self.inbox_tick)

    def check_inbox(self):
        folder = Path(self.inbox_folder.get())
        if not folder.is_dir():
            return
        cfg = self.profile.config()

        def work():
            from .cli import process_inbox
            msgs = []
            process_inbox(self.profile, folder, cfg, get_api=self.get_api, log=msgs.append)
            return msgs

        def done(msgs):
            for m in msgs or ["No new plans."]:
                self.log_inbox(m)
            self.set_status("Folder checked.")
        self.run_bg("Checking trainer folder", work, done)

    # ------------------------------------------------------------ tab 3: report
    def build_report_tab(self, nb):
        f = ttk.Frame(nb, padding=10)
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Button(bar, text="Update from Garmin", style="Big.TButton", command=self.sync).pack(side="left")
        ttk.Label(bar, text="  weeks:").pack(side="left")
        self.weeks = tk.IntVar(value=8)
        ttk.Spinbox(bar, from_=2, to=52, width=4, textvariable=self.weeks, command=self.show_report).pack(side="left")
        ttk.Button(bar, text="Copy report", command=self.copy_report).pack(side="left", padx=8)
        ttk.Label(f, text="Copy the report and send it to your coach, or paste it into an AI assistant for advice.",
                  style="Status.TLabel").pack(anchor="w", pady=4)
        self.report_box = tk.Text(f, font=(MONO_FONT, 10), wrap="none", state="disabled", background="#f6f7f9",
                                  relief="flat")
        self.report_box.pack(fill="both", expand=True)
        self.after(500, self.show_report)
        return f

    def show_report(self):
        try:
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                data.report(self.profile, int(self.weeks.get()))
            out = (self.profile.dir / "report.md").read_text(encoding="utf-8")
        except SystemExit:
            out = "No training data yet. Press 'Update from Garmin' (takes about a minute)."
        except Exception as e:  # noqa: BLE001
            out = f"Couldn't build the report: {e}"
        self.report_box.config(state="normal")
        self.report_box.delete("1.0", "end")
        self.report_box.insert("1.0", out)
        self.report_box.config(state="disabled")

    def copy_report(self):
        self.clipboard_clear()
        self.clipboard_append(self.report_box.get("1.0", "end"))
        self.set_status("Report copied. Paste it anywhere.")

    def sync(self):
        if not self.logged_in():
            messagebox.showinfo(APP_NAME, "First connect your Garmin account (button at the top right).")
            return

        def work():
            import contextlib
            import io
            api = self.get_api()
            self.profile.client = lambda interactive=True: api  # reuse the open session
            with contextlib.redirect_stdout(io.StringIO()):
                data.sync(self.profile, days=90, daily_days=21)
        self.run_bg("Downloading the last 90 days from Garmin (about a minute)", work,
                    lambda _: (self.show_report(), self.refresh_account(), self.set_status("Updated.")))

    # ------------------------------------------------------------ help
    def show_help(self):
        if messagebox.askyesno(APP_NAME, (
                "How to write a plan:\n\n"
                "• Start each day with a line like  Mon - Legs  or  Thu 19 Nov - Run\n"
                "• Strength:  Back squat 4 x 6 @ 60kg rest 2 min\n"
                "• Supersets:  Superset: face pulls 3 x 15 / curls 3 x 10\n"
                "• Runs:  4 x 6 min @ T-pace, 1 min jog   or   Long run 50 min @ z2\n"
                "• 'Fri off' days are skipped.\n\n"
                "Orange ⚠ lines mean an exercise name was a guess. Reword it and check the preview again.\n\n"
                "Open the full guide in your browser?")):
            webbrowser.open(HELP_URL)


class LoginDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Connect your Garmin account")
        self.resizable(False, False)
        self.result = None
        f = ttk.Frame(self, padding=18)
        f.pack()
        ttk.Label(f, text="Use the same email and password as the Garmin Connect app.", wraplength=340).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(f, text="Email").grid(row=1, column=0, sticky="w")
        self.email = ttk.Entry(f, width=34)
        self.email.grid(row=1, column=1, pady=3)
        ttk.Label(f, text="Password").grid(row=2, column=0, sticky="w")
        self.pw = ttk.Entry(f, width=34, show="•")
        self.pw.grid(row=2, column=1, pady=3)
        self.remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Remember my password on this computer", variable=self.remember).grid(
            row=3, column=1, sticky="w", pady=4)
        ttk.Label(f, foreground="#555", wraplength=340, text=(
            "Your password goes only to Garmin. You normally stay logged in for months even without "
            "'remember'.")).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 10))
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=2, sticky="e")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Connect", command=self.ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self.ok())
        self.email.focus_set()
        self.transient(parent)
        self.grab_set()

    def ok(self):
        if self.email.get().strip() and self.pw.get():
            self.result = (self.email.get().strip(), self.pw.get(), self.remember.get())
            self.destroy()


def friendly_error(e):
    msg = str(e) or type(e).__name__
    low = msg.lower()
    if "401" in low or "authentication" in low or "credentials" in low or "password" in low:
        return "Garmin didn't accept the login. Check your email and password, or press 'Log in to Garmin' again."
    if "429" in low or "too many" in low:
        return "Garmin says too many requests. Wait 15 minutes and try again."
    if "not logged in" in low or "setup" in low:
        return "You're not connected to Garmin yet. Press 'Log in to Garmin' at the top right."
    if "connection" in low or "timed out" in low or "resolve" in low:
        return "Couldn't reach Garmin. Check your internet connection."
    return f"Something went wrong:\n\n{msg}\n\n{traceback.format_exception_only(type(e), e)[-1].strip()}"


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
