#!/bin/zsh
# Encode a device screen recording into an App Store App Preview.
set -eu

usage() {
  cat <<'EOF'
Usage: make_preview.sh <input.mov> [out.mp4] [start-seconds] [duration-seconds]

Encode a device screen recording into an App Store App Preview. Scales to fit
and pads rather than stretching, then prints PASS/FAIL for every Apple spec
item plus the peak audio level (silence means re-record, not re-encode).

Arguments:
  input.mov          Source recording (iOS Screen Recording recommended)
  out.mp4            Output path (default: <input>-preview.mp4)
  start-seconds      Trim start (default: 0)
  duration-seconds   Clip length (default: 28; Apple allows 15-30)

Environment:
  CANVAS=886x1920    iPhone portrait (all modern sizes). iPad: 1200x1600.
                     Mac / Apple TV: 1920x1080. Landscape iPhone: 1920x886.
  PAD_COLOR=0xFFFFFF Padding colour — use the app's background so bars vanish.

Apple's App Preview spec (pinned):
  canvas     886x1920 for all modern iPhone sizes (not a native screen size)
  duration   15-30s
  video      H.264 High Profile Level 4.0, progressive, <=30 fps, 10-12 Mbps
  audio      stereo AAC 256 kbps, 44.1 or 48 kHz (silent stereo track added if
             the source has none)
  size       <=500 MB

Requires: ffmpeg (brew install ffmpeg)

Examples:
  make_preview.sh take.mov out.mp4 2 28
  CANVAS=1200x1600 PAD_COLOR=0xE8E6DC make_preview.sh take.mov ipad.mp4
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

IN="${1:?usage: make_preview.sh <input.mov> [out.mp4] [start] [duration]  (try --help)}"
OUT="${2:-${IN:r}-preview.mp4}"
START="${3:-0}"
DUR="${4:-28}"

command -v ffmpeg >/dev/null || { echo "ffmpeg not found — brew install ffmpeg"; exit 1; }
[[ -f "$IN" ]] || { echo "no such file: $IN"; exit 1; }

# The app's background, so any padding reads as part of the frame.
PAD_COLOR="${PAD_COLOR:-0xFFFFFF}"
CANVAS="${CANVAS:-886x1920}"
CW="${CANVAS%x*}"; CH="${CANVAS#*x}"

# A silent stereo track is synthesised when the recording has none: the spec
# wants an enabled stereo audio track, and a video with no audio stream at all
# is the kind of thing that comes back as a vague rejection.
if ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$IN" | grep -q .; then
  echo "==> source has audio; keeping it"
  AUDIO_IN=()
  AUDIO_MAP=(-map 0:a:0)
else
  echo "==> source is silent; adding a silent stereo track"
  AUDIO_IN=(-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100)
  AUDIO_MAP=(-map 1:a:0 -shortest)
fi

echo "==> ${START}s +${DUR}s  ->  ${CW}x${CH}"
ffmpeg -hide_banner -y \
  -ss "$START" -t "$DUR" -i "$IN" \
  "${AUDIO_IN[@]}" \
  -map 0:v:0 "${AUDIO_MAP[@]}" \
  -vf "scale=${CW}:${CH}:force_original_aspect_ratio=decrease,pad=${CW}:${CH}:(ow-iw)/2:(oh-ih)/2:color=${PAD_COLOR},fps=30,format=yuv420p" \
  -c:v libx264 -profile:v high -level:v 4.0 -preset slow \
  -b:v 11M -maxrate 12M -bufsize 24M \
  -c:a aac -b:a 256k -ar 44100 -ac 2 \
  -movflags +faststart \
  "$OUT"

echo
echo "==> wrote $OUT"
# A silent take is the common failure and it's invisible in a spec check: the
# stereo track is present and conformant, it just carries nothing. Measure it.
LEVEL=$(ffmpeg -hide_banner -nostats -i "$OUT" -af volumedetect -f null - 2>&1 \
        | awk -F': ' '/max_volume/ {print $2}')
echo "==> peak audio level: ${LEVEL:-unknown}"
case "$LEVEL" in
  -9[0-9]*|-inf*) echo "    ^ that is digital silence. Check the ring/silent switch"
                  echo "      (an .ambient audio session is silent when muted)," \
                       "the app's own sound setting, and that iOS Screen Recording" \
                       "was used rather than QuickTime (which drops app audio)." ;;
esac
ffprobe -v error -show_entries \
  "format=duration,size:stream=codec_name,codec_type,width,height,r_frame_rate,profile,level,channels,sample_rate" \
  -of default=noprint_wrappers=1 "$OUT"

echo
echo "checks:"
CW="$CW" CH="$CH" python3 - "$OUT" <<'PY'
import json, os, subprocess, sys
cw, ch = int(os.environ['CW']), int(os.environ['CH'])
out = sys.argv[1]
probe = json.loads(subprocess.run(
    ["ffprobe", "-v", "error", "-print_format", "json",
     "-show_format", "-show_streams", out], capture_output=True, text=True).stdout)
video = next(s for s in probe["streams"] if s["codec_type"] == "video")
audio = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
dur, size = float(probe["format"]["duration"]), int(probe["format"]["size"])
num, den = (int(x) for x in video["r_frame_rate"].split("/"))
fps = num / den
def check(ok, label):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
check((video["width"], video["height"]) == (cw, ch), f"{cw}x{ch} (got {video['width']}x{video['height']})")
check(15 <= dur <= 30, f"15-30s (got {dur:.1f}s)")
check(fps <= 30, f"<=30 fps (got {fps:.2f})")
check(video["codec_name"] == "h264" and video.get("profile") == "High", f"H.264 High (got {video['codec_name']}/{video.get('profile')})")
check(int(video.get("level", 0)) <= 40, f"level <=4.0 (got {int(video.get('level', 0))/10:.1f})")
check(audio is not None and audio["channels"] == 2, "stereo audio track present")
check(audio is not None and audio["codec_name"] == "aac", f"AAC audio (got {audio and audio['codec_name']})")
check(size <= 500 * 1024 * 1024, f"<=500 MB (got {size/1e6:.1f} MB)")
PY
