"""Pull Garmin data (or import a CSV export), and write a training report."""

import csv
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

from .util import fmt_dur, fmt_pace, parse_clock, parse_num


def is_run(a):
    return "run" in a["type"].lower()


def merge_activities(profile, new):
    existing = {a["id"]: a for a in profile.load("activities.json", [])}
    for a in new:
        existing[a["id"]] = a
    acts = sorted(existing.values(), key=lambda a: a["start"], reverse=True)
    profile.save("activities.json", acts)
    return acts


# ----------------------------------------------------------------- sync from Garmin

def normalize_api_activity(r):
    dist_km = (r.get("distance") or 0) / 1000
    speed = r.get("averageSpeed")
    return {
        "id": str(r.get("activityId")),
        "start": r.get("startTimeLocal"),
        "type": (r.get("activityType") or {}).get("typeKey", "unknown").replace("_", " "),
        "name": r.get("activityName"),
        "distance_km": round(dist_km, 3),
        "duration_s": r.get("duration") or 0,
        "avg_hr": r.get("averageHR"),
        "max_hr": r.get("maxHR"),
        "pace_s_km": (1000 / speed) if speed and dist_km > 0.2 else None,
        "calories": r.get("calories"),
        "aerobic_te": r.get("aerobicTrainingEffect"),
        "anaerobic_te": r.get("anaerobicTrainingEffect"),
        "ascent_m": r.get("elevationGain"),
        "avg_cadence": r.get("averageRunningCadenceInStepsPerMinute"),
        "avg_power": r.get("avgPower"),
        "total_sets": r.get("totalSets") or r.get("activeSets"),
        "total_reps": r.get("totalReps"),
        "source": "api",
    }


def daily_metrics(api, d):
    ds = d.isoformat()
    out = {"date": ds}

    def safe(fn):
        try:
            return fn()
        except Exception:
            return None

    stats = safe(lambda: api.get_stats(ds)) or {}
    out["resting_hr"] = stats.get("restingHeartRate")
    out["steps"] = stats.get("totalSteps")
    out["stress_avg"] = stats.get("averageStressLevel")
    out["body_battery_max"] = stats.get("bodyBatteryHighestValue")
    summ = (safe(lambda: api.get_hrv_data(ds)) or {}).get("hrvSummary") or {}
    out["hrv_last_night"] = summ.get("lastNightAvg")
    out["hrv_status"] = summ.get("status")
    dto = (safe(lambda: api.get_sleep_data(ds)) or {}).get("dailySleepDTO") or {}
    out["sleep_h"] = round(dto["sleepTimeSeconds"] / 3600, 2) if dto.get("sleepTimeSeconds") else None
    out["sleep_score"] = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value")
    mm = safe(lambda: api.get_max_metrics(ds))
    if isinstance(mm, list) and mm:
        gen = mm[0].get("generic") or {}
        out["vo2max"] = gen.get("vo2MaxPreciseValue") or gen.get("vo2MaxValue")
    return out


def sync(profile, days=90, daily_days=30):
    api = profile.client()
    end = date.today()
    start = end - timedelta(days=days - 1)
    print(f"Fetching activities {start} -> {end} ...")
    raw = api.get_activities_by_date(start.isoformat(), end.isoformat())
    acts = merge_activities(profile, [normalize_api_activity(r) for r in raw])
    print(f"  {len(raw)} activities fetched ({len(acts)} stored total)")
    daily = {d["date"]: d for d in profile.load("daily.json", [])}
    n = min(days, daily_days)
    print(f"Fetching daily metrics for the last {n} days (HRV, sleep, resting HR, VO2max) ...")
    for i in range(n):
        d = end - timedelta(days=i)
        daily[d.isoformat()] = daily_metrics(api, d)
        print(f"  {d}", end="\r")
    profile.save("daily.json", sorted(daily.values(), key=lambda x: x["date"]))
    try:
        thresholds(profile, api, quiet=True)
    except Exception:
        pass
    print("\nDone. Next: garmin-coach report")


def thresholds(profile, api=None, quiet=False):
    """Read Garmin's lactate threshold (pace + HR) into the profile config."""
    api = api or profile.client()
    lt = api.get_lactate_threshold(latest=True) or {}
    sh = lt.get("speed_and_heart_rate") or {}
    cfg = profile.config()
    if sh.get("heartRate"):
        cfg["threshold_hr"] = sh["heartRate"]
    if sh.get("speed"):
        ms = sh["speed"] * 10 if sh["speed"] < 1 else sh["speed"]  # endpoint reports m/s / 10
        cfg["threshold_pace"] = fmt_pace(1000 / ms)
    if sh.get("calendarDate"):
        cfg["threshold_date"] = str(sh["calendarDate"])[:10]
    profile.save_config(cfg)
    if not quiet:
        print(f"Threshold: {cfg.get('threshold_pace', '?')}/km @ {cfg.get('threshold_hr', '?')} bpm "
              f"(measured {cfg.get('threshold_date', '?')})")
    return cfg


# ----------------------------------------------------------------- CSV import

def import_csv(profile, path):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    new = []
    for r in rows:
        if not r.get("Date"):
            continue
        typ = r["Activity Type"]
        run = "run" in typ.lower()
        dist = parse_num(r.get("Distance")) or 0
        if dist > 150:  # track runs/swims are exported in metres
            dist /= 1000
        dur = parse_clock(r.get("Total Time")) or 0
        pace = parse_clock(r.get("Avg Speed")) if run else None
        if run and pace is None and dist > 0.2 and dur:
            pace = dur / dist
        new.append({
            "id": f"csv-{r['Date']}", "start": r["Date"], "type": typ.lower(), "name": r.get("Title"),
            "distance_km": round(dist, 3), "duration_s": dur,
            "avg_hr": parse_num(r.get("Avg HR")), "max_hr": parse_num(r.get("Max HR")),
            "pace_s_km": pace, "calories": parse_num(r.get("Calories")),
            "aerobic_te": parse_num(r.get("Aerobic TE")), "ascent_m": parse_num(r.get("Total Ascent")),
            "avg_cadence": parse_num(r.get("Avg Bike Cadence")), "avg_power": parse_num(r.get("Avg Power")),
            "total_sets": parse_num(r.get("Total Sets")), "total_reps": parse_num(r.get("Total Reps")),
            "source": "csv",
        })
    acts = merge_activities(profile, new)
    print(f"Imported {len(new)} activities ({len(acts)} stored total). Next: garmin-coach report")


# ----------------------------------------------------------------- report

def hr_zone(hr, cfg):
    """With threshold_hr: % of threshold HR (Friel) Z1<85 Z2<90 Z3<95 Z4<100 Z5.
    Otherwise % of HR reserve: Z1<60 Z2<70 Z3<80 Z4<90 Z5."""
    if not hr:
        return None
    if cfg.get("threshold_hr"):
        pct, lims = hr / cfg["threshold_hr"], (0.85, 0.90, 0.95, 1.0)
    else:
        pct, lims = (hr - cfg["resting_hr"]) / (cfg["max_hr"] - cfg["resting_hr"]), (0.6, 0.7, 0.8, 0.9)
    for z, lim in enumerate(lims, 1):
        if pct < lim:
            return z
    return 5


def report(profile, weeks=8):
    cfg = profile.config()
    acts = profile.load("activities.json", [])
    daily = profile.load("daily.json", [])
    if not acts:
        sys.exit("No data yet. Run `garmin-coach sync` or `garmin-coach import-csv Activities.csv` first.")
    for a in acts:
        a["_dt"] = datetime.fromisoformat(a["start"].replace("T", " ")[:19])
    latest = max(a["_dt"] for a in acts)
    cutoff = latest - timedelta(weeks=weeks)
    acts = [a for a in acts if a["_dt"] >= cutoff]
    runs = [a for a in acts if is_run(a) and a["distance_km"] >= 1]

    L = [f"# Training report ({cutoff.date()} -> {latest.date()}, {weeks} weeks)"]
    if cfg.get("threshold_hr"):
        L.append(f"Garmin lactate threshold: {cfg.get('threshold_pace', '?')}/km @ {cfg['threshold_hr']} bpm "
                 f"(measured {cfg.get('threshold_date', '?')}). Zones = % of threshold HR.\n")
    else:
        L.append(f"Settings: max HR {cfg['max_hr']}, resting HR {cfg['resting_hr']}. "
                 "Run `garmin-coach thresholds` to use Garmin's threshold instead.\n")

    weeks_d = defaultdict(lambda: {"h": 0, "run_km": 0, "runs": 0, "strength": 0, "hiit": 0, "other": 0, "long": 0})
    for a in acts:
        w = weeks_d[(a["_dt"] - timedelta(days=a["_dt"].weekday())).date()]
        w["h"] += a["duration_s"] / 3600
        t = a["type"].lower()
        if is_run(a):
            w["run_km"] += a["distance_km"]
            w["runs"] += a["distance_km"] >= 1
            w["long"] = max(w["long"], a["distance_km"])
        elif "strength" in t:
            w["strength"] += 1
        elif "hiit" in t or "cardio" in t:
            w["hiit"] += 1
        else:
            w["other"] += 1
    L += ["## Weekly load", "| Week of | Hours | Run km | Runs | Longest run | Strength | HIIT | Other |",
          "|---|---|---|---|---|---|---|---|"]
    for wk in sorted(weeks_d):
        w = weeks_d[wk]
        L.append(f"| {wk} | {w['h']:.1f} | {w['run_km']:.1f} | {w['runs']} | {w['long']:.1f} km | "
                 f"{w['strength']} | {w['hiit']} | {w['other']} |")

    zt = defaultdict(float)
    for a in runs:
        z = hr_zone(a.get("avg_hr"), cfg)
        if z:
            zt[z] += a["duration_s"]
    tot = sum(zt.values()) or 1
    L.append("\n## Run intensity (by session avg HR, time-weighted)")
    L.append(" | ".join(f"Z{z}: {zt[z] / tot * 100:.0f}%" for z in range(1, 6)))
    L.append(f"Easy (Z1-2) share of run time: {(zt[1] + zt[2]) / tot * 100:.0f}%  (endurance guideline ~75-80%)")

    L += ["\n## Runs", "| Date | Type | km | Time | Pace /km | Avg HR | Zone | Aerobic TE |",
          "|---|---|---|---|---|---|---|---|"]
    for a in sorted(runs, key=lambda a: a["_dt"]):
        L.append(f"| {a['_dt']:%Y-%m-%d} | {a['type']} | {a['distance_km']:.2f} | {fmt_dur(a['duration_s'])} | "
                 f"{fmt_pace(a['pace_s_km'])} | {a['avg_hr'] or '-'} | Z{hr_zone(a['avg_hr'], cfg) or '-'} | "
                 f"{a.get('aerobic_te') or '-'} |")

    eff = [(a["_dt"], a["pace_s_km"], a["avg_hr"]) for a in runs
           if a.get("pace_s_km") and a.get("avg_hr") and "treadmill" not in a["type"] and "track" not in a["type"]]
    if len(eff) >= 2:
        L.append("\n## Aerobic efficiency (outdoor runs)")
        L.append("Metres per heartbeat = speed / HR. Higher = fitter. Watch the trend, not single runs.")
        for dt, p, hr in sorted(eff):
            L.append(f"- {dt:%Y-%m-%d}: {fmt_pace(p)}/km @ {hr:.0f} bpm -> {(1000 / p) * 60 / hr:.2f} m/beat")

    hard_hr = 0.95 * cfg["threshold_hr"] if cfg.get("threshold_hr") else 0.85 * cfg["max_hr"]
    hard = [a for a in runs if a.get("avg_hr") and a["avg_hr"] >= hard_hr
            and a["duration_s"] >= 20 * 60 and a.get("pace_s_km")]
    if hard:
        L.append("\n## Best hard efforts (>= 20 min)")
        L.append("Treadmill pace from a wrist watch is often off - trust outdoor numbers more.")
        for label, group in (("Outdoor", [a for a in hard if "treadmill" not in a["type"]]),
                             ("Treadmill", [a for a in hard if "treadmill" in a["type"]])):
            if group:
                b = min(group, key=lambda a: a["pace_s_km"])
                L.append(f"- {label}: {b['distance_km']:.1f} km @ {fmt_pace(b['pace_s_km'])}/km, "
                         f"avg HR {b['avg_hr']:.0f} ({b['_dt']:%Y-%m-%d})")

    dd = [d for d in daily if d["date"] >= cutoff.date().isoformat()]
    if dd:
        def avg(key, rows):
            v = [r[key] for r in rows if r.get(key) is not None]
            return round(statistics.mean(v), 1) if v else None
        L += ["\n## Recovery & fitness", "| Metric | Last 7 days | Whole period |", "|---|---|---|"]
        for key, label in [("resting_hr", "Resting HR"), ("hrv_last_night", "HRV (ms)"), ("sleep_h", "Sleep (h)"),
                           ("sleep_score", "Sleep score"), ("stress_avg", "Avg stress"),
                           ("body_battery_max", "Body Battery high")]:
            L.append(f"| {label} | {avg(key, dd[-7:]) or '-'} | {avg(key, dd) or '-'} |")
        vo2 = [d for d in dd if d.get("vo2max")]
        if vo2:
            L.append(f"\nVO2max: {vo2[0]['vo2max']} ({vo2[0]['date']}) -> {vo2[-1]['vo2max']} ({vo2[-1]['date']})")

    L.append("\n---\nPaste this into Claude (or send it to your coach) with your goal and ask for insights.")
    out = profile.dir / "report.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nSaved to {out}")
