# Garmin Coach ⌚

**Paste your trainer's workout message, click a button, and it's on your Garmin watch.**

Your trainer sends you something like this on WhatsApp:

```
Thu - Threshold run
- Warm-up: 12 min easy jog, drills, 4 x 20 sec strides
- 4 x 6 min @ T-pace, 1 min jog
- Cool-down 8 min

Sat - Upper body
- DB bench press 4 x 8 @ 20kg rest 90s
- Chin-ups 4 x 6
- Superset: face pulls 3 x 15 / curls 3 x 10
```

Garmin Coach turns it into proper workouts on your watch:

- 🏃 **Runs** get each part as a step (warm-up → intervals → recovery → cool-down). The watch beeps if you go too fast or too slow. "T-pace" and "zone 2" are set from **your own** Garmin numbers.
- 🏋️ **Gym sessions** show each exercise by name, with sets, reps, target weight and a rest timer. Garmin also records what you actually lifted.

It's free, needs no subscription, and runs on your own computer.

---

## 1. Download

➡️ **[Download GarminCoach.exe](../../releases/latest)** (Windows 10 / 11, about 17 MB)

There's nothing to install. Save the file anywhere, for example your Desktop, and double-click it.

> **"Windows protected your PC"?** Windows shows this for any new app that isn't from a big company. Click **More info → Run anyway**. You only need to do this once.

## 2. Connect your Garmin account (once)

1. Click **Log in to Garmin** (top right).
2. Enter the same email and password you use in the Garmin Connect app.
3. If Garmin texts or emails you a code, type it in.

That's it. You stay logged in on that computer for months.

## 3. Send a workout to your watch

1. Copy your trainer's message and paste it into the big box. Or click **Open file…** if they sent a file.
2. Read the preview underneath. It shows exactly what will go on your watch.
3. Click **Send to my watch**.
4. Open the **Garmin Connect app** on your phone so your watch syncs.

The workouts appear on the right days in your Garmin calendar. On the watch, open them under **Training → Workouts** (or the watch suggests today's).

**Sent something by mistake?** Keep the same text in the box and click **Undo**.

### If you see an orange ⚠ line
It means an exercise name wasn't clear, so the app made its best guess. Reword that line, for example "DB bench press" instead of "chest thing", and the preview updates by itself.

---

## For trainers: how to write the plan

Write it the way you already do. The important bits:

| Write | It becomes |
|---|---|
| `Mon - Legs` or `Thu 19 Nov - Run` | starts a new day |
| `Fri off` | rest day (skipped) |
| `Back squat 4 x 6 @ 60kg rest 2 min` | 4 sets × 6 reps, 60 kg, 2-min rest timer |
| `Plank 3 x 45s` | 3 timed sets |
| `Superset: face pulls 3 x 15 / curls 3 x 10` | the two exercises back to back, 3 rounds |
| `4 x 6 min @ T-pace, 1 min jog` | intervals at the athlete's own threshold pace |
| `6 x 400m @ 5:00-5:10/km, 200m jog` | intervals with a pace alert |
| `Long run 50 min @ z2` | heart-rate zone 2 alert |
| `(anything in brackets)` | a note shown on the watch |

Common gym short forms work (DB, KB, RDL, pull-ups, wall balls, SkiErg, sled push…). The full guide is in **[TRAINER_GUIDE.md](TRAINER_GUIDE.md)**.

---

## Let your trainer send workouts directly (optional)

Your trainer **never needs your password** for this.

1. Make a shared folder you can both open, such as Google Drive, Dropbox or OneDrive.
2. In the app, go to the **Trainer folder** tab, click **Choose folder…**, then **Start**.
3. Your trainer saves each plan as a `.txt` file in that folder.

While the app is open, it checks the folder every 10 minutes and sends new plans to your watch:
- ✅ Sent plans move into a `pushed` folder.
- ⚠️ A plan with an unclear exercise name is **not** sent. It moves into a `failed` folder with a note saying what to fix.
- 📝 `log.txt` in the folder lists everything that happened.

---

## See how your training is going (optional)

The **My training** tab downloads your last 90 days from Garmin and shows:
- hours, running distance and sessions each week
- whether your easy runs were really easy
- whether you're getting fitter (pace compared with heart rate)
- resting heart rate, HRV, sleep and VO2max trends

Click **Copy report** to send it to your coach, or paste it into an AI assistant and ask for advice.

---

## Questions

**Is my password safe?**
It's only ever sent to Garmin's own login. The app then keeps a login key on your computer, in your user folder under `.garmin-coach`. Your password is saved only if you tick "Remember my password".

**Which watches work?**
Any Garmin that supports workouts: most Forerunner, Fenix, Epix, Venu, Instinct and similar models.

**The watch counted the wrong number of reps.**
Rep counting isn't perfect, especially for pull-ups and cable exercises. You can correct the number (and add the weight) on the watch after each set.

**It suddenly can't log in.**
Garmin sometimes changes its login system. Download the newest version of the app from the link above.

**Mac?**
There's no Mac app yet. Mac users can run it with Python. See the next section.

---

## For developers

Garmin Coach is a Python package with a command-line tool as well as the app.

```bash
pip install git+https://github.com/Raghav-Sahni/garmin-coach.git
garmin-coach setup                 # log in
garmin-coach check week.txt        # preview, sends nothing
garmin-coach push week.txt         # send to Garmin
garmin-coach remove week.txt       # undo
garmin-coach inbox FOLDER --watch 15
garmin-coach sync && garmin-coach report
garmin-coach-app                   # open the desktop app
```

Add `--profile NAME` to manage several Garmin accounts, for example a trainer handling multiple athletes.

Build the Windows app with `pip install pyinstaller` and then `packaging\build_exe.bat`. Run the tests with `pip install -e .[dev]` and then `pytest`.

Data lives in `~/.garmin-coach/profiles/<name>/`. Built on [python-garminconnect](https://github.com/cyberjunky/python-garminconnect). Not affiliated with Garmin. MIT licensed.
