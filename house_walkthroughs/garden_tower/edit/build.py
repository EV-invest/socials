#!/usr/bin/env python3
"""Garden Tower: one continuous take per price tier, behind a short intro.

Three apartments, all on floor 14, one per price point in the Block A list
(msg 290). Each is a single uncut take -- the only cuts in the film are the
intro montage and the dips to black between units.
"""
import subprocess, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, WORK, OUT = ROOT / "raw", ROOT / "edit/work", ROOT / "edit/out"
PLAN = ROOT / "assets/floorplan_blockA.jpg"
FONTS = "/nix/store/mgard6209ac2wlp8kwmns8a15ydqszwm-google-fonts-0-unstable-2026-03-13/share/fonts/truetype"
# Poppins has no Vietnamese diacritics; Be Vietnam Pro does
BOLD, LIGHT = f"{FONTS}/BeVietnamPro-SemiBold.ttf", f"{FONTS}/BeVietnamPro-Light.ttf"

# warm the clinical white walls, lift the shadows, keep the sky honest
GRADE = ("eq=contrast=1.06:saturation=1.12:gamma=1.03:gamma_r=1.01:gamma_b=0.98,"
         "colorbalance=rs=0.02:bs=-0.03:rm=0.03:bm=-0.03:rh=0.01:bh=-0.01,"
         "unsharp=5:5:0.4:5:5:0.0")

INTRO = [
    (259, 64.6, 4.0, "corner glass, lagoon panorama"),
    (254, 60.3, 4.4, "lagoon and Thi Nai bridge"),
    (257, 62.4, 3.4, "mountains, low-rise neighbourhood"),
    (254, 33.0, 4.2, "block A corridor"),
]
PLAN_DUR = 8.0

# Transit, blank wall and dwell-too-long stretches, timed off a 2s contact sheet of
# each take. Speeding them beats cutting them: the take stays unbroken, and the
# viewer still reads the floor as one connected space. (start, end, rate)
RAMPS = {
    242: [],
    248: [(2.5, 7.5, 2.5),    # entry corridor
          (28.0, 36.0, 3.0),  # blank wall / door run between living and bed 2
          (47.5, 52.0, 2.5),  # hallway to bathroom
          (56.0, 60.0, 2.5),  # bathroom dwell
          (88.0, 95.0, 3.0)], # wardrobe run, already seen
    250: [(2.5, 7.5, 2.5),
          (28.0, 36.0, 3.0),
          (46.0, 52.0, 2.5),
          (55.0, 60.5, 2.5),
          (68.5, 84.0, 3.0),   # utility + wrapped door, longest dead stretch in the set
          (96.0, 102.5, 3.0),
          (103.5, 108.8, 2.5)],
}
# (msg_id, in, dur, unit, price) -- one unbroken take each
UNITS = [
    (242, 0.0, 33.6, "A-14-10", "1.190 BN VND"),
    (248, 0.0, 99.8, "A-14-15", "1.219 BN VND"),
    (250, 0.0, 108.8, "A-14-12", "1.404 BN VND"),
]
OUTRO = (259, 9.8, 5.0, "window onto the lagoon")

# unit footprints on the block A plan, in source-image pixels
UNIT_BOX = {"A-14-10": (500, 161, 584, 272), "A-14-15": (748, 161, 828, 272), "A-14-12": (586, 290, 668, 403)}
INSET_CROP = "880x265+60+150"  # the slab, without the title and the sales copy
INSET_IN, INSET_OUT = 0.9, 9.8
# The takes are 60fps and the film is 30, so an output frame advances 2*rate source
# frames. Only rates that make that a whole number sample evenly -- 1.24x steps
# 2,3,2,3 frames and the cadence stutter is exactly what reads as jank.
STEPS = (1.0, 1.5, 2.0, 2.5, 3.0)
SHOULDER = 0.3   # seconds held at each intermediate rate on the way in and out
MIN_HOLD = 1.0   # seconds a ramp must spend at its target rate to be worth ramping
WARM = 18        # source frames of decode lead-in, so tmix reaches a cut with a full window

# (start_offset_within_segment, dur, big, small) keyed by segment index
INTRO_CARDS = {
    0: (0.6, 4.4, "GARDEN TOWER", "AN PHÚ THỊNH  ·  QUY NHƠN"),
    1: (0.4, 3.6, "ĐẦM THỊ NẠI", "THE LAGOON AND THỊ NẠI BRIDGE"),
    2: (0.3, 2.8, "QUY NHƠN ĐÔNG", "THE NEW EAST SIDE OF THE CITY"),
    3: (0.3, 3.6, "BLOCK A", "18 APARTMENTS PER FLOOR"),
}
UNIT_SUB = "66 m²  ·  2 BEDROOM  ·  {}"
OUTRO_CARD = ("GARDEN TOWER", "ENQUIRIES  ·  @valeratrades")

AMBIENT_SRC, AMBIENT_DB = 255, -26
DIP = 0.6  # dip to black between units


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"FAILED: {' '.join(cmd[:14])}...\n{r.stderr[-2500:]}")


def src_of(msg_id):
    hits = sorted(RAW.glob(f"{msg_id:04d}_*.MOV"))
    assert len(hits) == 1, f"expected exactly one clip for msg {msg_id}, got {hits}"
    return hits[0]


def dt(font, text, x, y, size, colour="white", box=None, alpha=None):
    # the box alpha rides the text alpha, so the scrim fades with the card
    b = f":box=1:boxcolor={box}:boxborderw=16" if box else ""
    a = f":alpha='{alpha}'" if alpha else ""
    return (f"drawtext=fontfile={font}:text='{text}':x={x}:y={y}:fontsize={size}"
            f":fontcolor={colour}{b}{a}")


def expand(dur, ramps):
    """Ramps with eased shoulders, plus the 1x gaps, as contiguous (first, last, rate) source frames.

    A step straight from 1x to 2x reads as a glitch however clean the frames are, so each
    ramp climbs and descends through the intermediate rates in STEPS.

    Every piece spans a whole number of 2*rate source frames, so it renders to a whole
    number of output frames. A piece that ends part-way through a step leaves its last
    frame a hair short of the seam, and the film shows a duplicate at every join.
    """
    plan, t = [], 0.0  # (rate, nominal length in source frames)
    for a, b, r in sorted(ramps):
        assert a >= t and b <= dur, f"ramp {(a, b)} overlaps or overruns {dur}"
        assert r in STEPS, f"rate {r} does not land on a whole number of source frames"
        if a > t:
            plan.append((1.0, (a - t) * 60))
        ladder = [x for x in STEPS if 1.0 < x < r]
        # a ramp too short to sit at its target rate is all shoulder: it reads as cheap and
        # saves nothing. Leave the stretch alone instead of squeezing the ease into it.
        assert b - a >= 2 * SHOULDER * len(ladder) + MIN_HOLD, \
            f"ramp {(a, b)} is too short to reach {r}x -- drop it"
        sh = SHOULDER * 60 if ladder else 0.0
        plan += ([(x, sh) for x in ladder]
                 + [(r, (b - a) * 60 - 2 * sh * len(ladder))]
                 + [(x, sh) for x in reversed(ladder)])
        t = b
    if t < dur:
        plan.append((1.0, (dur - t) * 60))

    total, out, f = round(dur * 60), [], 0
    for i, (r, n) in enumerate(plan or [(1.0, total)]):
        step = int(2 * r)
        # the last piece absorbs the rounding, so a take never runs past its own footage
        n = (total - f) // step if i == len(plan) - 1 else max(1, round(n / step))
        assert n >= 1, f"piece at {r}x quantised to nothing"
        out.append((f, f + n * step, r))
        f += n * step
    return out


def blur_frames(rate):
    """Source frames to average per output frame -- a full 360-degree shutter at this rate.

    Averaging 2*rate frames makes consecutive output frames tile the source with neither
    gap nor overlap. Above 1x the displacement per output frame is large enough that an
    exactly-tiling window still strobes, so the window is opened two frames wider -- a
    shutter past 360 degrees, paid for in a little softness on the parts nobody dwells on.
    """
    n = 2 * rate
    assert n == int(n), f"rate {rate} does not tile the source"
    return int(n) + (2 if rate > 1 else 0)


def render_base(msg_id, t_in, dur):
    """Stabilised, graded, still 60fps and still 1x -- the source every piece is cut from."""
    out = WORK / f"base_{msg_id}_{t_in}_{dur}.mp4"
    if out.exists():
        return out
    src, trf = src_of(msg_id), WORK / f"base_{msg_id}.trf"
    # analysis runs on the scaled-down frame so the 4K decode is only paid twice, not at full res
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(t_in), "-t", str(dur), "-i", str(src),
         "-vf", f"scale=1920:1080,vidstabdetect=shakiness=6:accuracy=15:result={trf}", "-f", "null", "-"])
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(t_in), "-t", str(dur), "-i", str(src),
         "-vf", (f"scale=1920:1080:flags=lanczos,setsar=1,"
                 f"vidstabtransform=input={trf}:smoothing=45:optzoom=1:zoom=1:interpol=bicubic,"
                 f"{GRADE},format=yuv420p"),
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", str(out)])
    trf.unlink()
    return out


def render_take(msg_id, t_in, dur, ramps):
    """One take as an ordered list of retimed pieces.

    Cut from the already-stabilised base, so the pieces line up frame for frame and the
    only discontinuity across a seam is the intended change of speed.
    """
    base = render_base(msg_id, t_in, dur)
    pieces = []
    for i, (a, b, r) in enumerate(expand(dur, ramps)):
        out = WORK / f"p{msg_id}_{i:02d}_{a}_{b}_{r:.1f}.mp4"
        pieces.append(out)
        if out.exists():
            continue
        # decode a little early so tmix reaches the cut with a full averaging window, and
        # trim on frame indices rather than seconds so the seek can't land a frame out
        pad = min(WARM, a)
        # fps pads a frame when the stream end lands on an output timestamp, so the count
        # is capped rather than trusted -- that pad is a duplicate, right on the seam
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{(a - pad) / 60:.6f}",
             "-t", f"{(pad + b - a + 1) / 60:.6f}", "-i", str(base),
             "-vf", (f"tmix=frames={blur_frames(r)},"
                     f"trim=start_frame={pad}:end_frame={pad + b - a},setpts=(PTS-STARTPTS)/{r},"
                     f"fps=30,trim=end_frame={(b - a) // int(2 * r)},setpts=PTS-STARTPTS,"
                     f"format=yuv420p"),
             "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "16", str(out)])
    return pieces


def render_inset(unit):
    out = WORK / f"inset_{unit}.png"
    if out.exists():
        return out
    x0, y0, x1, y1 = UNIT_BOX[unit]
    # highlight before cropping, so the box coordinates stay in the plan's own frame
    run(["magick", str(PLAN), "-fill", "rgba(255,85,30,0.5)", "-stroke", "#ff551e", "-strokewidth", "6",
         "-draw", f"rectangle {x0},{y0} {x1},{y1}", "-crop", INSET_CROP, "+repage",
         "-resize", "700x", "-bordercolor", "white", "-border", "12", str(out)])
    return out


def render_shot(tag, msg_id, t_in, dur):
    # the cut parameters are in the filename, so re-timing can never reuse a stale render
    out = WORK / f"{tag}.mp4"
    if out.exists():
        return out
    src, trf = src_of(msg_id), WORK / f"{tag}.trf"
    # analysis runs on the scaled-down frame so the 4K decode is only paid twice, not at full res
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(t_in), "-t", str(dur), "-i", str(src),
         "-vf", f"scale=1920:1080,vidstabdetect=shakiness=6:accuracy=15:result={trf}", "-f", "null", "-"])

    run(["ffmpeg", "-v", "error", "-y", "-ss", str(t_in), "-t", str(dur), "-i", str(src),
         "-vf", (f"scale=1920:1080:flags=lanczos,setsar=1,"
                 f"vidstabtransform=input={trf}:smoothing=45:optzoom=1:zoom=1:interpol=bicubic,"
                 f"{GRADE},tmix=frames={blur_frames(1.0)},fps=30,format=yuv420p"),
         "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "17", str(out)])
    trf.unlink()
    return out


def render_plan():
    out = WORK / "plan.mp4"
    if out.exists():
        return out
    lines = [(BOLD, 46, 830, "BLOCK A   ·   18 APARTMENTS PER FLOOR   ·   66 m² 2-BEDROOM"),
             (LIGHT, 38, 902, "09 / 10   —   1.190 BN VND"),
             (LIGHT, 38, 950, "03 · 05 · 07 · 11 · 13 · 15   —   1.219 BN VND"),
             (LIGHT, 38, 998, "04 · 06 · 08 · 12 · 14 · 16   —   1.404 BN VND")]
    text = ",".join(dt(f, t, "(w-text_w)/2", y, s, colour="0x1a1a1a") for f, s, y, t in lines)
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", str(PLAN_DUR), "-i", str(PLAN),
         "-vf", (f"crop=iw:ih*0.70:0:0,scale=1560:-2,pad=1920:1080:(ow-iw)/2:30:white,setsar=1,"
                 f"{text},fps=30,format=yuv420p"),
         "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "17", str(out)])
    return out


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=nb_read_frames", "-of", "default=nk=1:nw=1", str(path)],
                       capture_output=True, text=True)
    return int(r.stdout.strip()) / 30.0


def overlay(spans):
    """Timeline drawtext, insets and dips to black, off the durations the pieces actually came out at."""
    (intro, plan_start, units, outro_start, total) = spans

    def fade(t0, t1, ramp=0.6):
        return (f"if(lt(t,{t0}),0,if(lt(t,{t0 + ramp}),(t-{t0})/{ramp},"
                f"if(lt(t,{t1 - ramp}),1,if(lt(t,{t1}),({t1}-t)/{ramp},0))))")

    def card(t0, dur, big, small):
        t1 = t0 + dur
        return [dt(BOLD, big, 112, "h-255", 84, box="black@0.34", alpha=fade(t0, t1)),
                dt(LIGHT, small, 112, "h-108", 38, box="black@0.34", alpha=fade(t0 + 0.25, t1))]

    parts = []
    for i, (off, dur, big, small) in INTRO_CARDS.items():
        parts += card(intro[i] + off, dur, big, small)
    for s, (_, _, _, unit, price) in zip(units, UNITS):
        parts += card(s + 0.9, 5.2, unit, UNIT_SUB.format(price))
    parts += card(outro_start + 1.0, OUTRO[2] - 1.6, *OUTRO_CARD)

    # a hard cut would read as "same flat, different room"; the dip says "different flat".
    # each dip is gated to its own window -- an ungated fade=out holds black to the end of the film
    parts.append("fade=t=in:st=0:d=1.2")
    for s in units:
        parts.append(f"fade=t=out:st={s - DIP:.2f}:d={DIP}:enable='between(t,{s - DIP:.2f},{s:.2f})'")
        parts.append(f"fade=t=in:st={s:.2f}:d={DIP}:enable='between(t,{s:.2f},{s + DIP:.2f})'")
    parts.append(f"fade=t=out:st={total - 2.0:.2f}:d=2.0")
    return ",".join(parts)


def main():
    for d in (WORK, OUT):
        d.mkdir(parents=True, exist_ok=True)

    segs = [render_shot(f"in{i}_{m}_{a}_{b}", m, a, b) for i, (m, a, b, _) in enumerate(INTRO)]
    segs.append(render_plan())
    takes = [render_take(m, a, b, RAMPS[m]) for m, a, b, _, _ in UNITS]
    for t in takes:
        segs += t
    segs.append(render_shot(f"out_{OUTRO[0]}_{OUTRO[1]}_{OUTRO[2]}", *OUTRO[:3]))
    print(f"rendered {len(segs)} segments")

    # the pieces land on whole frames, so the timeline is read back off them rather than assumed
    dur = {p: probe(p) for p in segs}
    starts, t = {}, 0.0
    for p in segs:
        starts[p] = t
        t += dur[p]
    spans = ([starts[p] for p in segs[:4]], starts[segs[4]],
             [starts[k[0]] for k in takes], starts[segs[-1]], t)
    for (m, _, b, _, _), k in zip(UNITS, takes):
        print(f"  {m}: {b:.1f}s -> {sum(dur[p] for p in k):.1f}s over {len(k)} pieces")

    listing = WORK / "concat.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in segs))
    picture = WORK / "picture.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(picture)])

    master = OUT / "garden_tower_walkthrough_1080p.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(picture), "-stream_loop", "-1", "-i", str(src_of(AMBIENT_SRC))]
    chain, prev = [f"[0:v]{overlay(spans)}[v0]"], "v0"
    for i, ((_, _, _, unit, _), s) in enumerate(zip(UNITS, spans[2])):
        cmd += ["-loop", "1", "-framerate", "30", "-i", str(render_inset(unit))]
        a, b = s + INSET_IN, s + INSET_OUT
        # the still runs on the film's own clock -- shifting it with setpts instead would
        # make overlay buffer every main frame up to `a` waiting for its first still
        chain.append(f"[{i + 2}:v]format=rgba,fade=t=in:st={a:.2f}:d=0.5:alpha=1,"
                     f"fade=t=out:st={b:.2f}:d=0.5:alpha=1[i{i}]")
        chain.append(f"[{prev}][i{i}]overlay=W-w-64:64:eof_action=pass:enable='between(t,{a:.2f},{b + 0.5:.2f})'[v{i + 1}]")
        prev = f"v{i + 1}"
    total = spans[4]
    chain.append(f"[1:a]volume={AMBIENT_DB}dB,lowpass=f=4200,"
                 f"afade=t=in:st=0:d=2,afade=t=out:st={total - 2.5:.2f}:d=2.5[a]")
    # one continuous room-tone bed, so the dips between flats don't land in silence
    run(cmd + ["-filter_complex", ";".join(chain), "-map", f"[{prev}]", "-map", "[a]", "-t", f"{total:.2f}",
               "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(master)])
    print(f"{master}  ({total:.1f}s)")


if __name__ == "__main__":
    if "--clean" in sys.argv:
        shutil.rmtree(WORK, ignore_errors=True)
    main()
