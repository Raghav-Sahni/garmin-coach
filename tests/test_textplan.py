from datetime import date

import pytest

from garmin_coach.textplan import ALIASES, match_exercise, parse_text
from garmin_coach.workouts import build_workout

TODAY = date(2026, 11, 16)  # a Monday
CFG = {"threshold_pace": "6:07", "threshold_hr": 184, "max_hr": 200}

# Exactly as a trainer sent it over WhatsApp (bullets, tabs, a half-closed bracket, a side comment).
TRAINER_RUNS = """Wed 18 Nov: Optional

- 20–30 min easy cardio or mobility

Thu 19 Nov: Threshold intervals

•\tWarm-up: 10–15 min easy jog, drills, 4 × 20 second strides
•\tMain set: 4 × 6 min at T-pace, 1 min easy jog between (24 min of threshold work). @~Alex can maybe do 3 × 6 min if that sounds tough (quality over quantity)

Friday Off

Sunday Easy long run 45-50 min (any pace but has to be continuous non stop
"""

TRAINER_UPPER = """MONDAY

Warm-up: 5 min easy cardio, band pull-aparts, scap push-ups
\t
•\tFlat DB bench press: 4 × 8
•\tChin-ups (palms toward you) or assisted chin-ups: 4 × 6
•\tArnold press: 3 × 8
•\tSeal row or inverted row: 3 × 10
•\tSuperset: cable face pulls 3 × 15 / EZ-bar curls 3 × 10
•\tAb wheel or Pallof press: 3 × 8–10
"""


def by_name(plan):
    return {w["name"]: w for w in plan.specs}


def test_trainer_runs():
    plan = parse_text(TRAINER_RUNS, CFG, TODAY)
    w = by_name(plan)
    assert set(w) == {"Optional", "Threshold intervals", "Easy long run"}
    assert any("Off" in s for s in plan.skipped)

    thr = w["Threshold intervals"]
    assert thr["sport"] == "running" and thr["date"] == "2026-11-19"
    warm, drills, strides, main = thr["steps"]
    assert warm == {**warm, "type": "warmup", "time": "10:00"}
    assert drills["type"] == "warmup" and "time" not in drills
    assert strides["repeat"] == 4 and strides["steps"][0]["time"] == "0:20"
    assert main["repeat"] == 4                      # not fooled by the "3 × 6" side comment
    work, rec = main["steps"]
    assert work["time"] == "6:00" and work["pace"] == ["6:02", "6:15"]   # T-pace from Garmin threshold
    assert rec == {**rec, "type": "recovery", "time": "1:00"}

    long = w["Easy long run"]
    assert long["date"] == "2026-11-22" and long["steps"][0]["time"] == "45:00"
    assert w["Optional"]["steps"][0]["exercise"] == "Cardio"
    for spec in plan.specs:
        build_workout(spec)


def test_trainer_upper_body():
    plan = parse_text(TRAINER_UPPER, CFG, TODAY)
    (w,) = plan.specs
    assert w["sport"] == "strength_training" and w["date"] == "2026-11-16"
    names = []
    for s in w["steps"]:
        names += [c.get("exercise") for c in s["steps"]] if "repeat" in s else [s["exercise"]]
    assert names == ["Cardio", "Banded Pull Apart", "Push-up Plus", "Dumbbell Bench Press", "Chin-up",
                     "Arnold Press", "Inverted Row", "Face Pull", "Barbell Biceps Curl", None, "Kneeling Ab Wheel"]
    bench = w["steps"][3]
    assert (bench["sets"], bench["reps"]) == (4, 8)
    superset = w["steps"][7]
    assert superset["repeat"] == 3
    assert not [x for x in plan.warnings if "check it" in x]
    build_workout(w)


def test_week_directive_and_formats():
    txt = """week: 23 Nov
# Tue - Legs
date: Wed
- Back squat 4x6 @ 60kg rest 2 min
- Plank 3 x 45s
- Farmer's carry 4 x 40m
- Sled push 4 x 15 m rest 90
"""
    (w,) = parse_text(txt, CFG, TODAY).specs
    assert w["date"] == "2026-11-25"   # explicit date: line wins over the header day
    squat, plank, carry, sled = w["steps"]
    assert squat == {**squat, "exercise": "Back Squats", "sets": 4, "reps": 6, "weight": 60.0, "rest": "2:00"}
    assert plank["time"] == "0:45" and plank["sets"] == 3
    assert carry["exercise"] == "Farmer's Carry" and "reps" not in carry   # distance -> press LAP
    assert sled["rest"] == "1:30"


def test_run_targets():
    txt = """Sat - Track
- warmup 15 min @ z2
- 6 x 400m @ 5:00-5:10/km, 200m jog
- 3 x 1 km @ 5:30, 2 min rest
- cooldown 10 min hr 120-145
"""
    (w,) = parse_text(txt, CFG, TODAY).specs
    wu, reps400, km, cd = w["steps"]
    assert wu["hr"] == [156, 164]
    assert reps400["steps"][0] == {**reps400["steps"][0], "distance": 400, "pace": ["5:00", "5:10"]}
    assert reps400["steps"][1]["distance"] == 200
    assert km["steps"][0]["pace"] == ["5:25", "5:35"] and km["steps"][1] == {**km["steps"][1], "type": "rest", "time": "2:00"}
    assert cd["hr"] == [120, 145]


def test_indented_circuit():
    txt = """Sat 21 Nov - Functional
Circuit 4 rounds rest 2 min:
    - Run 1 km
    - Wall balls 20
    - Sled push 25m

- Plank 3 x 30s
"""
    (w,) = parse_text(txt, CFG, TODAY).specs
    circuit, plank = w["steps"]
    assert circuit["repeat"] == 4
    assert [s.get("exercise") for s in circuit["steps"]] == ["Run", "Wall Ball", "Sled Push", None]
    assert circuit["steps"][-1]["time"] == "2:00"
    assert plank["exercise"] == "Plank"


def test_chat_sentences_are_not_workouts():
    assert parse_text("hello coach, see you saturday", CFG, TODAY).specs == []
    (w,) = parse_text("Mon - Upper\nGreat work last week!\n- Bench press 3 x 5", CFG, TODAY).specs
    assert [s["exercise"] for s in w["steps"]] == ["Bench Press"]
    assert "Great work" in w["description"]


@pytest.mark.parametrize("text,expected", [
    ("DB bench", "Dumbbell Bench Press"), ("pull-ups", "Pull-up"), ("RDLs", "Romanian Deadlift"),
    ("KB swings", "Kettlebell Swing"), ("lat pulldown", "Lat Pull-down"), ("goblet squats", "Goblet Squat"),
    ("wall balls", "Wall Ball"), ("SkiErg", "Cardio"), ("row", "Rowing Machine"),
    ("Incline barbell or DB bench press", "Incline Barbell Bench Press"),
    ("Half-kneeling landmine press", "Single-arm Dumbbell Shoulder Press"),
    ("rope triceps pushdown", "Triceps Press-down"), ("Cable row", "Seated Cable Row"),
    ("Seal row or inverted row", "Inverted Row"), ("Ab wheel or Pallof press", "Kneeling Ab Wheel"),
    ("box jumps", "Box Jump"), ("hip thrusts", "Barbell Hip Thrust with Bench"), ("burpees", "Burpee"),
])
def test_names(text, expected):
    assert match_exercise(text)[0] == expected


def test_aliases_exist_in_garmin_catalog():
    from garminconnect.exercises import resolve
    assert [v for v in ALIASES.values() if not resolve(v)] == []
