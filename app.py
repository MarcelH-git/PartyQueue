import os
import re
import json
import html
import socket
import base64
import io
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "partyqueue-dev-key-change-me")

JUKEBOX_PASSWORD = os.environ.get("JUKEBOX_PASSWORD", "host")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "")
HOST_NAME = os.environ.get("HOST_NAME", "Host")  # z.B. "192.168.178.76"

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")

queue = []
now_playing = {"current_time": 0, "duration": 0}
paused = False
guest_limit = 3
active_names = set()
stream_url_cache = {}  # youtube_id -> (url, timestamp)


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_public_ip():
    return PUBLIC_HOST if PUBLIC_HOST else get_local_ip()


def extract_youtube_id(text):
    match = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", text)
    return match.group(1) if match else None


def is_host():
    return session.get("authenticated") is True


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE) as f:
        return json.load(f)


def append_history(entry):
    history = load_history()
    history.append(entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def make_qr_base64(url):
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="white", back_color="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def check_video_playable(youtube_id):
    import urllib.request, urllib.parse
    params = urllib.parse.urlencode({
        "part": "status,contentDetails",
        "id": youtube_id,
        "key": YOUTUBE_API_KEY,
    })
    try:
        with urllib.request.urlopen(
            f"https://www.googleapis.com/youtube/v3/videos?{params}", timeout=5
        ) as r:
            data = json.loads(r.read())
        items = data.get("items", [])
        if not items:
            return "Video nicht gefunden oder nicht verfügbar"
        status = items[0].get("status", {})
        if not status.get("embeddable", True):
            return "Dieses Video kann nicht eingebettet werden (vom Uploader deaktiviert)"
        if status.get("uploadStatus") not in ("processed", "uploaded", None):
            return "Video ist nicht abspielbar"
        return None
    except Exception:
        return None


def parse_duration(iso):
    h = int(re.search(r'(\d+)H', iso).group(1)) if 'H' in iso else 0
    mins = int(re.search(r'(\d+)M', iso).group(1)) if 'M' in iso else 0
    s = int(re.search(r'(\d+)S', iso).group(1)) if 'S' in iso else 0
    total = h * 3600 + mins * 60 + s
    mm, ss = divmod(total, 60)
    if h:
        return f"{h}:{mm:02d}:{ss:02d}"
    return f"{mm}:{ss:02d}"


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name.lower() == HOST_NAME.lower():
            return render_template("login_guest.html", ip=get_public_ip(),
                                   error=f'"{HOST_NAME}" ist reserviert. Bitte einen anderen Namen wählen.')
        if name.lower() in {n.lower() for n in active_names}:
            return render_template("login_guest.html", ip=get_public_ip(),
                                   error=f'"{name}" ist bereits vergeben. Bitte einen anderen Namen wählen.')
        if name:
            old = session.get("guest_name")
            if old:
                active_names.discard(old)
            session.pop("authenticated", None)
            session["guest_name"] = name.strip()[:30]
            active_names.add(session["guest_name"])
        return redirect(url_for("index"))

    if not session.get("guest_name"):
        return render_template("login_guest.html", ip=get_public_ip(), error=None)

    return render_template("index.html", queue=queue, ip=get_public_ip(),
                           guest_name=session["guest_name"])


@app.route("/tv")
def tv():
    ip = get_public_ip()
    guest_url = f"http://{ip}:5000/"
    qr = make_qr_base64(guest_url)
    return render_template("tv.html", queue=queue, ip=ip, qr=qr, guest_url=guest_url)


@app.route("/host", methods=["GET", "POST"])
def host():
    if request.method == "POST":
        if "password" in request.form:
            if request.form["password"] == JUKEBOX_PASSWORD:
                session["authenticated"] = True
                return redirect(url_for("host"))
            else:
                return render_template("host.html", error="Falsches Passwort",
                                       authenticated=False, queue=queue, ip=get_public_ip())
        return redirect(url_for("host"))

    if not is_host():
        return render_template("host.html", authenticated=False,
                               queue=queue, ip=get_public_ip())
    return render_template("host.html", authenticated=True,
                           queue=queue, ip=get_public_ip())


@app.route("/history")
def history():
    if not is_host():
        return redirect(url_for("host"))
    entries = load_history()
    return render_template("history.html", entries=entries, ip=get_public_ip())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/logout_guest")
def logout_guest():
    name = session.pop("guest_name", None)
    if name:
        active_names.discard(name)
    return redirect(url_for("index"))


@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    youtube_id = request.form.get("youtube_id", "").strip()
    raw = request.form.get("raw", "").strip()
    if is_host():
        added_by = HOST_NAME
    else:
        added_by = session.get("guest_name", "Unbekannt")
    duration = request.form.get("duration", "").strip()

    if raw:
        extracted = extract_youtube_id(raw)
        if extracted:
            youtube_id = extracted
            if not title:
                title = f"Video ({youtube_id})"
        else:
            return jsonify({"error": "Kein gültiger YouTube-Link"}), 400

    if not youtube_id or not title:
        return jsonify({"error": "Titel und YouTube-ID erforderlich"}), 400

    if YOUTUBE_API_KEY:
        err = check_video_playable(youtube_id)
        if err:
            return jsonify({"error": err}), 400

    if any(v["youtube_id"] == youtube_id for v in queue):
        return jsonify({"error": "Dieses Video ist bereits in der Queue"}), 400

    if not is_host():
        count = sum(1 for v in queue if v.get("added_by") == added_by)
        if count >= guest_limit:
            return jsonify({"error": f"Du hast bereits {guest_limit} Videos in der Queue"}), 400

    entry = {"title": title, "youtube_id": youtube_id, "added_by": added_by, "duration": duration}
    queue.append(entry)

    append_history({
        "title": title,
        "youtube_id": youtube_id,
        "added_by": added_by,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "queue": queue, "now_playing": now_playing})
    return redirect(request.referrer or url_for("index"))


@app.route("/skip", methods=["POST"])
def skip():
    if not is_host() and not request.headers.get("X-TV-Request"):
        return jsonify({"error": "Nicht autorisiert"}), 403
    if queue:
        queue.pop(0)
    now_playing["current_time"] = 0
    now_playing["duration"] = 0
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "queue": queue})
    return redirect(request.referrer or url_for("host"))


@app.route("/delete/<int:i>", methods=["POST"])
def delete(i):
    if not is_host():
        return jsonify({"error": "Nicht autorisiert"}), 403
    if 0 <= i < len(queue):
        queue.pop(i)
    return redirect(request.referrer or url_for("host"))


@app.route("/move/<int:i>/<direction>", methods=["POST"])
def move(i, direction):
    if not is_host():
        return jsonify({"error": "Nicht autorisiert"}), 403
    if direction == "up" and i > 0:
        queue[i], queue[i - 1] = queue[i - 1], queue[i]
    elif direction == "down" and i < len(queue) - 1:
        queue[i], queue[i + 1] = queue[i + 1], queue[i]
    return redirect(request.referrer or url_for("host"))


def search_via_ytdlp(q):
    import subprocess
    proc = subprocess.run(
        ["yt-dlp",
         f"ytsearch6:{q}", "--print", "%(id)s|%(title)s|%(channel)s|%(duration_string)s|%(thumbnail)s",
         "--no-download", "--quiet", "--flat-playlist"],
        capture_output=True, text=True, timeout=15
    )
    results = []
    for line in proc.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue
        vid_id, title, channel, duration, thumbnail = parts
        results.append({
            "youtube_id": vid_id,
            "title": html.unescape(title),
            "thumbnail": f"https://i.ytimg.com/vi/{vid_id}/default.jpg",
            "channel": html.unescape(channel),
            "duration": duration,
            "embeddable": True,
        })
    return results


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    import urllib.request, urllib.parse
    if YOUTUBE_API_KEY:
        try:
            params = urllib.parse.urlencode({
                "part": "snippet",
                "q": q,
                "type": "video",
                "maxResults": 6,
                "key": YOUTUBE_API_KEY,
            })
            with urllib.request.urlopen(
                f"https://www.googleapis.com/youtube/v3/search?{params}", timeout=5
            ) as r:
                search_data = json.loads(r.read())

            items = [i for i in search_data.get("items", []) if i.get("id", {}).get("videoId")]
            if not items:
                return jsonify([])

            video_ids = ",".join(item["id"]["videoId"] for item in items)
            params2 = urllib.parse.urlencode({
                "part": "contentDetails,status",
                "id": video_ids,
                "key": YOUTUBE_API_KEY,
            })
            with urllib.request.urlopen(
                f"https://www.googleapis.com/youtube/v3/videos?{params2}", timeout=5
            ) as r:
                video_data = json.loads(r.read())

            video_info = {
                v["id"]: {
                    "duration": parse_duration(v["contentDetails"]["duration"]),
                    "embeddable": v.get("status", {}).get("embeddable", True),
                }
                for v in video_data.get("items", [])
            }

            results = [
                {
                    "youtube_id": item["id"]["videoId"],
                    "title": html.unescape(item["snippet"]["title"]),
                    "thumbnail": item["snippet"]["thumbnails"]["default"]["url"],
                    "channel": html.unescape(item["snippet"]["channelTitle"]),
                    "duration": video_info.get(item["id"]["videoId"], {}).get("duration", ""),
                    "embeddable": video_info.get(item["id"]["videoId"], {}).get("embeddable", True),
                }
                for item in items
            ]
            return jsonify(results)
        except Exception:
            pass  # Quota erreicht oder Fehler — auf yt-dlp fallen zurück

    try:
        return jsonify(search_via_ytdlp(q))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/nowplaying", methods=["POST"])
def nowplaying():
    data = request.get_json(silent=True) or {}
    now_playing["current_time"] = float(data.get("current_time", 0))
    now_playing["duration"] = float(data.get("duration", 0))
    return jsonify({"ok": True})


@app.route("/stream_url/<youtube_id>")
def stream_url(youtube_id):
    import subprocess, json, time
    cached = stream_url_cache.get(youtube_id)
    if cached and time.time() - cached["ts"] < 3600:
        return jsonify({"url": cached["url"], "title": cached["title"]})
    try:
        proc = subprocess.run(
            ["yt-dlp", "--js-runtimes", "node", "--remote-components", "ejs:github",
             "-j", "--no-download", "--format", "best[ext=mp4]/best",
             f"https://www.youtube.com/watch?v={youtube_id}"],
            capture_output=True, text=True, timeout=30
        )
        if proc.returncode != 0:
            return jsonify({"error": proc.stderr.strip().split("\n")[-1]}), 500
        info = json.loads(proc.stdout.strip().split("\n")[0])
        result = {"url": info["url"], "title": info.get("title", "")}
        stream_url_cache[youtube_id] = {**result, "ts": time.time()}
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/set_limit", methods=["POST"])
def set_limit():
    global guest_limit
    if not is_host():
        return jsonify({"error": "Nicht autorisiert"}), 403
    try:
        val = int(request.form.get("limit", 3))
        guest_limit = max(1, min(val, 20))
    except ValueError:
        return jsonify({"error": "Ungültiger Wert"}), 400
    return jsonify({"limit": guest_limit})


@app.route("/pause", methods=["POST"])
def pause():
    global paused
    if not is_host():
        return jsonify({"error": "Nicht autorisiert"}), 403
    paused = True
    return jsonify({"paused": paused})


@app.route("/resume", methods=["POST"])
def resume():
    global paused
    if not is_host():
        return jsonify({"error": "Nicht autorisiert"}), 403
    paused = False
    return jsonify({"paused": paused})


@app.route("/queue.json")
def queue_json():
    return jsonify({"queue": queue, "now_playing": now_playing, "paused": paused, "guest_limit": guest_limit})


if __name__ == "__main__":
    if os.environ.get("DEV"):
        queue.extend([
            {"title": "Rickroll", "youtube_id": "dQw4w9WgXcQ", "added_by": "Dev", "duration": "3:33"},
            {"title": "Gangnam Style", "youtube_id": "9bZkp7q19f0", "added_by": "Dev", "duration": "4:12"},
        ])
        print("DEV: 2 Testvideos in Queue geladen")

    ip = get_public_ip()
    print(f"\n PartyQueue laeuft!")
    print(f"   Gaeste:  http://{ip}:5000/")
    print(f"   TV:      http://{ip}:5000/tv")
    print(f"   Host:    http://{ip}:5000/host")
    print(f"   History: http://{ip}:5000/history\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
