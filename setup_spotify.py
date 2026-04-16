#!/usr/bin/env python3
"""
One-time setup: obtain a Spotify refresh token.
Run: python setup_spotify.py
"""
import os
import sys
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Hardcoded credentials — change these if needed
CLIENT_ID     = "bd88f2f6237a427ca82fa0d4d00e0aec"
CLIENT_SECRET = "5a3ae53469d4463c9ba3a240147f1774"
REDIRECT_URI  = "http://127.0.0.1:3000"
PORT          = 3000
HOST          = "127.0.0.1"
SCOPE         = "playlist-modify-public playlist-modify-private playlist-read-private"

try:
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    print("ERROR: spotipy not installed. Run: pip install spotipy")
    sys.exit(1)

print(f"\n[config] client_id:    {CLIENT_ID}")
print(f"[config] redirect_uri: {REDIRECT_URI}\n")

auth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE,
    open_browser=False,
    cache_path=None,  # no cache file
)

auth_url = auth.get_authorize_url()

_code: dict = {"value": None}
_event = threading.Event()


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code  = params.get("code",  [None])[0]
        error = params.get("error", [None])[0]

        print(f"[callback] path={parsed.path} code={'yes' if code else 'no'} error={error}")

        if code:
            _code["value"] = code
            body = b"""<html><body style="font-family:monospace;background:#111;color:#eee;padding:40px">
            <h2 style="color:#1db954">Authorization successful. You can close this tab.</h2>
            </body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            threading.Timer(0.5, _event.set).start()
        elif error:
            body = f"<html><body>Error: {error}</body></html>".encode()
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            threading.Timer(0.5, _event.set).start()
        else:
            # favicon or other browser requests — ignore
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, fmt, *args):
        pass


server = HTTPServer((HOST, PORT), CallbackHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()

print("=== Spotify Authorization ===\n")
print("Opening browser... if it doesn't open, go to:\n")
print(f"   {auth_url}\n")
webbrowser.open(auth_url)
print("Waiting (up to 3 min)...")

_event.wait(timeout=180)
server.shutdown()

code = _code["value"]
if not code:
    print("\nERROR: timed out or denied.")
    sys.exit(1)

token_info = auth.get_access_token(code, as_dict=True, check_cache=False)
refresh_token = token_info.get("refresh_token", "")

if not refresh_token:
    print("ERROR: no refresh token in response:", token_info)
    sys.exit(1)

print("\n=== SUCCESS ===\n")
print(f"SPOTIFY_REFRESH_TOKEN={refresh_token}\n")

# Write/update .env
env_path = ".env"
if os.path.exists(env_path):
    import re
    content = open(env_path).read()
    for key, val in [
        ("SPOTIFY_CLIENT_ID",     CLIENT_ID),
        ("SPOTIFY_CLIENT_SECRET", CLIENT_SECRET),
        ("SPOTIFY_REFRESH_TOKEN", refresh_token),
    ]:
        if key in content:
            content = re.sub(rf"{key}=.*", f"{key}={val}", content)
        else:
            content = content.rstrip("\n") + f"\n{key}={val}\n"
    open(env_path, "w").write(content)
    print("Written to .env.")
else:
    with open(env_path, "w") as f:
        f.write(f"SPOTIFY_CLIENT_ID={CLIENT_ID}\n")
        f.write(f"SPOTIFY_CLIENT_SECRET={CLIENT_SECRET}\n")
        f.write(f"SPOTIFY_REFRESH_TOKEN={refresh_token}\n")
    print(".env created.")

print("\nAdd to GitHub secrets → Settings → Secrets → Actions:")
print(f"  SPOTIFY_REFRESH_TOKEN = {refresh_token}")
