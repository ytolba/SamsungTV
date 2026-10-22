#!/usr/bin/env python3
"""Control a Samsung Tizen TV over its official local WebSocket API.

Every command is printed with a timestamp. While a command runs, the TV log
(sdb dlogutil) is streamed if sdb is available. The TV shows an "Allow" prompt
the first time; approve it with the remote. The token is cached in ~/.tv-token.

  tv.py status
  tv.py key KEY_HOME [KEY_RIGHT ...]
  tv.py youtube "<video id | url | search words>"
"""
import base64, json, os, re, shutil, subprocess, sys, time, threading
try:
    import websocket  # pip install websocket-client
except ImportError:
    sys.exit("pip install websocket-client")

TV = os.environ.get("TV_IP") or sys.exit("export TV_IP=<tv ip>")
TOKEN_FILE = os.path.expanduser("~/.tv-token")
SDB = shutil.which("sdb") or os.path.expanduser("~/tizen-studio/tools/sdb")
YOUTUBE = "111299001912"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

class Logcat:
    """Shows the TV log only while a command runs."""
    def __enter__(self):
        self.p = None
        if os.path.exists(SDB):
            self.p = subprocess.Popen([SDB, "-s", f"{TV}:26101", "dlogutil", "-v", "brief"],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            threading.Thread(target=lambda: [print("   log|", l.rstrip()) for l in self.p.stdout], daemon=True).start()
        return self
    def __exit__(self, *a):
        if self.p: self.p.terminate()

def connect():
    token = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else ""
    name = base64.b64encode(b"tv.py").decode()
    url = f"wss://{TV}:8002/api/v2/channels/samsung.remote.control?name={name}" + (f"&token={token}" if token else "")
    log("connect (approve the prompt on the TV with the remote if it appears)")
    ws = websocket.create_connection(url, timeout=30, sslopt={"cert_reqs": 0})
    msg = json.loads(ws.recv())
    if msg.get("event") != "ms.channel.connect":
        sys.exit(f"unexpected reply: {msg}")
    t = (msg.get("data") or {}).get("token")
    if t:
        open(TOKEN_FILE, "w").write(t); os.chmod(TOKEN_FILE, 0o600)
    return ws

def key(ws, k, wait=1.2):
    log(f"press {k}")
    ws.send(json.dumps({"method": "ms.remote.control",
        "params": {"Cmd": "Click", "DataOfCmd": k, "Option": "false", "TypeOfRemote": "SendRemoteKey"}}))
    time.sleep(wait)

def video_id(arg):
    m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", arg) or re.fullmatch(r"([\w-]{11})", arg)
    if m: return m.group(1)
    if shutil.which("yt-dlp"):
        out = subprocess.run(["yt-dlp", "--get-id", f"ytsearch1:{arg}"], capture_output=True, text=True).stdout.strip()
        if out: return out
    sys.exit("give a video id/url, or install yt-dlp to resolve search words to an id")

def main(a):
    if not a: sys.exit(__doc__)
    cmd = a[0]; log(f"$ tv.py {' '.join(a)}")
    with Logcat():
        ws = connect()
        if cmd == "status":
            log("connected")
        elif cmd == "key":
            for k in a[1:]: key(ws, k)
        elif cmd == "youtube":
            vid = video_id(" ".join(a[1:])); log(f"video id {vid}")
            key(ws, "KEY_HOME", 2)
            log("launch YouTube with deep link")
            ws.send(json.dumps({"method": "ms.channel.emit", "params": {"event": "ed.apps.launch", "to": "host",
                "data": {"appId": YOUTUBE, "action_type": "DEEP_LINK", "metaTag": f"v={vid}"}}}))
            time.sleep(8)
            log("If a 'Who's watching?' screen is showing, pick your profile on the remote; then:")
            key(ws, "KEY_ENTER", 2)  # starts the video if it is paused on the watch page
        else:
            sys.exit(__doc__)
        ws.close()
main(sys.argv[1:])
