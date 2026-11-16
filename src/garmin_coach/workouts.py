"""Turn workout specs (dicts) into Garmin Connect workout payloads, and push them.

Spec format (what textplan.py produces, or what you can write as JSON):
  {"name": "...", "date": "YYYY-MM-DD", "sport": "running" | "strength_training", "steps": [...]}
Run steps:      {"type": "warmup|interval|recovery|rest|cooldown", "time": "m:ss" | "distance": metres,
                 "pace": ["m:ss", "m:ss"] | "hr": [lo, hi], "note": "..."}
Strength steps: {"exercise": "<Garmin catalog name>", "sets": 4, "reps": 8 | "time": "m:ss",
                 "rest": "m:ss" | "lap", "weight": kg, "note": "..."}
Repeats:        {"repeat": 3, "steps": [...]}
"""

import hashlib
import json
from datetime import datetime

from .util import parse_clock

STEP_TYPES = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4, "rest": 5}
SPORTS = {"running": 1, "cycling": 2, "other": 3, "swimming": 4, "strength_training": 5, "cardio_training": 6}


def expand_sets(s):
    """{"exercise": X, "sets": 4, ..., "rest": "1:30"} -> repeat group of [exercise, rest]."""
    if "repeat" in s:
        return {**s, "steps": [expand_sets(c) for c in s["steps"]]}
    if "exercise" in s and (s.get("sets") or 1) > 1:
        one = {k: v for k, v in s.items() if k not in ("sets", "rest")}
        steps = [one]
        rest = s.get("rest", "lap")
        if rest:
            steps.append({"type": "rest"} if rest == "lap" else {"type": "rest", "time": rest})
        return {"repeat": s["sets"], "steps": steps}
    return s


def end_condition(step, s):
    if "reps" in s:
        step["endCondition"] = {"conditionTypeId": 10, "conditionTypeKey": "reps"}
        step["endConditionValue"] = float(s["reps"])
    elif "time" in s:
        step["endCondition"] = {"conditionTypeId": 2, "conditionTypeKey": "time"}
        step["endConditionValue"] = parse_clock(str(s["time"]))
    elif "distance" in s:
        step["endCondition"] = {"conditionTypeId": 3, "conditionTypeKey": "distance"}
        step["endConditionValue"] = float(s["distance"])
    else:
        step["endCondition"] = {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}


def exercise_step(s, order):
    from garminconnect.exercises import resolve
    ex = resolve(s["exercise"])
    if not ex:
        raise ValueError(f"Unknown Garmin exercise '{s['exercise']}'")
    step = {"type": "ExecutableStepDTO", "stepOrder": order,
            "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
            "category": ex["category"], "exerciseName": ex["exercise"] or None,
            "description": (s.get("note") or None) and s["note"][:250],
            "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}}
    end_condition(step, {k: v for k, v in s.items() if k != "distance"})
    if s.get("weight"):
        step["weightValue"] = float(s["weight"]) * 1000  # Garmin stores grams
        step["weightUnit"] = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
    return step


def pace_to_ms(p):
    return 1000 / parse_clock(p)


def build_step(s, order):
    if "exercise" in s:
        return exercise_step(s, order)
    if "repeat" in s:
        children, o = [], order
        for c in s["steps"]:
            o += 1
            children.append(build_step(c, o))
            o += count_steps(c) - 1
        return {
            "type": "RepeatGroupDTO", "stepOrder": order,
            "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
            "numberOfIterations": s["repeat"],
            "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
            "endConditionValue": s["repeat"], "smartRepeat": False,
            "workoutSteps": children,
        }
    st = s.get("type", "interval")
    step = {"type": "ExecutableStepDTO", "stepOrder": order,
            "stepType": {"stepTypeId": STEP_TYPES[st], "stepTypeKey": st},
            "description": (s.get("note") or None) and s["note"][:250]}
    end_condition(step, s)
    if "hr" in s:
        lo, hi = sorted(s["hr"])
        step["targetType"] = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
        step["targetValueOne"], step["targetValueTwo"] = lo, hi
    elif "pace" in s:
        lo, hi = sorted(pace_to_ms(p) for p in s["pace"])  # m/s, slow -> fast
        step["targetType"] = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}
        step["targetValueOne"], step["targetValueTwo"] = lo, hi
    else:
        step["targetType"] = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
    return step


def count_steps(s):
    return 1 + sum(count_steps(c) for c in s["steps"]) if "repeat" in s else 1


def build_workout(w):
    sport = w.get("sport", "running")
    sport_type = {"sportTypeId": SPORTS[sport], "sportTypeKey": sport}
    steps, order = [], 1
    for s in (expand_sets(x) for x in w["steps"]):
        steps.append(build_step(s, order))
        order += count_steps(s)
    return {
        "workoutName": w["name"][:80], "description": w.get("description"), "sportType": sport_type,
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport_type, "workoutSteps": steps}],
    }


# ----------------------------------------------------------------- pushing with a ledger (no duplicates)

def spec_hash(w):
    clean = json.loads(json.dumps(w, default=str))
    return hashlib.sha1(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:16]


def load_ledger(profile):
    return json.loads(profile.ledger_file.read_text()) if profile.ledger_file.exists() else {}


def push_specs(profile, api, specs, source="", force=False, log=print):
    ledger = load_ledger(profile)
    results = []
    for w in specs:
        h = spec_hash(w)
        if h in ledger and not force:
            log(f"  skip  '{w['name']}' {w.get('date') or ''} - already pushed (id {ledger[h]['id']}). Use --force to push again.")
            continue
        r = api.upload_workout(build_workout(w))
        wid = (r if isinstance(r, dict) else r.json())["workoutId"]
        if w.get("date"):
            api.schedule_workout(wid, w["date"])
        ledger[h] = {"id": wid, "name": w["name"], "date": w.get("date"), "source": str(source),
                     "pushed_at": datetime.now().isoformat(timespec="seconds")}
        profile.ledger_file.write_text(json.dumps(ledger, indent=1))
        log(f"  added '{w['name']}'" + (f" on {w['date']}" if w.get("date") else " (unscheduled)") + f"  (id {wid})")
        results.append(wid)
    return results


def remove_specs(profile, api, specs, log=print):
    ledger = load_ledger(profile)
    for w in specs:
        h = spec_hash(w)
        if h not in ledger:
            log(f"  not found: '{w['name']}' {w.get('date') or ''} (was it pushed from this exact file?)")
            continue
        api.delete_workout(ledger[h]["id"])
        log(f"  removed '{w['name']}' {w.get('date') or ''} (id {ledger[h]['id']})")
        del ledger[h]
    profile.ledger_file.write_text(json.dumps(ledger, indent=1))
