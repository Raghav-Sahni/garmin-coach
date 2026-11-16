def parse_clock(s):
    """'01:07:37' / '00:01:27.7' / '6:51' / '90' -> seconds."""
    if s is None or str(s).strip() in ("--", ""):
        return None
    sec = 0.0
    for p in str(s).strip().split(":"):
        sec = sec * 60 + float(p)
    return sec


def fmt_clock(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_pace(sec_per_km):
    return fmt_clock(sec_per_km) if sec_per_km else "-"


def fmt_dur(sec):
    h, rem = divmod(int(sec), 3600)
    return f"{h}h{rem // 60:02d}" if h else f"{rem // 60}m"


def parse_num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("'", "")
    if s in ("", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
