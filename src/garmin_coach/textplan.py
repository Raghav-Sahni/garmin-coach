"""Read workouts written as plain text (the way trainers already write them) into workout specs.

    Thu 19 Nov: Threshold intervals
    - Warm-up: 12 min easy jog, drills, 4 x 20 sec strides
    - 4 x 6 min @ T-pace, 1 min jog
    - Cool-down 8 min

    MONDAY - Upper body
    - DB bench press 4 x 8 @ 22.5kg rest 90s
    - Superset: face pulls 3 x 15 / EZ-bar curls 3 x 10

See TRAINER_GUIDE.md for the full format. The parser is forgiving: unknown lines become notes,
and `garmin-coach check FILE` shows exactly how every line was understood before anything is pushed.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .util import fmt_clock, parse_clock

# ----------------------------------------------------------------- dates

DAY_RE = (r"(monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thur|thu|friday|fri|"
          r"saturday|sat|sunday|sun)")
WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:[a-z]*)\.?"
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
HEADER_START = re.compile(rf"^\s*(#+|{DAY_RE}\b|\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH_RE}\b|"
                          rf"{MONTH_RE}\s+\d{{1,2}}\b|today\b|tomorrow\b)", re.I)


def _infer_year(month, day, today):
    d = date(today.year, month, day)
    if (d - today).days < -180:
        d = date(today.year + 1, month, day)
    elif (d - today).days > 185:
        d = date(today.year - 1, month, day)
    return d


def find_date(text, today, week_start=None):
    """Return (date | None, text with the date words removed)."""
    t = text
    d = None
    pats = [
        (rf"\b(\d{{4}})-(\d{{1,2}})-(\d{{1,2}})\b", lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{MONTH_RE}(?:\s+(\d{{4}}))?\b",
         lambda m: date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])) if m[3]
         else _infer_year(MONTHS[m[2][:3].lower()], int(m[1]), today)),
        (rf"\b{MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s*(\d{{4}}))?",
         lambda m: date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])) if m[3]
         else _infer_year(MONTHS[m[1][:3].lower()], int(m[2]), today)),
        (r"\btoday\b", lambda m: today),
        (r"\btomorrow\b", lambda m: today + timedelta(days=1)),
    ]
    for pat, fn in pats:
        m = re.search(pat, t, re.I)
        if m:
            try:
                d = fn(m)
            except ValueError:
                continue
            t = t[:m.start()] + " " + t[m.end():]
            break
    m = re.search(rf"\b{DAY_RE}\b", t, re.I)
    if m:
        if d is None:
            wd = WEEKDAY[m[1][:3].lower()]
            base = week_start or today
            d = base + timedelta(days=(wd - base.weekday()) % 7)
        t = t[:m.start()] + " " + t[m.end():]
    return d, t


# ----------------------------------------------------------------- exercise names -> Garmin catalog

ABBR = {
    "db": "dumbbell", "dbs": "dumbbell", "bb": "barbell", "kb": "kettlebell", "kbs": "kettlebell",
    "ez": "ez bar", "sl": "single leg", "bw": "", "rdl": "romanian deadlift", "rdls": "romanian deadlift",
    "ohp": "barbell overhead press", "pulldown": "pull down", "pulldowns": "pull down", "pullup": "pull up",
    "pullups": "pull up", "pushup": "push up", "pushups": "push up", "chinup": "chin up", "chinups": "chin up",
    "situp": "sit up", "situps": "sit up", "stepup": "step up", "stepups": "step up", "pullapart": "pull apart",
    "pullaparts": "pull apart", "bbj": "burpee broad jump", "kettlebells": "kettlebell", "dumbbells": "dumbbell",
}
STOP = {"flat", "easy", "light", "heavy", "moderate", "the", "a", "an", "of", "each", "side", "per", "slow",
        "controlled", "x", "set", "sets", "rep", "reps", "your", "some"}

# curated names trainers use -> Garmin catalog display name
ALIASES = {
    "dumbbell bench": "Dumbbell Bench Press", "bench": "Bench Press", "incline bench": "Incline Barbell Bench Press",
    "incline dumbbell bench": "Incline Dumbbell Bench Press", "incline dumbbell press": "Incline Dumbbell Bench Press",
    "seal row": "Chest Supported Dumbbell Row", "chest supported row": "Chest Supported Dumbbell Row",
    "ez bar curl": "Barbell Biceps Curl", "bicep curl": "Dumbbell Biceps Curl", "curl": "Dumbbell Biceps Curl",
    "hammer curl": "Dumbbell Hammer Curl",
    "pallof press": "Cable Core Press", "pallof": "Cable Core Press",
    "ab wheel": "Kneeling Ab Wheel", "ab rollout": "Kneeling Ab Wheel", "rollout": "Kneeling Ab Wheel",
    "skierg": "Cardio", "ski erg": "Cardio", "ski": "Cardio",
    "row": "Rowing Machine", "rower": "Rowing Machine", "rowing": "Rowing Machine", "erg": "Rowing Machine",
    "row erg": "Rowing Machine",
    "wall ball": "Wall Ball", "wallball": "Wall Ball",
    "sled push": "Sled Push", "sled pull": "Sled Backward Drag", "sled drag": "Sled Backward Drag",
    "sled": "Sled Push",
    "burpee broad jump": "Burpee", "burpee": "Burpee",
    "farmer carry": "Farmer's Carry", "farmer walk": "Farmer's Walk", "farmer": "Farmer's Carry",
    "sandbag lunge": "Sandbag Lunge",
    "hip thrust": "Barbell Hip Thrust with Bench",
    "run": "Run", "jog": "Run", "running": "Run", "treadmill": "Treadmill",
    "bike": "Bike", "assault bike": "Assault Bike", "air bike": "Air Bike", "echo bike": "Assault Bike",
    "mobility": "Warm-up", "stretch": "Warm-up", "stretching": "Warm-up", "foam roll": "Warm-up",
    "warm up": "Warm-up", "warmup": "Warm-up", "cool down": "Warm-up", "cooldown": "Warm-up",
    "easy cardio": "Cardio", "cardio": "Cardio",
    "band pull apart": "Banded Pull Apart", "pull apart": "Banded Pull Apart",
    "scap push up": "Push-up Plus", "scapular push up": "Push-up Plus",
    "bent over row": "Barbell Row", "dip": "Body-weight Dip", "tricep dip": "Body-weight Dip",
    "lat pull down": "Lat Pull-down", "lat pulldown": "Lat Pull-down",
    "landmine press": "Single-arm Dumbbell Shoulder Press",  # no landmine moves in Garmin's catalog
    "tricep push down": "Triceps Press-down", "tricep pushdown": "Triceps Press-down",
    "push down": "Triceps Press-down", "pushdown": "Triceps Press-down", "tricep press down": "Triceps Press-down",
    "cable row": "Seated Cable Row", "seated row": "Seated Cable Row",
    "kettlebell swing": "Kettlebell Swing", "swing": "Kettlebell Swing",
}

QUALITY_RANK = {"exact": 0, "alias": 1, "contains": 2, "fuzzy": 3, "guess": 4, "unknown": 5}


def norm(s):
    s = s.lower().replace("’", "").replace("'", "")
    s = re.sub(r"[-_/]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    out = []
    for tok in s.split():
        tok = ABBR.get(tok, tok)
        for t in tok.split():
            if len(t) > 3 and t.endswith("sses"):
                t = t[:-2]
            elif len(t) >= 3 and t.endswith("s") and not t.endswith(("ss", "us")):
                t = t[:-1]
            if t and t not in STOP:
                out.append(t)
    return " ".join(out)


_CATALOG = None


def catalog():
    global _CATALOG
    if _CATALOG is None:
        from garminconnect.exercises import EXERCISES
        cat = {}
        for e in EXERCISES:
            cat.setdefault(norm(e["name"]), e["name"])
        _CATALOG = (cat, {norm(k): v for k, v in ALIASES.items()})
    return _CATALOG


def _contains(hay, needle):
    return re.search(rf"(?:^| ){re.escape(needle)}(?: |$)", hay) is not None


def match_one(text):
    cat, alias = catalog()
    n = norm(text)
    if not n:
        return None, "unknown"
    if n in alias:  # curated trainer words win (e.g. "row" = rowing machine, not a generic row)
        return alias[n], "alias"
    if n in cat:
        return cat[n], "exact"
    best = None
    for table in (cat, alias):
        for k, v in table.items():
            if k and _contains(n, k) and (best is None or len(k.split()) > len(best[0].split())):
                best = (k, v)
    if best:
        return best[1], "contains"
    close = difflib.get_close_matches(n, list(cat) + list(alias), n=1, cutoff=0.82)
    if close:
        return cat.get(close[0]) or alias[close[0]], "fuzzy"
    toks = set(n.split())
    scored = []
    for k, v in cat.items():
        kt = set(k.split())
        j = len(toks & kt) / len(toks | kt)
        if j >= 0.5:
            scored.append((j, -len(k), v))
    if scored:
        return max(scored)[2], "guess"
    return None, "unknown"


def match_exercise(text, fallback="Total Body"):
    """Return (catalog name, quality). 'A or B' tries both and keeps the better match."""
    alts = [a for a in re.split(r"\s+or\s+|\s*/\s*", text, flags=re.I) if a.strip()] or [text]
    if len(alts) > 1:
        # "Incline barbell or DB bench press": the first option borrows the shared ending ("bench press")
        tail = " ".join(alts[-1].split()[-2:])
        alts = [x for a in alts[:-1] for x in (a, f"{a.strip()} {tail}")] + alts[-1:]
    results = [match_one(a) for a in alts]
    name, q = min(results, key=lambda r: QUALITY_RANK[r[1]])
    return (name, q) if name else (fallback, "unknown")


# ----------------------------------------------------------------- amounts and targets

AMOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:\.\d+)?))?\s*"
    r"(seconds|second|secs|sec|s|minutes|minute|mins|min|hours|hour|h|metres|meters|metre|meter|km|k|"
    r"miles|mile|mi|m|calories|cals|cal|reps|rep|'|\")(?![a-z])", re.I)
CLOCK_RE = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])(?!\s*(?:/|min/|per\b))")
SETS_RE = re.compile(
    r"(\d+)\s*(?:sets?\s*)?(?:x|×|\*|sets?\s+of)\s*(\d+(?:\.\d+)?)(?:\s*(?:-|–)\s*(\d+(?:\.\d+)?))?\s*"
    r"(seconds|second|secs|sec|s|minutes|minute|mins|min|metres|meters|m|km|calories|cals|cal|reps|rep|'|\")?"
    r"(?![a-z])", re.I)
REST_RE = re.compile(r"\b(?:rest|recover|recovery)\s*:?\s*(\d+:\d{2}|\d+(?:\.\d+)?)\s*"
                     r"(seconds|second|secs|sec|s|minutes|minute|mins|min|m|')?(?![a-z])", re.I)
WEIGHT_RE = re.compile(r"(?:@\s*)?(\d+(?:\.\d+)?)\s*(kg|kgs|lb|lbs)\b", re.I)


def unit_kind(unit):
    u = (unit or "").lower()
    if u in ("s", "sec", "secs", "second", "seconds", '"'):
        return "time", 1
    if u in ("min", "mins", "minute", "minutes", "'"):
        return "time", 60
    if u in ("h", "hour", "hours"):
        return "time", 3600
    if u in ("m", "meter", "meters", "metre", "metres"):
        return "distance", 1
    if u in ("km", "k"):
        return "distance", 1000
    if u in ("mi", "mile", "miles"):
        return "distance", 1609.34
    if u in ("cal", "cals", "calories"):
        return "cal", 1
    return "reps", 1


def find_amount(text):
    """First time/distance amount in text -> (kind, value, match) or None. Ranges use the low end."""
    m = AMOUNT_RE.search(text)
    c = CLOCK_RE.search(text)
    if c and (not m or c.start() < m.start()):
        return "time", int(c[1]) * 60 + int(c[2]), c
    if m:
        kind, mult = unit_kind(m[3])
        if kind in ("time", "distance"):
            return kind, float(m[1]) * mult, m
    return None


def zone_hr(z, cfg):
    t = cfg.get("threshold_hr")
    if t:
        bands = {1: (0.65, 0.85), 2: (0.85, 0.89), 3: (0.90, 0.94), 4: (0.95, 0.99), 5: (1.0, 1.06)}
        lo, hi = bands[z]
        return [round(t * lo), round(t * hi)]
    mx = cfg.get("max_hr", 200)
    return [round(mx * (0.4 + 0.1 * z)), round(mx * (0.5 + 0.1 * z))]


def find_target(text, cfg, warnings):
    """Pace / HR target in a run step -> (dict, text without it)."""
    t = text

    def cut(m):
        return t[:m.start()] + " " + t[m.end():]

    m = re.search(r"(?:@|\bat\b|\bpace\b)?\s*(\d{1,2}:\d{2})\s*(?:-|–|to)\s*(\d{1,2}:\d{2})\s*(?:/km|min/km|/k|per km)?", t, re.I)
    if m and (re.search(r"@|\bat\b|pace|/km|/k|per km", m[0], re.I)):
        return {"pace": [m[1], m[2]]}, cut(m)
    m = re.search(r"(?:@|\bat\b)\s*(\d{1,2}:\d{2})\s*(?:/km|min/km|/k|per km)?|(\d{1,2}:\d{2})\s*(?:/km|min/km|/k|per km)", t, re.I)
    if m:
        p = parse_clock(m[1] or m[2])
        return {"pace": [fmt_clock(p - 5), fmt_clock(p + 5)]}, cut(m)
    m = re.search(r"(?:@\s*)?(?:hr|heart rate|bpm)\s*:?\s*(\d{2,3})\s*(?:-|–|to)\s*(\d{2,3})|(\d{2,3})\s*(?:-|–|to)\s*(\d{2,3})\s*bpm", t, re.I)
    if m:
        lo, hi = (m[1], m[2]) if m[1] else (m[3], m[4])
        return {"hr": [int(lo), int(hi)]}, cut(m)
    m = re.search(r"(?:@\s*)?(?:hr|heart rate)\s*(?:<|under|below|max|cap)\s*(\d{2,3})", t, re.I)
    if m:
        return {"hr": [100, int(m[1])]}, cut(m)
    m = re.search(r"(?:@\s*)?\b(?:z|zone)\s*([1-5])\b", t, re.I)
    if m:
        if not cfg.get("threshold_hr"):
            warnings.append(f"zone {m[1]} uses max HR {cfg.get('max_hr', 200)} - run `garmin-coach thresholds` for better zones")
        return {"hr": zone_hr(int(m[1]), cfg)}, cut(m)
    m = re.search(r"(?:@\s*|\bat\s+)?\b(t[- ]?pace|threshold pace|threshold|lt pace)\b", t, re.I)
    if m:
        tp = cfg.get("threshold_pace")
        if tp:
            p = parse_clock(tp)
            return {"pace": [fmt_clock(p - 5), fmt_clock(p + 8)]}, cut(m)
        warnings.append("'T-pace' used but no threshold pace known - run `garmin-coach thresholds`")
    return {}, t


# ----------------------------------------------------------------- line helpers

BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦·>]+|\d+[.)])\s*")
RUN_WORDS = re.compile(r"\b(run|running|jog|jogging|strides?|tempo|threshold|t[- ]?pace|fartlek|long run|"
                       r"intervals?|track|hill repeats?|/km|min/km|pace)\b", re.I)
RUN_HINTS = re.compile(r"@\s*\d{1,2}:\d{2}|\d{1,2}:\d{2}\s*/\s*k|\b(?:hr|heart rate)\s*[<\d]|@\s*z(?:one)?\s*[1-5]\b|"
                       r"^\d+\s*(?:x|×)\s*\d+(?:\.\d+)?\s*(?:m|km|k)\b", re.I)
STRENGTH_LABELS = re.compile(r"^(warm[- ]?up|cool[- ]?down|mobility|activation|superset|tri[- ]?set|giant set|"
                             r"circuit|finisher|emom|amrap|metcon|\d+\s*rounds?|rounds?)\b", re.I)


def split_note(line):
    """Pull out (parentheses) and trailing sentences as a note. Returns (core, note)."""
    notes = []
    for m in re.finditer(r"\(([^)]*)\)?", line):
        notes.append(m[1].strip())
    core = re.sub(r"\([^)]*\)?", " ", line)
    parts = re.split(r"(?<=[.!?])\s+(?=[@A-Z~])", core, maxsplit=1)
    if len(parts) == 2:
        core, extra = parts
        notes.append(extra.strip())
    return core.strip().rstrip("."), "; ".join(n for n in notes if n)


def split_label(text):
    m = re.match(r"^\s*([A-Za-z][A-Za-z0-9 \-]{0,30}?)\s*:\s*(.*)$", text)
    return (m[1].strip(), m[2].strip()) if m else ("", text.strip())


@dataclass
class Line:
    text: str
    indent: int
    bullet: bool


@dataclass
class Draft:
    name: str = ""
    date: date | None = None
    sport: str | None = None
    lines: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    default_rest: str = "lap"
    off: bool = False
    header_step: str = ""


@dataclass
class Plan:
    specs: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


# ----------------------------------------------------------------- run parsing

def step_type_for(text, default="interval"):
    t = text.lower()
    if re.search(r"\bwarm[- ]?up\b|\bwu\b", t):
        return "warmup"
    if re.search(r"\bcool[- ]?down\b|\bcd\b", t):
        return "cooldown"
    if re.search(r"\b(rest|walk|stand)\b", t):
        return "rest"
    return default


def amount_fields(kind, value):
    return {"time": fmt_clock(value)} if kind == "time" else {"distance": round(value)}


def parse_run_part(text, cfg, warnings, default_type="interval"):
    target, rest = find_target(text, cfg, warnings)
    amt = find_amount(rest)
    step = {"type": step_type_for(text, default_type)}
    if amt:
        step.update(amount_fields(amt[0], amt[1]))
    step.update(target)
    step["note"] = text.strip()
    return step, bool(amt or target)


def parse_run_line(text, cfg, warnings):
    """One line of a run workout -> list of steps (may be a repeat)."""
    core, note = split_note(text)
    label, body = split_label(core)
    default_type = step_type_for(label) if label else "interval"
    m = re.match(r"^(\d+)\s*(?:x|×|\*|rounds?\s+of|sets?\s+of)\s*(.+)$", body, re.I)
    if m:
        reps = int(m[1])
        parts = re.split(r"\s*(?:,|;|/|\bwith\b|\bw/|\bthen\b|\+)\s*", m[2], maxsplit=1, flags=re.I)
        work, has = parse_run_part(parts[0], cfg, warnings, "interval")
        work["type"] = "interval"
        steps = [work]
        if len(parts) > 1 and parts[1].strip():
            rec, _ = parse_run_part(parts[1], cfg, warnings, "recovery")
            if rec["type"] == "interval":
                rec["type"] = "recovery"
            steps.append(rec)
        elif re.search(r"stride", parts[0], re.I):
            steps.append({"type": "recovery", "note": "walk back - press LAP"})
        if note:
            work["note"] = f"{work['note']} ({note})"
        return [{"repeat": reps, "steps": steps}]
    parts = [p for p in re.split(r"\s*,\s*", body) if p.strip()] if "," in body else [body]
    out = []
    for p in parts:
        if re.match(r"^\d+\s*(?:x|×|\*)", p.strip(), re.I):
            sub = parse_run_line(p, cfg, warnings)
            out.extend(sub)
            continue
        step, has = parse_run_part(p, cfg, warnings, default_type)
        if not has and not label and default_type == "interval" and not RUN_WORDS.search(p) \
                and not re.search(r"drill|stride|jog|walk", p, re.I):
            continue  # plain sentence: not a step
        out.append(step)
    if out and note:
        out[-1]["note"] = f"{out[-1]['note']} ({note})"
    return out


# ----------------------------------------------------------------- strength parsing

def seconds_text(v, unit):
    if ":" in v:
        return fmt_clock(parse_clock(v))
    x = float(v)
    u = (unit or "").lower()
    if u in ("min", "mins", "minute", "minutes", "m", "'") or (not u and x < 10):
        x *= 60
    return fmt_clock(x)


def parse_strength_item(text, default_rest, fallback="Total Body"):
    """'Flat DB bench press: 4 x 8 @ 22.5kg rest 90s' -> exercise step dict."""
    core, note = split_note(text)
    item = {}
    m = REST_RE.search(core)
    if m:
        item["rest"] = seconds_text(m[1], m[2])
        core = core[:m.start()] + " " + core[m.end():]
    m = WEIGHT_RE.search(core)
    if m:
        kg = float(m[1]) * (0.4536 if m[2].lower().startswith("lb") else 1)
        item["weight"] = round(kg, 1)
        core = core[:m.start()] + " " + core[m.end():]
    m = SETS_RE.search(core)
    extra = []
    if m:
        item["sets"] = int(m[1])
        val = float(m[3] or m[2])
        kind, mult = unit_kind(m[4])
    else:
        m = re.search(r"(\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:\.\d+)?))?\s*"
                      r"(seconds|second|secs|sec|s|minutes|minute|mins|min|metres|meters|m|km|calories|cals|cal|"
                      r"reps|rep|'|\")?(?![a-z\d])", core, re.I)
        if m:
            val = float(m[1]) if (m[3] or "").lower() not in ("reps", "rep", "") else float(m[2] or m[1])
            kind, mult = unit_kind(m[3])
    if m:
        if kind == "reps":
            item["reps"] = int(val)
        elif kind == "time":
            item["time"] = fmt_clock(val * mult)
        else:
            extra.append(m[0].strip())  # distance / calories -> press LAP when done
        name_text = core[:m.start()] + " " + core[m.end():]
    else:
        name_text = core
    if re.search(r"/\s*side|each\s*(side|leg|arm)|per\s*side", text, re.I):
        extra.append("per side")
    name_text = re.sub(r"\b(rounds?|sets?|reps?)\b|[:\-–,@]", " ", name_text, flags=re.I)
    name_text = re.sub(r"/\s*side|each\s*(side|leg|arm)|per\s*side", " ", name_text, flags=re.I).strip()
    ex, quality = match_exercise(name_text, fallback)
    item = {"exercise": ex, **item}
    if item.get("sets", 1) > 1:
        item.setdefault("rest", default_rest)
    full_note = text.strip()
    item["note"] = full_note
    item["_match"] = quality
    item["_name"] = name_text
    return item


def parse_strength_lines(lines, draft, warnings):
    steps, i = [], 0
    while i < len(lines):
        ln = lines[i]
        i += 1
        if not ln.text:
            continue
        core, _ = split_note(ln.text)
        label, body = split_label(core)
        lab = (label or core).lower()
        if re.match(r"^rest\b", core, re.I) and not SETS_RE.search(core):
            m = REST_RE.search(core)
            steps.append({"type": "rest", "time": seconds_text(m[1], m[2])} if m else {"type": "rest"})
            continue
        if label and STRENGTH_LABELS.match(label) or (not label and STRENGTH_LABELS.match(core)
                                                       and re.search(r"superset|circuit|rounds?", core, re.I)):
            rounds_m = re.search(r"(\d+)\s*(?:rounds?|x)\b|\bx\s*(\d+)|(\d+)\s*sets?\b", label or core, re.I)
            rounds = int(next(g for g in rounds_m.groups() if g)) if rounds_m else None
            if re.match(r"warm|cool|mobility|activation", lab):
                fb = "Warm-up"
                for part in [p for p in re.split(r"\s*,\s*", body) if p.strip()]:
                    s = parse_strength_item(part, "lap", fallback=fb)
                    if s["_match"] == "unknown":
                        s["exercise"] = fb
                    steps.append(s)
                continue
            if body and not re.fullmatch(r"[\d\sxrounds]*", body, re.I):
                items = [parse_strength_item(p, "lap") for p in re.split(r"\s*(?:/|\+|&|;|,)\s*", body) if p.strip()]
            else:
                items = []
                while i < len(lines) and lines[i].text and (lines[i].indent > ln.indent
                                                             or (lines[i].bullet and not ln.bullet)):
                    items.append(parse_strength_item(lines[i].text, "lap"))
                    i += 1
            if not items:
                warnings.append(f"'{ln.text.strip()}' has no exercises under it (indent them, or put them on the same line split by /)")
                continue
            rest_m = REST_RE.search(core)
            n = rounds or max(it.get("sets", 1) for it in items)
            for it in items:
                it.pop("sets", None)
                it.pop("rest", None)
            block = items + [{"type": "rest", "time": seconds_text(rest_m[1], rest_m[2])} if rest_m else {"type": "rest"}]
            steps.append({"repeat": n, "steps": block, "note": ln.text.strip()})
            continue
        if not re.search(r"[a-z]", core, re.I):
            continue
        item = parse_strength_item(ln.text, draft.default_rest)
        if item["_match"] in ("unknown", "guess", "fuzzy") and not any(k in item for k in ("reps", "time", "sets")) \
                and not re.search(r"\d", core):
            draft.notes.append(ln.text.strip())  # a sentence, not an exercise
            continue
        steps.append(item)
    return steps


# ----------------------------------------------------------------- whole files

def classify(draft):
    if draft.sport:
        return draft.sport
    run = strength = 0
    if RUN_WORDS.search(draft.name):
        run += 1
    for ln in draft.lines:
        if not ln.text:
            continue
        if RUN_WORDS.search(ln.text) or RUN_HINTS.search(ln.text):
            run += 1
        elif re.match(r"^(warm|cool)", ln.text, re.I):
            continue
        elif SETS_RE.search(ln.text) or STRENGTH_LABELS.match(split_note(ln.text)[0]):
            strength += 1
    if draft.header_step and RUN_WORDS.search(draft.header_step):
        run += 1
    return "running" if run and (strength == 0 or run > 2 * strength) else "strength_training"


def walk_steps(steps):
    for s in steps:
        if "repeat" in s:
            yield from walk_steps(s["steps"])
        else:
            yield s


def finish(draft, cfg, plan):
    while draft.lines and not draft.lines[-1].text:
        draft.lines.pop()
    if draft.off:
        plan.skipped.append(f"{draft.date or ''} {draft.name or 'day'}: rest/off day - nothing to push".strip())
        return
    if not draft.lines and not draft.header_step:
        if draft.name or draft.date:
            plan.skipped.append(f"{draft.date or ''} {draft.name}: no steps".strip())
        return
    sport = classify(draft)
    lines = ([Line(draft.header_step, 0, False)] if draft.header_step else []) + draft.lines
    w = []
    if sport == "running":
        steps = []
        for ln in lines:
            if not ln.text:
                continue
            got = parse_run_line(ln.text, cfg, w)
            if got:
                steps.extend(got)
            else:
                draft.notes.append(ln.text.strip())
    else:
        steps = parse_strength_lines(lines, draft, w)
    if not steps:
        plan.skipped.append(f"{draft.date or ''} {draft.name}: couldn't find any steps".strip())
        return
    name = draft.name or ("Run" if sport == "running" else "Strength")
    spec = {"name": name, "date": draft.date.isoformat() if draft.date else None, "sport": sport, "steps": steps}
    if draft.notes:
        spec["description"] = " | ".join(draft.notes)[:500]
    for s in walk_steps(steps):
        if s.get("_match") in ("guess", "unknown", "fuzzy"):
            w.append(f"'{s['_name']}' -> {s['exercise']} ({s['_match']} match - check it)")
    if not draft.date:
        w.append("no date - it will be added to your Garmin workout library but not scheduled")
    plan.warnings.extend(f"{name}: {x}" for x in w)
    plan.specs.append(spec)


def parse_text(text, cfg=None, today=None, filename=""):
    cfg = cfg or {}
    today = today or date.today()
    plan = Plan()
    week_start = None
    fname_date, _ = find_date(Path(filename).stem, today) if filename else (None, "")
    draft = Draft(date=fname_date if fname_date and not re.search(DAY_RE, Path(filename).stem, re.I) else None)
    started = False
    for raw in text.splitlines():
        if not raw.strip():
            if draft.lines and draft.lines[-1].text:
                draft.lines.append(Line("", 0, False))  # blank line ends a circuit block
            continue
        indent = len(raw) - len(raw.lstrip(" \t").replace("\t", "    ")) if raw[:1] in " \t" else 0
        bullet = bool(BULLET_RE.match(raw))
        stripped = BULLET_RE.sub("", raw).strip() if bullet else raw.strip()
        low = stripped.lower()
        m = re.match(r"^(week|week of|week starting)\s*:?\s*(.+)$", low)
        if m and not bullet:
            d, _ = find_date(m[2], today)
            if d:
                week_start = d - timedelta(days=d.weekday())
                continue
        m = re.match(r"^(date|day|type|sport|name|title|notes?|rest)\s*:\s*(.*)$", stripped, re.I)
        if m and not (m[1].lower() == "rest" and re.search(r"[a-z]{3,}", m[2]) and not re.match(r"lap", m[2], re.I)):
            key, val = m[1].lower(), m[2].strip()
            if key in ("date", "day"):
                draft.date, _ = find_date(val, today, week_start)
            elif key in ("type", "sport"):
                draft.sport = "running" if re.match(r"run|jog", val, re.I) else "strength_training"
            elif key in ("name", "title"):
                draft.name = val
            elif key.startswith("note"):
                draft.notes.append(val)
            elif key == "rest":
                rm = re.match(r"(\d+:\d{2}|\d+(?:\.\d+)?)\s*([a-z']*)", val, re.I)
                draft.default_rest = seconds_text(rm[1], rm[2]) if rm else "lap"
            continue
        if not bullet and indent == 0 and HEADER_START.match(stripped):
            if started or draft.lines:
                finish(draft, cfg, plan)
            started = True
            head = stripped.lstrip("#").strip()
            d, rest = find_date(head, today, week_start)
            rest = re.sub(r"^[\s:\-–|,]+|[\s:\-–|,]+$", "", re.sub(r"\s+", " ", rest))
            draft = Draft(date=d)
            if re.match(r"^(off|rest|rest day|day off|recovery day)\b", rest, re.I):
                draft.off, draft.name = True, rest
                continue
            core, _ = split_note(rest)
            if find_amount(core) or SETS_RE.search(core):
                cut = re.search(r"\d", core)
                draft.name = core[:cut.start()].strip(" :-–") if cut else core
                draft.header_step = rest
            else:
                draft.name = rest
            continue
        if stripped.startswith("@") and not re.match(r"@\s*[\dzZ]", stripped):
            draft.notes.append(stripped)
            continue
        draft.lines.append(Line(stripped, indent, bullet))
    finish(draft, cfg, plan)
    return plan


def load_plan(path, cfg=None, today=None):
    """.txt/.md -> parse text; .json -> specs as written."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
        plan = Plan(specs=data if isinstance(data, list) else [data])
        for s in plan.specs:
            s.setdefault("date", None)
        return plan
    return parse_text(p.read_text(encoding="utf-8-sig"), cfg, today, filename=p.name)


# ----------------------------------------------------------------- human-readable preview

def describe_step(s, ind="    "):
    if "repeat" in s:
        out = [f"{ind}{s['repeat']} rounds:"]
        for c in s["steps"]:
            out += describe_step(c, ind + "   ")
        return out
    if "exercise" in s:
        amt = f"{s['sets']} x " if s.get("sets", 1) > 1 else ""
        amt += f"{s['reps']} reps" if "reps" in s else s.get("time", "until LAP")
        if s.get("weight"):
            amt += f" @ {s['weight']} kg"
        if s.get("sets", 1) > 1:
            amt += f", rest {'until LAP' if s.get('rest') == 'lap' else s.get('rest')}"
        flag = "  ⚠ check" if s.get("_match") in ("guess", "unknown", "fuzzy") else ""
        return [f"{ind}{s['exercise']:<30} {amt}{flag}   ← \"{s.get('note', '')}\""]
    amt = s.get("time") or (f"{s['distance']} m" if "distance" in s else "until LAP")
    tgt = f" @ {s['pace'][0]}-{s['pace'][1]}/km" if "pace" in s else (f" @ HR {s['hr'][0]}-{s['hr'][1]}" if "hr" in s else "")
    return [f"{ind}{s.get('type', 'interval'):<9} {amt}{tgt}   ← \"{s.get('note', '')}\""]


def describe(plan):
    out = []
    for w in plan.specs:
        out.append(f"\n{w['name']}  [{w.get('sport', 'running').replace('_', ' ')}]  {w.get('date') or 'no date'}")
        for s in w["steps"]:
            out += describe_step(s)
        if w.get("description"):
            out.append(f"    notes: {w['description']}")
    for s in plan.skipped:
        out.append(f"\n(skipped) {s}")
    if plan.warnings:
        out.append("\nWarnings:")
        out += [f"  ⚠ {x}" for x in plan.warnings]
    return "\n".join(out)
