"""Where each athlete's settings, login tokens and data live.

Everything is stored per profile under ~/.garmin-coach/profiles/<name>/ (override the root
with GARMIN_COACH_HOME). One profile per Garmin account, so a trainer can manage several
athletes on one computer: `garmin-coach --profile alex push week.txt`.
"""

import json
import os
import sys
from pathlib import Path

DEFAULT_CONFIG = {"max_hr": 200, "resting_hr": 60}


def home():
    return Path(os.environ.get("GARMIN_COACH_HOME") or Path.home() / ".garmin-coach")


class Profile:
    def __init__(self, name="default"):
        self.name = name
        self.dir = home() / "profiles" / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.dir / "config.json"
        self.data = self.dir / "data"
        self.tokens = self.dir / "tokens"
        self.env_file = self.dir / ".env"
        self.ledger_file = self.dir / "pushed.json"

    # ---- config
    def config(self):
        cfg = dict(DEFAULT_CONFIG)
        if self.config_file.exists():
            cfg.update(json.loads(self.config_file.read_text()))
        return cfg

    def save_config(self, cfg):
        self.config_file.write_text(json.dumps(cfg, indent=1))

    # ---- data files
    def load(self, fname, default):
        p = self.data / fname
        return json.loads(p.read_text()) if p.exists() else default

    def save(self, fname, obj):
        self.data.mkdir(exist_ok=True)
        (self.data / fname).write_text(json.dumps(obj, indent=1, default=str))

    # ---- credentials
    def credentials(self):
        """Email/password from env vars, ./.env, or the profile's .env (keys email/password or GARMIN_*)."""
        vals = {}
        for f in (Path.cwd() / ".env", self.env_file):
            if f.exists():
                for line in f.read_text(encoding="utf-8-sig").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip().upper().removeprefix("GARMIN_")
                    vals.setdefault(k, v.strip().strip('"').strip("'"))
        email = os.environ.get("GARMIN_EMAIL") or vals.get("EMAIL")
        password = os.environ.get("GARMIN_PASSWORD") or vals.get("PASSWORD")
        return email, password

    def client(self, interactive=True):
        """Logged-in Garmin client. Uses cached tokens; falls back to saved or typed credentials."""
        try:
            from garminconnect import Garmin
        except ImportError:
            sys.exit("Missing library: pip install garminconnect")
        email, password = self.credentials()
        has_tokens = self.tokens.exists() and any(self.tokens.iterdir()) if self.tokens.is_dir() else self.tokens.exists()
        if not has_tokens and not (email and password):
            if not interactive:
                sys.exit(f"Profile '{self.name}' is not logged in. Run: garmin-coach --profile {self.name} setup")
            import getpass
            print(f"Log in to Garmin Connect for profile '{self.name}' (only needed once).")
            email = email or input("Garmin email: ").strip()
            password = password or getpass.getpass("Garmin password: ")
        api = Garmin(email=email, password=password, prompt_mfa=lambda: input("Garmin 2FA code: ").strip())
        api.login(str(self.tokens))
        return api
