"""garmin-coach command line.

  garmin-coach setup                       log in once (tokens cached ~1 year) and read your thresholds
  garmin-coach check  week.txt             show how a workout file is understood (no login, nothing sent)
  garmin-coach push   week.txt             put the workouts on your Garmin calendar -> watch
  garmin-coach remove week.txt             take them off again
  garmin-coach inbox  FOLDER [--watch 10]  push every new file a trainer drops into FOLDER
  garmin-coach sync | import-csv FILE | report | thresholds

Add --profile NAME before the command to manage more than one Garmin account.
"""

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import data
from .profile import Profile
from .textplan import describe, load_plan
from .workouts import build_workout, push_specs, remove_specs

PLAN_EXT = {".txt", ".md", ".json"}


def _plan(profile, path):
    plan = load_plan(path, profile.config())
    if not plan.specs:
        print(describe(plan))
        sys.exit(f"No workouts found in {path}.")
    return plan


def cmd_setup(p, a):
    import getpass
    print(f"Setting up profile '{p.name}'. Your password is sent only to Garmin, and is not stored unless you choose to.")
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    from garminconnect import Garmin
    api = Garmin(email=email, password=password, prompt_mfa=lambda: input("Garmin 2FA code: ").strip())
    api.login(str(p.tokens))
    print(f"Logged in as {api.full_name or api.display_name}. Login saved for this computer.")
    if input("Also save the password so it can log in again by itself if Garmin expires the login? [y/N] ").lower().startswith("y"):
        p.env_file.write_text(f"email={email}\npassword={password}\n")
        print(f"Saved to {p.env_file} (keep this file private).")
    try:
        data.thresholds(p, api)
    except Exception as e:
        print(f"(Couldn't read threshold pace/HR: {e})")
    print("\nDone. Try:  garmin-coach check examples/trainer_week.txt")


def cmd_check(p, a):
    plan = load_plan(a.file, p.config())
    print(describe(plan))
    if a.json:
        import json
        print(json.dumps([build_workout(w) for w in plan.specs], indent=1))
    print(f"\n{len(plan.specs)} workout(s). Nothing was sent. To send: garmin-coach push \"{a.file}\"")


def cmd_push(p, a):
    plan = _plan(p, a.file)
    print(describe(plan))
    if a.dry_run:
        return
    if plan.warnings and not a.yes and sys.stdin.isatty():
        if not input("\nThere are warnings above. Push anyway? [y/N] ").lower().startswith("y"):
            return
    print()
    push_specs(p, p.client(), plan.specs, source=Path(a.file).name, force=a.force)
    print("Sync your watch (Garmin Connect app) to get them.")


def cmd_remove(p, a):
    plan = _plan(p, a.file)
    remove_specs(p, p.client(), plan.specs)


def process_inbox(p, folder, cfg=None, get_api=None, log=print, allow_warnings=False):
    """Push every plan file in `folder` once. Sent files -> pushed/, problem files -> failed/ (+ .error.txt)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    done, failed = folder / "pushed", folder / "failed"
    cfg = cfg or p.config()
    state = {"api": None}

    def api():
        if state["api"] is None:
            state["api"] = get_api() if get_api else p.client(interactive=False)
        return state["api"]

    def out(msg):
        log(msg)
        with open(folder / "log.txt", "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M}  {msg}\n")

    files = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in PLAN_EXT
                   and f.name != "log.txt" and not f.name.startswith(("~", ".")))
    for f in files:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            plan = load_plan(f, cfg)
            if not plan.specs:
                raise ValueError("no workouts found in the file")
            unsure = [x for x in plan.warnings if "check it" in x]
            if unsure and not allow_warnings:
                raise ValueError("needs a human check before sending:\n  " + "\n  ".join(unsure)
                                 + "\nReword those exercise names and save the file again.")
            out(f"{f.name}: {len(plan.specs)} workout(s)")
            push_specs(p, api(), plan.specs, source=f.name, log=lambda m: out("  " + m.strip()))
            done.mkdir(exist_ok=True)
            shutil.move(str(f), done / f"{stamp}_{f.name}")
        except Exception as e:  # noqa: BLE001
            failed.mkdir(exist_ok=True)
            shutil.move(str(f), failed / f"{stamp}_{f.name}")
            (failed / f"{stamp}_{f.name}.error.txt").write_text(f"{e}\n", encoding="utf-8")
            out(f"{f.name}: NOT SENT - {e}")
    return len(files)


def cmd_inbox(p, a):
    print(f"Watching {a.folder} for workout files (.txt/.md/.json)"
          + (f" every {a.watch} min. Ctrl+C to stop." if a.watch else "."))
    while True:
        process_inbox(p, a.folder, log=lambda m: print(f"{datetime.now():%Y-%m-%d %H:%M}  {m}"),
                      allow_warnings=a.allow_warnings)
        if not a.watch:
            break
        time.sleep(a.watch * 60)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="garmin-coach", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="default", help="which Garmin account (default: 'default')")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="log in to Garmin once").set_defaults(fn=cmd_setup)
    s = sub.add_parser("check", help="preview how a workout file is read")
    s.add_argument("file"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_check)
    s = sub.add_parser("push", help="send workouts to Garmin")
    s.add_argument("file"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true", help="push even if already pushed")
    s.add_argument("-y", "--yes", action="store_true", help="don't ask about warnings")
    s.set_defaults(fn=cmd_push)
    s = sub.add_parser("remove", help="delete workouts that were pushed from a file")
    s.add_argument("file"); s.set_defaults(fn=cmd_remove)
    s = sub.add_parser("inbox", help="push every workout file dropped into a folder")
    s.add_argument("folder"); s.add_argument("--watch", type=float, default=0, metavar="MIN",
                                             help="keep checking every MIN minutes")
    s.add_argument("--allow-warnings", action="store_true", help="push even when an exercise name is a guess")
    s.set_defaults(fn=cmd_inbox)
    s = sub.add_parser("sync", help="download activities + daily metrics")
    s.add_argument("--days", type=int, default=90); s.add_argument("--daily-days", type=int, default=30)
    s.set_defaults(fn=lambda p, a: data.sync(p, a.days, a.daily_days))
    s = sub.add_parser("import-csv", help="import a Garmin Connect Activities.csv")
    s.add_argument("file"); s.set_defaults(fn=lambda p, a: data.import_csv(p, a.file))
    s = sub.add_parser("report", help="write a training summary")
    s.add_argument("--weeks", type=int, default=8); s.set_defaults(fn=lambda p, a: data.report(p, a.weeks))
    sub.add_parser("thresholds", help="read threshold pace/HR from Garmin").set_defaults(
        fn=lambda p, a: data.thresholds(p))

    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a.fn(Profile(a.profile), a)


if __name__ == "__main__":
    main()
