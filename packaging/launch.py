"""Entry point for the Windows .exe (PyInstaller).

`GarminCoach.exe --selftest out.txt` parses the built-in example and writes the preview to out.txt
(used to check a build without opening the window).
"""
import sys

if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
    from garmin_coach.app import EXAMPLE
    from garmin_coach.textplan import describe, parse_text
    plan = parse_text(EXAMPLE, {"threshold_pace": "6:07", "threshold_hr": 184})
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(describe(plan))
    sys.exit(0)

from garmin_coach.app import main  # noqa: E402

main()
