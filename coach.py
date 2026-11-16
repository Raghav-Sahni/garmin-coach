"""Old entry point, kept so `python coach.py ...` still works. Prefer `garmin-coach ...`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from garmin_coach.cli import main  # noqa: E402

main()
