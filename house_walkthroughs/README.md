edit property tour videos

## Framework

A tour sells one thing: the feeling of being in the room. Everything below serves that.
The three rules, in priority order:

1. **One take per apartment.** A cut inside a unit reads as "the bit we skipped was bad".
   The only cuts in the film are between units.
2. **Never bore the viewer inside the take.** Transit, blank walls and dwell-too-long
   stretches get *sped up*, not cut. The take stays unbroken and the viewer still reads
   the floor as one connected space.
3. **Start the walkthrough as soon as possible.** Intro is context, not content. ~20s.

Cuts we did not plan at shoot time will always look clunky. If a take needs a cut to work,
the take is wrong — pick a different one, or reshoot.

## Structure

```
intro montage   ~16s   4 shots, from footage NOT reused later
floorplan card   ~8s   the block plan + the price tiers
unit 1          uncut  + floorplan inset (unit highlighted) for the first ~10s
  dip to black  0.6s   says "different flat", where a hard cut would say "different room"
unit 2          uncut
  dip to black
unit 3          uncut
outro            ~5s   contact card over a window shot
```

Lower titles: unit code (84pt semibold) over `AREA · BEDROOMS · PRICE` (38pt light), both
on a `black@0.34` box, bottom-left, fading in ~1s into each segment.

## Process

### 1. Pull the footage

`~/s/tg/examples/dump_media.rs` — downloads a channel message range (documents *and*
photos, so it also gets floorplans and price lists):

```
cargo b --example dump_media
./target/debug/examples/dump_media <channel_id> <access_hash> <from> <to> <outdir> [--dry]
```

Channel id / access hash live in the `peer_info` table of
`~/.local/state/tg/@valeratrades.session`. The example copies the session first — the
running server holds a lock on the live file, and the copy carries the same auth key.

Run it detached (`setsid nohup … & disown`) and poll. Never block the foreground.

### 2. Map every clip to a unit, then rename

Vietnamese developer footage almost always opens on the door plate. Grab frames at
`0.3 1.5 3.0 5.0` for every clip, montage into contact sheets, read the plates, confirm
the ambiguous ones with a full-res centre crop.

Rename the raws immediately: `0248_A-14-15_IMG_2335.MOV`. Everything downstream globs on
the message id, so the rename is free, and it stops the whole rest of the job being done
against numbers nobody can hold in their head.

### 3. Read the price list against the floorplan

Do not assume the tiers match the sizes. Garden Tower has **two** areas (66.12 and
82.65 m²) and **three** price tiers, all three within the 66 m² 2-bedroom — the split is by
position on the slab, not by size. Check which units actually have footage: the 82.65 m²
corners had none at all.

Whatever the axis turns out to be, pick one take per tier, and if possible **all on the same
floor** so the orientations are directly comparable.

### 4. Review the candidates properly

12 evenly-spaced frames per clip, tiled 4-wide, one sheet per clip. Reject on:

- people in frame (workers, the presenter, hands)
- bedding, trestles, tools, packaging
- water stains, unfinished tiling
- flat overcast light, dusty floors

The best views in the set are often in the worst-finished unit. Finish beats view — the
view is sold by the intro montage anyway.

### 5. Plan the speed ramps

Contact sheet at **2s intervals** over the chosen takes. Mark every stretch that is:

- corridor/hallway transit between focal points → **2.5×**
- dwelling on something already shown (second wardrobe run, bathroom hold) → **2.5×**
- blank wall and door runs → **3.0×**
- the longest dead stretch in a take (utility rooms, wrapped doors) → **3.0×**

**Don't ramp gently.** 1.5× is the worst rate there is: fast enough that the frame stepping
shows, too slow to read as a deliberate hyperlapse. Either the stretch is worth real time,
or it goes past at 2.5×+. The floor is 2.5.

**Don't ramp briefly either.** A ramp has to climb to its rate and back down — ~1.2s of
shoulder to reach 2.5×, ~1.8s to reach 3×. A stretch too short to then *sit* at that rate
for a second or so is all shoulder and no ramp: it reads as cheap and saves almost nothing.
Leave it alone. `expand()` asserts this rather than squeezing the ease in silently — if the
build rejects a ramp, delete the ramp, don't shorten the shoulders.

**Only the rates in `STEPS` exist.** See the retiming section — arbitrary rates like 1.9×
judder and no amount of blur fixes it.

Never ramp: the window reveals, the kitchen, the first sight of a room. Those are the take.
A typical 100s raw take loses 12–25s this way and gains enormously.

## Technique

Per-segment render, then concat, then one overlay pass over the whole picture.

**Stabilise + grade, per segment.** Two-pass `vidstabdetect`/`vidstabtransform` with the
analysis run on the *scaled* frame, so the 4K decode is paid twice but never at full res.
Grade warms the clinical white walls without touching the sky:

```
eq=contrast=1.06:saturation=1.12:gamma=1.03:gamma_r=1.01:gamma_b=0.98,
colorbalance=rs=0.02:bs=-0.03:rm=0.03:bm=-0.03:rh=0.01:bh=-0.01,
unsharp=5:5:0.4:5:5:0.0
```

### Retiming without jank

This is the part that took three attempts. **iPhone footage is 59.94 fps and the film is
30**, so even at 1× half the frames are thrown away. Three things have to be true or the
sped-up sections strobe:

**1. Rate × 2 must be a whole number.** An output frame advances `2*rate` source frames.
At 1.9× that is 3.8, so the sampler steps 4,4,4,3,4,4,4,3 — a cadence stutter, and it is
by far the largest contributor to what reads as "janky". Allowed rates are therefore
**1.0, 1.5, 2.0, 2.5** and nothing else. Diagnose it by measuring frame-to-frame motion:

```
ffmpeg -ss <t> -t 5 -i master.mp4 -vf \
  "scale=320:180,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-" -f null -
```

A clean ramp gives a smoothly rising sequence. A bad one alternates every other frame
(`6.7 4.9 6.7 4.9 6.8 5.2 …`). That 2-cycle *is* the judder.

**2. Every piece must be a whole number of output frames.** Work in source frames, not
seconds. A piece spanning `n` source frames at rate `r` must have `n % (2*rate) == 0`, or
its last frame lands a hair short of the seam and the join shows a **duplicate frame**.
With 80+ pieces that is 80 visible hitches, and it looks exactly like bad speed-ramping.
Two separate causes, both need fixing:

- quantise piece lengths to multiples of `2*rate` in `expand()`, and let the final piece
  of a take absorb the remainder
- **`fps` pads one extra frame** when the stream end lands exactly on an output timestamp.
  Don't trust its count — follow it with `trim=end_frame=<n/(2*rate)>,setpts=PTS-STARTPTS`.

Cut with `trim=start_frame`/`end_frame` on frame indices, never `trim=start`/`duration` in
seconds; `-ss` is only the coarse seek, printed to 6 decimals. Then assert every rendered
piece's `nb_read_frames` equals what was planned.

**3. Motion blur, `tmix=frames=2*rate`.** Averaging `2*rate` source frames makes
consecutive output frames tile the source with neither gap nor overlap — a full 360°
shutter at that speed. Apply it at 1× too. Above 1× the displacement per output frame is
big enough that even an exactly-tiling window strobes, so open it **two frames wider**
(`2*rate + 2`) — a shutter past 360°, paid for in softness on stretches nobody dwells on.
Decode 18 frames early and `trim` *after* tmix, so the window is already full at the cut.

**4. Ease through the intermediate rates.** A step straight from 1× to 3× reads as a
glitch however clean the frames are. Each ramp climbs 1.0 → 1.5 → 2.0 → 2.5 → 3.0 and
back, holding ~0.3s at each intermediate rate. Short holds — those rates are the ugly ones,
they're a transition, not a look.

**Architecture: two stages.** `tmix`'s frame count cannot vary across ranges within one
filter graph, so a single pass is impossible.

```
stage A  render_base()   stabilise + grade the whole take, still 60fps, still 1x
stage B  render_take()   cut pieces out of that base, each with its own tmix + setpts + fps=30
```

Cutting from the *already stabilised* base is what makes the seams invisible: the pieces
line up frame for frame, so the only discontinuity across a seam is the intended change of
speed. Concatenating separately-stabilised renders jolts at every seam — don't.

A `split`/`trim`/`concat` filter graph is also a trap: `concat` buffers raw frames, ~18 GB
for a 100s 1080p take.

**Read the timeline back off the pieces**, don't assume it. Each piece rounds to a whole
frame, and with 40+ pieces the drift desyncs every card and dip downstream:

```
ffprobe -count_frames -select_streams v:0 -show_entries stream=nb_read_frames \
        -of default=nk=1:nw=1 <piece>     # / 30.0
```

**Floorplan inset.** Draw the highlight box on the full plan *before* cropping, so the
coordinates stay in the plan's own pixel frame. Then crop to the slab only (labels are
unreadable at inset size), resize, white border, `overlay=W-w-64:64` with an alpha fade.
Unit footprints on a regular slab can be derived: measure the two end units, divide the
span by the unit count, and the columns fall out.

### ffmpeg gotchas, all of these cost an hour each

- **An ungated `fade=t=out` holds black for the rest of the stream.** Every dip needs
  `enable='between(t,a,b)'` on *both* halves. Symptom: the master encodes at 17 kbps.
- **`drawtext` `alpha` applies to the box too**, which is what you want — the `box=1`
  scrim fades in and out with the text. Free.
- **Poppins has no Vietnamese diacritics** and renders tofu. Use **Be Vietnam Pro**.
- **Check subtitle legibility on the brightest frame**, not the first frame. A `black@0.34`
  box with `boxborderw=16` fixes it; leave ~145px between the two lines' baselines or the
  boxes collide.
- **`-loop 1 -i still.png` with no `-t` on that input never EOFs** and the encode runs
  forever. Bound it with `overlay=…:shortest=1`, or an output-level `-t` plus
  `eof_action=pass`. Symptom: 76 MB written for a 9s clip, and `moov atom not found`.
- **Don't `setpts=PTS+N/TB` a still to place an overlay.** `overlay` then buffers every
  main frame from 0 to N waiting for the still's first frame. Feed a `-framerate 30`
  looped still and gate it with absolute-time alpha fades instead.
- **`bc` is not installed here.** Do float math in `awk`.
- **`ffprobe -of csv=p=0` emits a trailing comma.** Use `-of default=nk=1:nw=1`.
- **A locale with a comma decimal separator breaks `printf %06.1f`** in shell loops. Name
  files off a zero-padded integer counter.
- **Verify on a full-res crop, not the contact sheet.** Downscaling eats diacritics and
  will send you chasing a font bug that isn't there.
- **ImageMagick `montage` beats ffmpeg `xstack`** for contact sheets by a mile.
- **Don't `pkill -f <name>`** — it matches the invoking shell's own command line.

### Verification before shipping

`ffprobe` the master, then:

- grab frames at every card and every inset — a card that didn't render looks fine in the log
- check each dip fired, by luma rather than by eye: `signalstats` `YAVG` should fall to
  ~30 at the midpoint from ~110 either side
- run the `tblend` motion measurement across every ramp shoulder and confirm there is no
  odd/even alternation
- scan **every seam** with it, not a sample: compute each seam's output frame index, and
  flag any where the motion at that frame falls below ~45% of the local median. That is a
  duplicate frame. Target is zero out of N.

## Facts worth not re-deriving

- Garden Tower is at 50 đường số 19B, khu đô thị mới An Phú Thịnh, **Quy Nhơn Đông** — not
  Da Nang. The lagoon in every window is **Đầm Thị Nại**, the long bridge is **Cầu Thị Nại**.
- Fonts: `BeVietnamPro-SemiBold.ttf` / `BeVietnamPro-Light.ttf` from the `google-fonts` nix
  store path.
- Source is 3840×2160 HEVC at **60000/1001 fps**. Masters go out 1920×1080 p30, h264
  crf19, AAC 128k, `-movflags +faststart`.
- Ambient bed: room tone from an unused clip, `-stream_loop -1`, `-26dB`, `lowpass=f=4200`,
  faded at both ends — so the dips between flats don't land in dead silence.

## Still not done anywhere

music, voiceover, virtual staging, vertical 0:60 and 0:30 cutdowns, a stills pack.
