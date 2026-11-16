# Writing workouts for the watch (trainer guide)

Write the week like you'd write it on WhatsApp. Save it as a `.txt` file and drop it in the shared folder (or send it to your athlete). It shows up on their Garmin watch, with each exercise, its sets × reps, the weights, rest timers and run paces.

## Example

```
week: 23 Nov

Mon - Upper body
- Warm-up: 5 min easy cardio, band pull-aparts, scap push-ups
- DB bench press 4 x 8 @ 22.5kg rest 90s
- Chin-ups 4 x 6
- Superset: face pulls 3 x 15 / EZ-bar curls 3 x 10
- Plank 3 x 45s

Thu - Threshold
- Warm-up: 12 min easy jog, drills, 4 x 20 sec strides
- 4 x 6 min @ T-pace, 1 min jog
- Cool-down 8 min

Fri off

Sat - Functional
Circuit 4 rounds rest 2 min:
    - Run 1 km
    - Wall balls 20
    - Sled push 25m

Sun - Long run 50 min @ z2
```

## The rules

**A new day starts** with a line beginning with a day or date, like `Mon`, `Thursday`, `Thu 19 Nov`, `23 Nov` or `2026-11-23`. You can also start it with `#`. Whatever follows is the workout name. `Fri off` and `Rest day` are skipped.

**Put `week: 23 Nov` at the top** so `Mon`…`Sun` land in the right week. Without it, a day name means the next one coming up.

### Strength
| You write | Watch shows |
|---|---|
| `Back squat 4 x 6` | 4 sets of 6 reps |
| `... @ 60kg` (or `lb`) | the target weight |
| `... rest 90s` / `rest 2 min` | a rest timer between sets. Without it, rest runs until you press LAP. |
| `Plank 3 x 45s` | 3 timed sets |
| `Sled push 4 x 15m`, `Row 500m`, `Bike 20 cal` | sets that end when you press LAP (distance and calories go in the note) |
| `Superset: A 3 x 10 / B 3 x 12` | A → B → rest, 3 rounds |
| `Circuit 4 rounds rest 2 min:` then **indented** lines | a circuit. Leave a blank line after it. |
| `Warm-up: a, b, c` | each item as its own step |
| `Seal row or inverted row` | the alternative that best matches Garmin's list |
| `rest: 90s` on its own line | the default rest for that day |

Short forms work: DB, BB, KB, RDL, OHP, pull-ups, pulldown, wall balls, SkiErg, sled push/pull, farmers carry, burpee broad jumps, and more. Anything in brackets `(like this)` becomes a note on the watch.

### Running
| You write | Watch shows |
|---|---|
| `Warm-up 12 min`, `Cool-down 8 min` | warm-up / cool-down steps |
| `4 x 6 min @ T-pace, 1 min jog` | 4 rounds of work + recovery |
| `6 x 400m @ 5:00-5:10/km, 200m jog` | pace alerts on the reps |
| `3 x 1 km @ 5:30, 2 min rest` | the pace ±5 s |
| `@ T-pace` / `@ threshold` | the athlete's own threshold pace from their Garmin |
| `@ z2` | the athlete's own heart-rate zone 2 |
| `hr 140-155`, `hr < 150` | a heart-rate alert |
| `drills`, `4 x 20 sec strides` | a step that waits for LAP; strides get a walk-back recovery |

**Notes for the athlete:** start a line with `note:` or `@`, or just write a normal sentence. A sentence with no exercise in it is kept as a note, not turned into a step.

## Before it goes to the watch
The athlete (or you) can run `garmin-coach check week.txt` to see exactly how every line was read. Nothing is sent. If an exercise name is only a guess, it's flagged `⚠ check`, and the shared-folder inbox **won't push that file**. It goes into `failed/` with a note saying which line to fix.
