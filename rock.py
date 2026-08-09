from flask import (
    Flask,
    request,
    jsonify,
    session,
    redirect,
    url_for,
    render_template_string,
    send_file
)
from dotenv import load_dotenv

import os
from io import BytesIO
import pyperclip
import socket
import subprocess
import shutil
import time
import urllib.parse
import secrets
import hmac
import ctypes

try:
    import comtypes
    from pycaw.pycaw import AudioUtilities
    AUDIO_CONTROL_AVAILABLE = True
except ImportError:
    AUDIO_CONTROL_AVAILABLE = False

import pyautogui
import pygetwindow as gw
import yt_dlp

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# =========================================================
# APPLICATION
# =========================================================

# Public-repository safe configuration:
# - Secrets are loaded from environment variables / .env.
# - User-specific folders are configurable and default to generic paths.
# - Do not commit your real .env file.

app = Flask(__name__)



BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GVA_LR_PASSWORD = os.environ.get("GVA_LR_PASSWORD")
SECRET_KEY = os.environ.get("GVA_LR_SECRET_KEY")
# =========================================================
# CONFIGURATION
# =========================================================

# User-specific locations are configurable through .env.
# No personal Windows paths are stored in this repository.
USER_HOME = os.path.expanduser("~")

VIDEO_FOLDER = os.path.abspath(
    os.path.expanduser(
        os.environ.get(
            "ROCK_VIDEO_FOLDER",
            os.path.join("~", "Videos", "RockVideos")
        )
    )
)

NOTES_FOLDER = os.path.abspath(
    os.path.expanduser(
        os.environ.get(
            "ROCK_NOTES_FOLDER",
            os.path.join("~", "Documents", "RockNotes")
        )
    )
)

ROCK_PROJECT_FOLDER = os.path.abspath(
    os.path.expanduser(
        os.environ.get(
            "ROCK_PROJECT_FOLDER",
            os.path.join("~", "RockProject")
        )
    )
)

# Prefer executables available on PATH. Optional .env overrides are
# supported for systems where VLC/Brave are installed in custom locations.
VLC_PATH = os.environ.get("ROCK_VLC_PATH") or shutil.which("vlc") or ""
BRAVE_PATH = os.environ.get("ROCK_BRAVE_PATH") or shutil.which("brave") or ""

VLC_HOST = os.environ.get("ROCK_VLC_HOST", "127.0.0.1")
VLC_PORT = int(os.environ.get("ROCK_VLC_PORT", "4212"))


# =========================================================
# PASSWORD / SECRET
# =========================================================

GVA_LR_PASSWORD = os.environ.get(
    "GVA_LR_PASSWORD"
)

SECRET_KEY = os.environ.get(
    "GVA_LR_SECRET_KEY"
)


if not GVA_LR_PASSWORD:

    print()
    print("ERROR:")
    print("GVA_LR_PASSWORD is not configured.")
    print()
    print('Git Bash:')
    print('export GVA_LR_PASSWORD="your-password"')
    print()

    raise SystemExit(1)


if not SECRET_KEY:

    print()
    print("ERROR:")
    print("GVA_LR_SECRET_KEY is not configured.")
    print()
    print('Git Bash:')
    print('export GVA_LR_SECRET_KEY="long-random-secret"')
    print()

    raise SystemExit(1)


app.secret_key = SECRET_KEY


app.config.update(

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SAMESITE="Strict",

    # False because GVA-LR currently uses local HTTP.
    # Change to True if HTTPS is added later.
    SESSION_COOKIE_SECURE=False

)


os.makedirs(
    NOTES_FOLDER,
    exist_ok=True
)


# =========================================================
# LOGIN ATTEMPT TRACKING
# =========================================================

login_attempts = {}


MAX_LOGIN_ATTEMPTS = 5

LOGIN_BLOCK_SECONDS = 30


# =========================================================
# SECURITY HELPERS
# =========================================================

def authenticated():

    return (
        session.get("authenticated")
        is True
    )


def check_password(password):

    if not isinstance(
        password,
        str
    ):

        return False

    return hmac.compare_digest(
        password,
        GVA_LR_PASSWORD
    )


def create_csrf_token():

    token = session.get(
        "csrf_token"
    )

    if not token:

        token = secrets.token_hex(32)

        session["csrf_token"] = token

    return token


def valid_csrf():

    expected = session.get(
        "csrf_token"
    )

    supplied = request.headers.get(
        "X-CSRF-Token",
        ""
    )

    if not expected:

        return False

    return hmac.compare_digest(
        expected,
        supplied
    )


def api_security():

    if not authenticated():

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401

    if request.method in (
        "POST",
        "PUT",
        "PATCH",
        "DELETE"
    ):

        if not valid_csrf():

            return jsonify({
                "status": "error",
                "message": "Invalid security token"
            }), 403

    return None


# =========================================================
# GLOBAL AUTHENTICATION GUARD
# =========================================================

@app.before_request
def require_gva_lr_login():

    # Only the login page and Flask static files are public.
    if request.endpoint in ("login", "static"):
        return None

    if authenticated():
        return None

    # Browser page requests are sent to the login screen.
    if request.method == "GET" and request.accept_mimetypes.accept_html:
        return redirect(url_for("login"))

    # API/direct requests are rejected until login.
    return jsonify({
        "status": "error",
        "message": "Authentication required"
    }), 401


# =========================================================
# SAFE NOTE PATH
# =========================================================

def safe_note_path(filename):

    if not isinstance(
        filename,
        str
    ):

        return None


    filename = filename.strip()


    if not filename:

        return None


    filename = os.path.basename(
        filename
    )


    if not filename.lower().endswith(
        ".txt"
    ):

        filename += ".txt"


    full_path = os.path.abspath(
        os.path.join(
            NOTES_FOLDER,
            filename
        )
    )


    root = os.path.abspath(
        NOTES_FOLDER
    )


    try:

        if (
            os.path.commonpath(
                [root, full_path]
            )
            != root
        ):

            return None

    except ValueError:

        return None


    return full_path



# =========================================================
# ROCK SHARE CONFIG
# =========================================================

ROCK_SHARE_FOLDER = os.path.join(os.path.expanduser("~"), "RockShare")
os.makedirs(ROCK_SHARE_FOLDER, exist_ok=True)


def safe_share_path(relative_path=""):
    relative_path = (relative_path or "").replace("\\", "/").lstrip("/")
    root = os.path.abspath(ROCK_SHARE_FOLDER)
    target = os.path.abspath(os.path.join(root, relative_path))
    try:
        if os.path.commonpath([root, target]) != root:
            return None
    except ValueError:
        return None
    return target


def share_relative_path(full_path):
    return os.path.relpath(full_path, ROCK_SHARE_FOLDER).replace("\\", "/")


# =========================================================
# VLC HELPER
# =========================================================

def vlc_command(command):

    try:

        with socket.create_connection(

            (
                VLC_HOST,
                VLC_PORT
            ),

            timeout=0.5

        ) as connection:

            connection.sendall(
                (
                    command + "\n"
                ).encode()
            )


        return True


    except Exception as error:

        print(
            "VLC:",
            error
        )

        return False


# =========================================================
# BRAVE WINDOW HELPER
# =========================================================

def focus_brave():

    try:

        windows = gw.getAllWindows()


        for window in windows:

            title = (
                window.title
                or ""
            ).lower()


            if "brave" in title:

                try:

                    if window.isMinimized:

                        window.restore()

                        time.sleep(0.05)


                    window.activate()

                    time.sleep(0.08)

                    return True


                except Exception as error:

                    print(
                        "Window activation:",
                        error
                    )


        return False


    except Exception as error:

        print(
            "Brave focus:",
            error
        )

        return False


# =========================================================
# OPEN BRAVE URL
# =========================================================

def open_brave_url(url):

    if not BRAVE_PATH or not os.path.isfile(BRAVE_PATH):
        return False


    subprocess.Popen([
        BRAVE_PATH,
        "--new-window",
        url
    ])


    return True


# =========================================================
# NAVIGATE BRAVE WITHOUT CREATING AN EXTRA TAB
# =========================================================

def navigate_brave_url(url):

    # If Brave is already open, reuse the current tab.
    # This avoids the extra blank/new tab that can appear when
    # repeatedly launching brave.exe with a URL.
    if focus_brave():

        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.05)
        pyautogui.write(url, interval=0.001)
        pyautogui.press("enter")

        return True

    # Brave is not running: start it directly with the URL.
    return open_brave_url(url)


# =========================================================
# LOGIN PAGE
# =========================================================

LOGIN_HTML = """
<!DOCTYPE html>

<html>

<head>

<title>GVA-LR Login</title>

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<style>

body {

    margin: 0;

    background: #0d0d0d;

    color: white;

    font-family: Arial, sans-serif;

    display: flex;

    align-items: center;

    justify-content: center;

    height: 100vh;

}


.login {

    width: 90%;

    max-width: 380px;

    background: #191919;

    padding: 30px;

    box-sizing: border-box;

    border-radius: 20px;

    text-align: center;

}


.logo {

    font-size: 38px;

    font-weight: bold;

    margin-bottom: 10px;

}


input {

    width: 100%;

    padding: 16px;

    box-sizing: border-box;

    background: #252525;

    border: 1px solid #444;

    border-radius: 12px;

    color: white;

    font-size: 18px;

    margin-top: 15px;

}


button {

    width: 100%;

    margin-top: 15px;

    padding: 16px;

    border: 0;

    border-radius: 12px;

    background: #176b36;

    color: white;

    font-size: 18px;

}


.error {

    color: #ff7777;

}


/* =========================================================
   ROCK V3 — MOBILE UI/UX REFRESH
   ========================================================= */

:root {
    --rock-bg: #0b0d12;
    --rock-surface: #151922;
    --rock-surface-2: #1d2330;
    --rock-border: rgba(255,255,255,.10);
    --rock-text: #f4f7fb;
    --rock-muted: #9aa6b6;
    --rock-accent: #5ea1ff;
    --rock-success: #35c97b;
    --rock-danger: #ff5f68;
    --rock-radius: 18px;
}

* {
    box-sizing: border-box;
}

html {
    background: var(--rock-bg);
}

body {
    margin: 0 auto;
    max-width: 760px;
    min-height: 100vh;
    background:
        radial-gradient(circle at top, #172238 0, var(--rock-bg) 320px);
    color: var(--rock-text);
    font-family:
        Inter, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    padding:
        max(12px, env(safe-area-inset-top))
        14px
        max(22px, env(safe-area-inset-bottom));
}

.header {
    position: sticky;
    top: 0;
    z-index: 20;
    margin: -12px -14px 16px;
    padding:
        max(16px, env(safe-area-inset-top))
        18px 14px;
    background: rgba(11,13,18,.88);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--rock-border);
    font-size: 1.18rem;
    font-weight: 800;
    letter-spacing: -.02em;
}

.page {
    width: 100%;
}

.card {
    background: linear-gradient(180deg, var(--rock-surface-2), var(--rock-surface));
    border: 1px solid var(--rock-border);
    border-radius: var(--rock-radius);
    padding: 16px;
    margin: 12px 0;
    box-shadow: 0 12px 30px rgba(0,0,0,.18);
}

.card h3 {
    margin: 0 0 12px;
    font-size: 1rem;
}

button,
input,
textarea,
select {
    font: inherit;
}

button {
    min-height: 48px;
    border: 1px solid var(--rock-border);
    border-radius: 14px;
    background: #232b3a;
    color: var(--rock-text);
    padding: 11px 14px;
    margin: 5px 3px;
    font-weight: 700;
    cursor: pointer;
    touch-action: manipulation;
    transition:
        transform .08s ease,
        background .15s ease,
        opacity .15s ease;
}

button:active {
    transform: scale(.97);
}

button.green {
    background: var(--rock-success);
    color: #07140d;
    border-color: transparent;
}

button.red {
    background: var(--rock-danger);
    color: white;
    border-color: transparent;
}

button.back {
    position: sticky;
    top: 70px;
    z-index: 15;
    width: auto;
    min-height: 42px;
    margin: 0 0 10px;
    padding: 8px 13px;
    background: rgba(29,35,48,.94);
    backdrop-filter: blur(12px);
}

input,
textarea,
select {
    width: 100%;
    min-height: 48px;
    margin: 7px 0;
    padding: 12px 13px;
    border: 1px solid var(--rock-border);
    border-radius: 13px;
    outline: none;
    background: #0e1219;
    color: var(--rock-text);
}

textarea {
    resize: vertical;
}

input:focus,
textarea:focus,
select:focus {
    border-color: var(--rock-accent);
    box-shadow: 0 0 0 3px rgba(94,161,255,.15);
}

.status {
    color: var(--rock-muted);
    line-height: 1.45;
}

#desktopTouchpad {
    background:
        radial-gradient(circle at center, #202a3a, #11161f);
    border-color: rgba(255,255,255,.16) !important;
}

/* Home page: turn the long button stack into an easy thumb-friendly grid. */
#homePage .card {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px;
}

#homePage .card h3,
#homePage .card h2,
#homePage .card p,
#homePage .card .status {
    grid-column: 1 / -1;
}

#homePage .card button {
    width: 100%;
    margin: 0;
    min-height: 58px;
}

/* Quick Launcher buttons work better as large tiles. */
#launcherPage .card {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px;
}

#launcherPage .card h3,
#launcherPage .card p {
    grid-column: 1 / -1;
}

#launcherPage .card button {
    width: 100%;
    margin: 0;
    min-height: 58px;
}

/* File actions should wrap instead of overflowing narrow phones. */
#rockFilesList > div {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
}

#rockFilesList > div > div:first-child {
    width: 100%;
    overflow-wrap: anywhere;
    font-weight: 700;
}

/* Screen preview gets a clean dark frame. */
#desktopScreenPreview {
    background: #050608;
    object-fit: contain;
}

/* Better one-hand layout on narrow phones. */
@media (max-width: 430px) {
    body {
        padding-left: 10px;
        padding-right: 10px;
    }

    .header {
        margin-left: -10px;
        margin-right: -10px;
    }

    .card {
        padding: 13px;
        border-radius: 16px;
    }

    button {
        min-height: 50px;
    }
}

/* Very small devices fall back to one column. */
@media (max-width: 330px) {
    #homePage .card,
    #launcherPage .card {
        grid-template-columns: 1fr;
    }
}

</style>

</head>


<body>


<div class="login">


<div class="logo">
⚡ GVA-LR
</div>


<p>
Laptop Remote
</p>


{% if error %}

<p class="error">
❌ {{ error }}
</p>

{% endif %}


<form method="POST">


<input

    type="password"

    name="password"

    placeholder="GVA-LR Password"

    autocomplete="current-password"

    required

>


<button type="submit">

🔓 Unlock GVA-LR

</button>


</form>


</div>


</body>

</html>
"""


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=[
        "GET",
        "POST"
    ]
)
def login():

    if authenticated():

        return redirect(
            url_for("home")
        )


    error = None


    if request.method == "POST":

        ip = request.remote_addr or "unknown"

        now = time.time()


        data = login_attempts.get(
            ip,
            {
                "count": 0,
                "blocked_until": 0
            }
        )


        if now < data["blocked_until"]:

            remaining = int(
                data["blocked_until"]
                - now
            )


            error = (
                "Too many attempts. "
                f"Try again in {remaining} seconds."
            )


            return render_template_string(
                LOGIN_HTML,
                error=error
            )


        password = request.form.get(
            "password",
            ""
        )


        if check_password(
            password
        ):

            login_attempts.pop(
                ip,
                None
            )


            session.clear()

            session["authenticated"] = True

            session["csrf_token"] = (
                secrets.token_hex(32)
            )


            return redirect(
                url_for("home")
            )


        data["count"] += 1


        if (
            data["count"]
            >= MAX_LOGIN_ATTEMPTS
        ):

            data["count"] = 0

            data["blocked_until"] = (
                now
                + LOGIN_BLOCK_SECONDS
            )


        login_attempts[ip] = data

        error = "Incorrect password"


    return render_template_string(
        LOGIN_HTML,
        error=error
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route(
    "/logout",
    methods=["POST"]
)
def logout():

    security = api_security()

    if security:

        return security


    session.clear()


    return jsonify({
        "status": "success",
        "message": "Logged out"
    })


# =========================================================
# MAIN PAGE
# =========================================================

@app.route("/")
def home():

    if not authenticated():

        return redirect(
            url_for("login")
        )


    csrf = create_csrf_token()


    return render_template_string(
        MAIN_HTML,
        csrf=csrf
    )


# =========================================================
# MAIN HTML
# =========================================================

MAIN_HTML = r"""
<!DOCTYPE html>

<html>

<head>

<title>GVA-LR</title>

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>


<style>

* {
    box-sizing: border-box;
}


body {

    margin: 0;

    background: #0e0e0e;

    color: white;

    font-family: Arial, sans-serif;

    text-align: center;

}


.page {

    display: none;

    padding: 18px;

}


.active {

    display: block;

}


.header {

    font-size: 30px;

    font-weight: bold;

    padding: 20px;

}


.card {

    max-width: 520px;

    margin: 15px auto;

    padding: 18px;

    background: #191919;

    border-radius: 18px;

}


button {

    width: 95%;

    max-width: 440px;

    padding: 16px;

    margin: 6px;

    border: 0;

    border-radius: 12px;

    font-size: 17px;

    color: white;

    background: #292929;

}


button:active {

    transform: scale(0.98);

}


.green {

    background: #176b36;

}


.red {

    background: #851f1f;

}


.orange {

    background: #8a4c14;

}


.back {

    background: #333;

}


.small {

    width: 29%;

    max-width: 130px;

    font-size: 20px;

}


input,
textarea {

    width: 95%;

    max-width: 450px;

    padding: 15px;

    margin: 7px;

    background: #222;

    border: 1px solid #444;

    border-radius: 12px;

    color: white;

    font-size: 17px;

}


textarea {

    min-height: 300px;

}


.movie,
.note,
.youtube-result {

    text-align: left;

}


.status {

    color: #aaa;

    min-height: 24px;

}


.warning {

    color: #ffb55e;

}


#timeline {

    width: 95%;

}


#volume {

    width: 90%;

}


.modal {

    display: none;

    position: fixed;

    z-index: 100;

    left: 0;

    top: 0;

    width: 100%;

    height: 100%;

    background: rgba(0,0,0,0.85);

    align-items: center;

    justify-content: center;

}


.modal-content {

    width: 90%;

    max-width: 400px;

    background: #1b1b1b;

    border-radius: 18px;

    padding: 25px;

}


.youtube-title {

    font-weight: bold;

}


.youtube-channel {

    color: #aaa;

    font-size: 14px;

}


hr {

    border: 0;

    border-top: 1px solid #333;

    margin: 20px 0;

}

</style>

</head>


<body>


<script>

const CSRF_TOKEN = "{{ csrf }}";


function api(
    url,
    data
) {

    return fetch(
        url,
        {

            method: "POST",

            headers: {

                "Content-Type":
                    "application/json",

                "X-CSRF-Token":
                    CSRF_TOKEN

            },

            body:
                JSON.stringify(
                    data || {}
                )

        }
    )

    .then(async response => {

        const result =
            await response.json();


        if (
            response.status === 401
        ) {

            window.location =
                "/login";

            throw new Error(
                "Authentication required"
            );

        }


        return result;

    });

}


function showPage(id) {

    if (
        id !== "desktopRemotePage"
        && typeof stopAutoPreview === "function"
    ) {
        stopAutoPreview();
    }

    window.scrollTo({
        top: 0,
        behavior: "instant"
    });

    document
        .querySelectorAll(
            ".page"
        )
        .forEach(page => {

            page.classList.remove(
                "active"
            );

        });


    document
        .getElementById(id)
        .classList.add(
            "active"
        );

}

</script>



<!-- ================================================= -->
<!-- HOME -->
<!-- ================================================= -->

<div
    id="homePage"
    class="page active"
>


<div class="header">

⚡ GVA-LR

</div>


<p>
💻 Laptop Connected
</p>


<div class="card">


<h3>
Applications
</h3>


<button onclick="openVLC()">

🎬 VLC

</button>


<button onclick="openNotes()">

📝 Notepad

</button>


<button onclick="showPage('launcherPage')">
🚀 Quick Launcher
</button>

<button onclick="openDesktopRemote()">
🖱️ Desktop Remote
</button>

<button onclick="openLaptopStatus()">
📊 Status
</button>

<button onclick="openRockFiles()">
📁 Files
</button>

<button
    onclick="showPage('clipboardPage')"
>
📋 Clipboard
</button>


<button onclick="showPage('bravePage')">

🌐 Brave

</button>


<button onclick="showPage('youtubePage')">

📺 YouTube

</button>


</div>



<div class="card">


<h3>
⚙️ System
</h3>


<button onclick="openDeviceControls()">

🔆 Display & Volume

</button>


<button onclick="lockLaptop()">

🔒 Lock Laptop

</button>


<button
    class="orange"
    onclick="powerDialog('restart')"
>

🔄 Restart Laptop

</button>


<button
    class="red"
    onclick="powerDialog('shutdown')"
>

⏻ Shutdown Laptop

</button>


</div>



<div class="card">


<button
    class="red"
    onclick="logout()"
>

🚪 Logout

</button>


</div>


</div>



<!-- ================================================= -->
<!-- DISPLAY & VOLUME -->
<!-- ================================================= -->

<div
    id="deviceControlsPage"
    class="page"
>

<div class="header">
🔆 DISPLAY & VOLUME
</div>

<button
    class="back"
    onclick="showPage('homePage')"
>
← GVA-LR
</button>

<div class="card">

<h3>🔆 Brightness</h3>

<input
    id="systemBrightness"
    type="range"
    min="0"
    max="100"
    value="50"
    oninput="brightnessText.innerText = this.value + '%'"
    onchange="setBrightness(this.value)"
>

<p id="brightnessText">50%</p>

<button
    class="small"
    onclick="changeBrightness(-10)"
>
−10
</button>

<button
    class="small"
    onclick="changeBrightness(10)"
>
+10
</button>

</div>


<div class="card">

<h3>🔊 System Volume</h3>

<input
    id="systemVolume"
    type="range"
    min="0"
    max="100"
    value="50"
    oninput="systemVolumeText.innerText = this.value + '%'"
    onchange="setSystemVolume(this.value)"
>

<p id="systemVolumeText">50%</p>

<button
    class="small"
    onclick="changeSystemVolume(-10)"
>
−10
</button>

<button
    class="small"
    onclick="changeSystemVolume(10)"
>
+10
</button>

<br>

<button onclick="toggleSystemMute()">
🔇 Mute / Unmute
</button>

<p
    id="deviceControlStatus"
    class="status"
></p>

</div>

</div>



<!-- ================================================= -->
<!-- VLC LIBRARY -->
<!-- ================================================= -->

<div
    id="vlcPage"
    class="page"
>


<div class="header">

🎬 VLC

</div>


<button
    class="back"
    onclick="showPage('homePage')"
>

← GVA-LR

</button>


<div class="card">


<h3>
Movies
</h3>


<div id="movieList">

Loading...

</div>


</div>


</div>



<!-- ================================================= -->
<!-- VLC PLAYER -->
<!-- ================================================= -->

<div
    id="vlcPlayerPage"
    class="page"
>


<button
    class="back"
    onclick="showPage('vlcPage')"
>

← Movies

</button>


<div class="header">

🎬 NOW PLAYING

</div>


<h3 id="movieName">

Movie

</h3>


<div class="card">


<p>
Timeline
</p>


<input

    id="timeline"

    type="range"

    min="0"

    max="100"

    value="0"

    oninput="
        timelineText.innerText =
        this.value + '%'
    "

    onchange="
        seekVLC(this.value)
    "

>


<p id="timelineText">
0%
</p>


<button
    class="small"
    onclick="vlc('pause')"
>

⏯

</button>


<br>


<p>
Volume
</p>


<input

    id="volume"

    type="range"

    min="0"

    max="100"

    value="50"

    oninput="
        vlcVolume(this.value)
    "

>


<br>


<button
    onclick="vlc('fullscreen')"
>

⛶ Fullscreen

</button>


<button
    class="red"
    onclick="closeVLC()"
>

❌ Close VLC

</button>


</div>


</div>



<!-- ================================================= -->
<!-- NOTES -->
<!-- ================================================= -->

<div
    id="notesPage"
    class="page"
>


<div class="header">

📝 GVA-LR NOTES

</div>


<button
    class="back"
    onclick="showPage('homePage')"
>

← GVA-LR

</button>


<div class="card">


<button
    class="green"
    onclick="newNote()"
>

➕ New Note

</button>


<div id="notesList">

</div>


</div>


</div>



<!-- ================================================= -->
<!-- NOTE EDITOR -->
<!-- ================================================= -->

<div
    id="noteEditorPage"
    class="page"
>


<button
    class="back"
    onclick="openNotes()"
>

← Notes

</button>


<div class="header">

📝 Editor

</div>


<div class="card">


<input

    id="noteFilename"

    placeholder="filename.txt"

>


<textarea

    id="noteText"

    placeholder="Write here..."

></textarea>


<button
    class="green"
    onclick="saveNote()"
>

💾 Save

</button>


<button onclick="openNoteLaptop()">

💻 Open on Laptop

</button>


<button
    class="red"
    onclick="deleteNote()"
>

🗑 Delete

</button>


<p
    id="noteStatus"
    class="status"
></p>


</div>


</div>








<!-- ================================================= -->
<!-- QUICK LAUNCHER -->
<!-- ================================================= -->

<div id="launcherPage" class="page">

<div class="header">
🚀 Quick Launcher
</div>

<button class="back" onclick="showPage('homePage')">
← GVA-LR
</button>

<div class="card">

<h3>💻 Development</h3>

<button onclick="quickLaunch('vscode')">
💙 VS Code
</button>

<button onclick="quickLaunch('gitbash')">
⌨️ Git Bash
</button>

<button onclick="quickLaunch('rock_folder')">
📁 Rocky Project
</button>

</div>

<div class="card">

<h3>🧰 Windows Tools</h3>

<button onclick="quickLaunch('explorer')">
📂 File Explorer
</button>

<button onclick="quickLaunch('calculator')">
🧮 Calculator
</button>
</div>

<div class="card"><p id="launcherStatus" class="status"></p></div>

</div>


<!-- ================================================= -->
<!-- DESKTOP REMOTE -->
<!-- ================================================= -->

<div id="desktopRemotePage" class="page">

<div class="header">
🖱️ Desktop Remote
</div>

<button class="back" onclick="showPage('homePage')">
← GVA-LR
</button>

<div class="card">

<h3>📸 Laptop Screen</h3>

<img
    id="desktopScreenPreview"
    alt="Laptop screen preview"
    style="width:100%;height:auto;border-radius:10px;border:1px solid #666;display:none;"
>

<p id="desktopScreenPlaceholder" class="status">
Press Refresh Screen to capture the laptop display.
</p>

<button
    class="green"
    onclick="refreshDesktopScreen()"
>
📸 Refresh Screen
</button>

<button
    id="autoPreviewButton"
    onclick="toggleAutoPreview()"
>
▶️ Start Auto Preview
</button>

<select
    id="autoPreviewSpeed"
    onchange="restartAutoPreviewIfRunning()"
>
<option value="2000">Every 2 seconds</option>
<option value="1000" selected>Every 1 second</option>
<option value="500">Every 0.5 second</option>
</select>

<p class="status">
RAM only • not saved to disk
</p>

</div>


<div class="card">

<h3>🖱️ Touchpad</h3>

<div
    id="desktopTouchpad"
    style="height:220px;border:2px solid #777;border-radius:14px;touch-action:none;user-select:none;display:flex;align-items:center;justify-content:center;margin-bottom:12px;"
>
Drag finger to move mouse<br>Tap to click
</div>

<button onclick="desktopMouse('left_click')">👆 Left Click</button>
<button onclick="desktopMouse('right_click')">🖱️ Right Click</button>
<button onclick="desktopMouse('double_click')">👆👆 Double Click</button>

<button onclick="desktopMouse('scroll_up')">▲ Scroll</button>
<button onclick="desktopMouse('scroll_down')">▼ Scroll</button>

</div>

<div class="card">

<h3>⌨️ Keyboard</h3>

<input
    id="desktopTypeInput"
    placeholder="Text to type on laptop"
>

<button class="green" onclick="desktopTypeText()">
⌨️ Type Text
</button>

<button onclick="desktopKey('enter')">↵ Enter</button>
<button onclick="desktopKey('escape')">Esc</button>
<button onclick="desktopKey('tab')">Tab</button>
<button onclick="desktopKey('backspace')">⌫ Backspace</button>

<button onclick="desktopKey('up')">↑</button>
<button onclick="desktopKey('left')">←</button>
<button onclick="desktopKey('down')">↓</button>
<button onclick="desktopKey('right')">→</button>

</div>

<div class="card">

<h3>⚡ Shortcuts</h3>

<button onclick="desktopShortcut('copy')">📋 Copy</button>
<button onclick="desktopShortcut('paste')">📥 Paste</button>
<button onclick="desktopShortcut('select_all')">Select All</button>
<button onclick="desktopShortcut('undo')">↶ Undo</button>

<button onclick="desktopShortcut('alt_tab')">🔄 Alt + Tab</button>
<button onclick="desktopShortcut('desktop')">🖥️ Show Desktop</button>
<button onclick="desktopShortcut('task_manager')">⚙️ Task Manager</button>

<p id="desktopRemoteStatus" class="status"></p>

</div>

</div>


<!-- ================================================= -->
<!-- LAPTOP STATUS -->
<!-- ================================================= -->

<div id="statusPage" class="page">

<div class="header">
📊 Laptop Status
</div>

<button
    class="back"
    onclick="showPage('homePage')"
>
← GVA-LR
</button>

<div class="card">

<h3>🔋 Battery</h3>
<p id="statusBattery">Loading...</p>

<h3>🧠 Performance</h3>
<p id="statusCpu">CPU: --</p>
<p id="statusRam">RAM: --</p>

<h3>💾 Storage</h3>
<p id="statusDisk">Disk: --</p>

<h3>🌐 Network</h3>
<p id="statusHost">Computer: --</p>
<p id="statusIp">IP: --</p>

<h3>⏱️ System</h3>
<p id="statusUptime">Uptime: --</p>

<button
    class="green"
    onclick="loadLaptopStatus()"
>
🔄 Refresh Status
</button>

<p id="statusMessage" class="status"></p>

</div>

</div>


<!-- ================================================= -->
<!-- ROCK FILES -->
<!-- ================================================= -->

<div id="filesPage" class="page">

<div class="header">📁 Rock Files</div>

<button class="back" onclick="showPage('homePage')">← GVA-LR</button>

<div class="card">
<h3>📂 Safe Share Folder</h3>
<p>Rock can access only <b>~/RockShare</b></p>
<p id="filesCurrentPath" class="status">/</p>
<button onclick="filesGoUp()">⬅ Parent Folder</button>
<button onclick="loadRockFiles()">🔄 Refresh</button>
</div>

<div class="card">
<h3>⬆ Upload to Laptop</h3>
<input id="rockFileUpload" type="file">
<button class="green" onclick="uploadRockFile()">⬆ Upload</button>
</div>

<div class="card">
<h3>📁 Create Folder</h3>
<input id="newFolderName" placeholder="Folder name">
<button onclick="createRockFolder()">➕ Create Folder</button>
</div>

<div class="card">
<h3>📄 Files</h3>
<div id="rockFilesList">Loading...</div>
<p id="filesStatus" class="status"></p>
</div>

</div>


<!-- ================================================= -->
<!-- ROCK CLIPBOARD -->
<!-- ================================================= -->

<div
    id="clipboardPage"
    class="page"
>

<div class="header">
📋 Rock Clipboard
</div>

<button
    class="back"
    onclick="showPage('homePage')"
>
← GVA-LR
</button>

<div class="card">

<h3>📱 → 💻 Send to Laptop</h3>

<textarea
    id="clipboardSendText"
    placeholder="Paste or type text here..."
    style="width:100%;min-height:130px;box-sizing:border-box;border-radius:10px;padding:10px;"
></textarea>

<button
    class="green"
    onclick="sendClipboardToLaptop()"
>
📋 Copy to Laptop Clipboard
</button>

</div>

<div class="card">

<h3>💻 → 📱 Get from Laptop</h3>

<button onclick="getClipboardFromLaptop()">
📥 Get Laptop Clipboard
</button>

<textarea
    id="clipboardReceiveText"
    readonly
    placeholder="Laptop clipboard will appear here..."
    style="width:100%;min-height:130px;box-sizing:border-box;border-radius:10px;padding:10px;"
></textarea>

<button onclick="copyReceivedClipboard()">
📱 Copy on Phone
</button>

<p id="clipboardStatus" class="status"></p>

</div>

</div>


<!-- ================================================= -->
<!-- BRAVE -->
<!-- ================================================= -->

<div
    id="bravePage"
    class="page"
>


<div class="header">

🌐 BRAVE

</div>


<button
    class="back"
    onclick="showPage('homePage')"
>

← GVA-LR

</button>



<div class="card">


<h3>
🔎 Search / URL
</h3>


<input

    id="braveInput"

    placeholder="Search or enter website"

>


<button
    class="green"
    onclick="braveGo()"
>

🚀 Go

</button>


</div>



<div class="card">


<h3>
🧭 Navigation
</h3>


<button
    class="small"
    onclick="brave('back')"
>

←

</button>


<button
    class="small"
    onclick="brave('refresh')"
>

↻

</button>


<button
    class="small"
    onclick="brave('forward')"
>

→

</button>


</div>



<div class="card">


<h3>
📜 Page
</h3>


<button onclick="brave('scroll_up')">

▲ Scroll Up

</button>


<button onclick="brave('scroll_down')">

▼ Scroll Down

</button>


<button onclick="brave('page_up')">

⬆ Page Up

</button>


<button onclick="brave('page_down')">

⬇ Page Down

</button>


<button
    class="small"
    onclick="brave('top')"
>

⏫

</button>


<button
    class="small"
    onclick="brave('bottom')"
>

⏬

</button>


</div>



<div class="card">


<h3>
🔍 Zoom
</h3>


<button
    class="small"
    onclick="brave('zoom_out')"
>

−

</button>


<button
    class="small"
    onclick="brave('zoom_reset')"
>

100%

</button>


<button
    class="small"
    onclick="brave('zoom_in')"
>

+

</button>


</div>



<div class="card">


<h3>
📑 Tabs
</h3>


<button onclick="brave('new_tab')">

➕ New Tab

</button>


<button
    class="small"
    onclick="brave('previous_tab')"
>

◀

</button>


<button
    class="small"
    onclick="brave('next_tab')"
>

▶

</button>


<button
    class="red"
    onclick="brave('close_tab')"
>

❌ Close Current Tab

</button>


</div>



<div class="card">

<button class="green" onclick="brave('bring_front')">
📌 Bring Browser to Front
</button>

<p class="status">Shows the existing Brave window on top. Does not open a new tab.</p>

</div>


<div class="card">


<h3>
🖱️ Browser Touchpad (Rock v3)
</h3>


<div
    id="braveTouchpad"
    style="height:180px;border:2px solid #777;border-radius:14px;touch-action:none;user-select:none;display:flex;align-items:center;justify-content:center;margin-bottom:12px;"
>

Drag here to move laptop mouse<br>Tap to click

</div>


<button onclick="braveMouse('left_click')">
👆 Left Click
</button>


<button onclick="braveMouse('right_click')">
🖱️ Right Click
</button>


<button onclick="braveMouse('scroll_up')">
▲ Scroll
</button>


<button onclick="braveMouse('scroll_down')">
▼ Scroll
</button>


<input
    id="braveTypeInput"
    placeholder="Text to type on laptop"
>


<button
    class="green"
    onclick="braveTypeText()"
>
⌨️ Type Text
</button>


</div>


<div class="card">


<h3>
📺 Generic Media
</h3>


<button
    class="small"
    onclick="brave('media_back')"
>

⏪

</button>


<button
    class="small"
    onclick="brave('media_play')"
>

⏯

</button>


<button
    class="small"
    onclick="brave('media_forward')"
>

⏩

</button>


<button onclick="brave('media_mute')">

🔇 Mute

</button>


<button onclick="brave('media_fullscreen')">

⛶ Fullscreen

</button>


</div>



<div class="card">


<button onclick="brave('open')">

🚀 Open Brave

</button>


<button
    class="red"
    onclick="brave('close_brave')"
>

🛑 Close Brave

</button>


<p
    id="braveStatus"
    class="status"
></p>


</div>


</div>



<!-- ================================================= -->
<!-- YOUTUBE SEARCH -->
<!-- ================================================= -->

<div
    id="youtubePage"
    class="page"
>


<div class="header">

📺 YouTube

</div>


<button
    class="back"
    onclick="showPage('homePage')"
>

← GVA-LR

</button>


<div class="card">


<h3>
🔎 Search YouTube
</h3>


<input

    id="youtubeSearch"

    placeholder="Search videos..."

>


<button
    class="green"
    onclick="searchYouTube()"
>

🔎 Search

</button>


<p
    id="youtubeStatus"
    class="status"
></p>


</div>



<div
    id="youtubeResults"
    class="card"
>

Search for a video.

</div>


</div>



<!-- ================================================= -->
<!-- YOUTUBE PLAYER -->
<!-- ================================================= -->

<div
    id="youtubePlayerPage"
    class="page"
>


<button
    class="back"
    onclick="showPage('youtubePage')"
>

← Results

</button>


<div class="header">

📺 YOUTUBE REMOTE

</div>


<div class="card">


<h3 id="youtubePlaying">

YouTube

</h3>


<p id="youtubeChannel"></p>


<button class="green" onclick="youtubeControl('bring_front')">
📌 Bring YouTube to Front
</button>


<hr>


<button
    class="small"
    onclick="youtubeControl('back10')"
>

⏪

</button>


<button
    class="small"
    onclick="youtubeControl('play')"
>

⏯

</button>


<button
    class="small"
    onclick="youtubeControl('forward10')"
>

⏩

</button>


<p>
10 sec back • Play/Pause • 10 sec forward
</p>


<button onclick="youtubeControl('volume_up')">

🔊 Volume +

</button>


<button onclick="youtubeControl('volume_down')">

🔉 Volume -

</button>


<button onclick="youtubeControl('mute')">

🔇 Mute

</button>


<button onclick="youtubeControl('fullscreen')">

⛶ Fullscreen

</button>


<hr>


<button onclick="youtubeControl('previous')">

⏮ Previous Video

</button>


<button onclick="youtubeControl('next')">

⏭ Next Video

</button>


<hr>


<button onclick="youtubeControl('theater')">

🎭 Theater Mode

</button>


<button onclick="youtubeControl('captions')">

CC Captions

</button>


<hr>


<button
    class="red"
    onclick="youtubeControl('close_tab')"
>

❌ Close Video Tab (Rock v3)

</button>


<p
    id="youtubeRemoteStatus"
    class="status"
></p>


</div>


</div>



<!-- ================================================= -->
<!-- POWER MODAL -->
<!-- ================================================= -->

<div
    id="powerModal"
    class="modal"
>


<div class="modal-content">


<h2 id="powerTitle">

⚠️ Power

</h2>


<p id="powerMessage">

</p>


<input

    id="powerPassword"

    type="password"

    placeholder="GVA-LR Password"

>


<p
    id="powerError"
    class="warning"
></p>


<button
    onclick="closePowerDialog()"
>

Cancel

</button>


<button
    id="powerConfirm"

    class="red"

    onclick="confirmPower()"
>

Confirm

</button>


</div>


</div>



<script>

let powerAction = null;


// =========================================================
// LOGOUT
// =========================================================

function logout() {

    api(
        "/logout",
        {}
    )

    .then(() => {

        window.location =
            "/login";

    });

}







// =========================================================
// QUICK LAUNCHER
// =========================================================

function quickLaunch(appName) {

    api(
        "/launcher/open",
        {
            app: appName
        }
    )
    .then(result => {

        launcherStatus.innerText =
            result.message || "";

    });

}


// =========================================================
// DESKTOP REMOTE
// =========================================================



let autoPreviewTimer = null;
let autoPreviewBusy = false;


function toggleAutoPreview() {

    if (autoPreviewTimer) {

        stopAutoPreview();

    }
    else {

        startAutoPreview();

    }

}


function startAutoPreview() {

    if (autoPreviewTimer) {
        return;
    }

    const interval =
        parseInt(
            document.getElementById(
                "autoPreviewSpeed"
            ).value,
            10
        );

    autoPreviewButton.innerText =
        "⏹️ Stop Auto Preview";

    // Show one frame immediately.
    refreshDesktopScreen();

    autoPreviewTimer =
        setInterval(
            () => {

                if (!autoPreviewBusy) {
                    refreshDesktopScreen();
                }

            },
            interval
        );

}


function stopAutoPreview() {

    if (autoPreviewTimer) {

        clearInterval(
            autoPreviewTimer
        );

        autoPreviewTimer = null;

    }

    autoPreviewButton.innerText =
        "▶️ Start Auto Preview";

}


function restartAutoPreviewIfRunning() {

    if (!autoPreviewTimer) {
        return;
    }

    stopAutoPreview();

    startAutoPreview();

}


function refreshDesktopScreen() {

    if (autoPreviewBusy) {
        return;
    }

    autoPreviewBusy = true;

    const image =
        document.getElementById(
            "desktopScreenPreview"
        );

    const placeholder =
        document.getElementById(
            "desktopScreenPlaceholder"
        );

    placeholder.innerText =
        "Capturing...";

    fetch(
        "/desktop/screenshot",
        {
            method: "POST",
            headers: {
                "X-CSRF-Token": CSRF_TOKEN
            },
            credentials: "same-origin"
        }
    )
    .then(response => {

        if (!response.ok) {
            throw new Error(
                "Screenshot failed"
            );
        }

        return response.blob();

    })
    .then(blob => {

        const oldUrl =
            image.dataset.objectUrl;

        if (oldUrl) {
            URL.revokeObjectURL(
                oldUrl
            );
        }

        const objectUrl =
            URL.createObjectURL(
                blob
            );

        image.dataset.objectUrl =
            objectUrl;

        image.src =
            objectUrl;

        image.style.display =
            "block";

        placeholder.innerText =
            "Updated now";

        autoPreviewBusy = false;

    })
    .catch(error => {

        placeholder.innerText =
            "Could not capture screen";

        autoPreviewBusy = false;

    });

}


let desktopTouchStartX = 0;
let desktopTouchStartY = 0;
let desktopLastX = 0;
let desktopLastY = 0;
let desktopMoved = false;


function openDesktopRemote() {

    showPage("desktopRemotePage");

}


function desktopMouse(action) {

    api(
        "/desktop/mouse",
        {
            action: action
        }
    )
    .then(result => {

        desktopRemoteStatus.innerText =
            result.message || "";

    });

}


function desktopMove(dx, dy) {

    fetch(
        "/desktop/move",
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": CSRF_TOKEN
            },
            body: JSON.stringify({
                dx: dx,
                dy: dy
            })
        }
    );

}


function desktopTypeText() {

    const input =
        document.getElementById("desktopTypeInput");

    if (!input.value) {
        return;
    }

    api(
        "/desktop/type",
        {
            text: input.value
        }
    )
    .then(result => {

        desktopRemoteStatus.innerText =
            result.message || "";

        if (result.status === "success") {
            input.value = "";
        }

    });

}


function desktopKey(key) {

    api(
        "/desktop/key",
        {
            key: key
        }
    );

}


function desktopShortcut(action) {

    api(
        "/desktop/shortcut",
        {
            action: action
        }
    );

}


document.addEventListener(
    "DOMContentLoaded",
    () => {

        const pad =
            document.getElementById(
                "desktopTouchpad"
            );

        if (!pad) {
            return;
        }

        pad.addEventListener(
            "pointerdown",
            event => {

                desktopTouchStartX =
                    event.clientX;

                desktopTouchStartY =
                    event.clientY;

                desktopLastX =
                    event.clientX;

                desktopLastY =
                    event.clientY;

                desktopMoved = false;

                pad.setPointerCapture(
                    event.pointerId
                );

            }
        );


        pad.addEventListener(
            "pointermove",
            event => {

                if (
                    !pad.hasPointerCapture(
                        event.pointerId
                    )
                ) {
                    return;
                }

                const dx =
                    event.clientX
                    - desktopLastX;

                const dy =
                    event.clientY
                    - desktopLastY;

                desktopLastX =
                    event.clientX;

                desktopLastY =
                    event.clientY;

                if (
                    Math.abs(
                        event.clientX
                        - desktopTouchStartX
                    ) > 4
                    ||
                    Math.abs(
                        event.clientY
                        - desktopTouchStartY
                    ) > 4
                ) {
                    desktopMoved = true;
                }

                if (
                    Math.abs(dx) >= 1
                    || Math.abs(dy) >= 1
                ) {

                    // Slight acceleration makes the phone pad
                    // comfortable on a laptop-sized display.
                    desktopMove(
                        Math.round(dx * 1.6),
                        Math.round(dy * 1.6)
                    );

                }

            }
        );


        pad.addEventListener(
            "pointerup",
            event => {

                if (!desktopMoved) {
                    desktopMouse(
                        "left_click"
                    );
                }

                try {
                    pad.releasePointerCapture(
                        event.pointerId
                    );
                }
                catch (error) {
                }

            }
        );

    }
);


// =========================================================
// LAPTOP STATUS
// =========================================================

function openLaptopStatus() {

    showPage("statusPage");

    loadLaptopStatus();

}


function loadLaptopStatus() {

    api(
        "/system/status",
        {}
    )
    .then(result => {

        if (result.status !== "success") {

            statusMessage.innerText =
                result.message || "Could not read laptop status";

            return;
        }

        statusBattery.innerText =
            result.battery.available
            ? (
                result.battery.percent + "%"
                + (result.battery.charging ? " • Charging ⚡" : " • On battery")
            )
            : "Battery information unavailable";

        statusCpu.innerText =
            "CPU: " + result.cpu_percent + "%";

        statusRam.innerText =
            "RAM: "
            + result.ram.percent + "% used"
            + " • "
            + result.ram.used_gb + " / "
            + result.ram.total_gb + " GB";

        statusDisk.innerText =
            "Disk: "
            + result.disk.percent + "% used"
            + " • "
            + result.disk.free_gb + " GB free";

        statusHost.innerText =
            "Computer: " + result.hostname;

        statusIp.innerText =
            "IP: " + result.ip;

        statusUptime.innerText =
            "Uptime: " + result.uptime;

        statusMessage.innerText =
            "Updated now";

    });

}


// =========================================================
// ROCK FILES
// =========================================================

let rockFilesPath = "";

function openRockFiles() {
    rockFilesPath = "";
    showPage("filesPage");
    loadRockFiles();
}

function loadRockFiles() {
    api("/files/list", {path: rockFilesPath}).then(result => {
        if (result.status !== "success") {
            filesStatus.innerText = result.message || "Could not load files";
            return;
        }

        rockFilesPath = result.path || "";
        filesCurrentPath.innerText = "/" + rockFilesPath;

        const list = document.getElementById("rockFilesList");
        list.innerHTML = "";

        if (!result.items.length) {
            list.innerHTML = "<p>Folder is empty.</p>";
            return;
        }

        result.items.forEach(item => {
            const row = document.createElement("div");
            row.style.padding = "10px 0";
            row.style.borderBottom = "1px solid #555";

            const title = document.createElement("div");
            title.textContent = (item.type === "folder" ? "📁 " : "📄 ") + item.name;
            row.appendChild(title);

            if (item.type === "folder") {
                const b = document.createElement("button");
                b.textContent = "📂 Open";
                b.onclick = () => {
                    rockFilesPath = item.path;
                    loadRockFiles();
                };
                row.appendChild(b);
            } else {
                const b = document.createElement("button");
                b.textContent = "⬇ Download";
                b.onclick = () => {
                    window.location = "/files/download?path=" + encodeURIComponent(item.path);
                };
                row.appendChild(b);
            }

            const rename = document.createElement("button");
            rename.textContent = "✏️ Rename";
            rename.onclick = () => renameRockItem(item);
            row.appendChild(rename);

            const del = document.createElement("button");
            del.textContent = "🗑 Delete";
            del.className = "red";
            del.onclick = () => deleteRockItem(item);
            row.appendChild(del);

            list.appendChild(row);
        });
    });
}

function filesGoUp() {
    if (!rockFilesPath) return;
    const parts = rockFilesPath.split("/");
    parts.pop();
    rockFilesPath = parts.join("/");
    loadRockFiles();
}

function uploadRockFile() {
    const input = document.getElementById("rockFileUpload");
    if (!input.files.length) {
        filesStatus.innerText = "Choose a file first";
        return;
    }

    const data = new FormData();
    data.append("file", input.files[0]);
    data.append("path", rockFilesPath);

    fetch("/files/upload", {
        method: "POST",
        headers: {
            "X-CSRF-Token": CSRF_TOKEN
        },
        body: data,
        credentials: "same-origin"
    })
    .then(r => r.json())
    .then(result => {
        filesStatus.innerText = result.message || "";
        if (result.status === "success") {
            input.value = "";
            loadRockFiles();
        }
    });
}

function createRockFolder() {
    const input = document.getElementById("newFolderName");
    const name = input.value.trim();
    if (!name) return;

    api("/files/mkdir", {path: rockFilesPath, name: name}).then(result => {
        filesStatus.innerText = result.message || "";
        if (result.status === "success") {
            input.value = "";
            loadRockFiles();
        }
    });
}

function renameRockItem(item) {
    const name = prompt("New name:", item.name);
    if (!name || name === item.name) return;

    api("/files/rename", {path: item.path, name: name}).then(result => {
        filesStatus.innerText = result.message || "";
        if (result.status === "success") loadRockFiles();
    });
}

function deleteRockItem(item) {
    if (!confirm("Delete " + item.name + "?")) return;

    api("/files/delete", {path: item.path}).then(result => {
        filesStatus.innerText = result.message || "";
        if (result.status === "success") loadRockFiles();
    });
}


// =========================================================
// ROCK CLIPBOARD
// =========================================================

function sendClipboardToLaptop() {

    const value =
        document.getElementById("clipboardSendText").value;

    api(
        "/clipboard/set",
        {
            text: value
        }
    )
    .then(result => {

        clipboardStatus.innerText =
            result.message || "Done";

    });

}


function getClipboardFromLaptop() {

    api(
        "/clipboard/get",
        {}
    )
    .then(result => {

        if (result.status === "success") {

            clipboardReceiveText.value =
                result.text || "";

        }

        clipboardStatus.innerText =
            result.message || "";

    });

}


async function copyReceivedClipboard() {

    const value =
        document.getElementById("clipboardReceiveText").value;

    try {

        await navigator.clipboard.writeText(value);

        clipboardStatus.innerText =
            "Copied on phone";

    }
    catch (error) {

        clipboardReceiveText.focus();
        clipboardReceiveText.select();

        clipboardStatus.innerText =
            "Select the text and use Copy";

    }

}


// =========================================================
// SYSTEM
// =========================================================

function openDeviceControls() {

    showPage("deviceControlsPage");

    api(
        "/device-control",
        {
            action: "status"
        }
    )

    .then(result => {

        if (result.status !== "success") {

            deviceControlStatus.innerText =
                result.message;

            return;
        }

        systemBrightness.value =
            result.brightness;

        brightnessText.innerText =
            result.brightness + "%";

        systemVolume.value =
            result.volume;

        systemVolumeText.innerText =
            result.volume + "%";

        deviceControlStatus.innerText =
            result.muted
            ? "🔇 System audio muted"
            : "🔊 System audio active";

    });

}


function setBrightness(value) {

    api(
        "/device-control",
        {
            action: "brightness",
            value: Number(value)
        }
    )

    .then(result => {

        deviceControlStatus.innerText =
            result.message;

        if (result.brightness !== undefined) {

            systemBrightness.value =
                result.brightness;

            brightnessText.innerText =
                result.brightness + "%";

        }

    });

}


function changeBrightness(amount) {

    const value =
        Math.max(
            0,
            Math.min(
                100,
                Number(systemBrightness.value)
                + amount
            )
        );

    systemBrightness.value = value;

    brightnessText.innerText =
        value + "%";

    setBrightness(value);

}


function setSystemVolume(value) {

    api(
        "/device-control",
        {
            action: "volume",
            value: Number(value)
        }
    )

    .then(result => {

        deviceControlStatus.innerText =
            result.message;

        if (result.volume !== undefined) {

            systemVolume.value =
                result.volume;

            systemVolumeText.innerText =
                result.volume + "%";

        }

    });

}


function changeSystemVolume(amount) {

    const value =
        Math.max(
            0,
            Math.min(
                100,
                Number(systemVolume.value)
                + amount
            )
        );

    systemVolume.value = value;

    systemVolumeText.innerText =
        value + "%";

    setSystemVolume(value);

}


function toggleSystemMute() {

    api(
        "/device-control",
        {
            action: "mute"
        }
    )

    .then(result => {

        deviceControlStatus.innerText =
            result.message;

    });

}


function lockLaptop() {

    api(
        "/system-control",
        {
            action: "lock"
        }
    )

    .then(result => {

        alert(
            result.message
        );

    });

}


function powerDialog(action) {

    powerAction =
        action;


    powerPassword.value =
        "";


    powerError.innerText =
        "";


    if (
        action ===
        "restart"
    ) {

        powerTitle.innerText =
            "⚠️ Restart Laptop?";


        powerMessage.innerText =
            "The laptop will restart and GVA-LR will disconnect.";


        powerConfirm.innerText =
            "🔄 Restart";

    }

    else {

        powerTitle.innerText =
            "⚠️ Shutdown Laptop?";


        powerMessage.innerText =
            "The laptop will turn off and GVA-LR will disconnect.";


        powerConfirm.innerText =
            "⏻ Shutdown";

    }


    powerModal.style.display =
        "flex";

}


function closePowerDialog() {

    powerModal.style.display =
        "none";


    powerAction =
        null;

}


function confirmPower() {

    const password =
        powerPassword.value;


    api(
        "/system-control",
        {

            action:
                powerAction,

            password:
                password

        }
    )

    .then(result => {

        if (
            result.status ===
            "success"
        ) {

            powerError.innerText =
                result.message;

        }

        else {

            powerError.innerText =
                "❌ "
                + result.message;

        }

    });

}


// =========================================================
// VLC
// =========================================================

function openVLC() {

    showPage(
        "vlcPage"
    );


    movieList.innerHTML =
        "Loading...";


    fetch("/videos")

    .then(response => {

        if (
            response.status === 401
        ) {

            window.location =
                "/login";

        }

        return response.json();

    })

    .then(videos => {

        movieList.innerHTML =
            "";


        if (
            videos.length === 0
        ) {

            movieList.innerHTML =
                "No videos found.";

            return;

        }


        videos.forEach(
            video => {

                const button =
                    document.createElement(
                        "button"
                    );


                button.className =
                    "movie";


                button.innerText =
                    "🎞️ " + video;


                button.onclick =
                    () => playMovie(
                        video
                    );


                movieList.appendChild(
                    button
                );

            }
        );

    });

}


function playMovie(filename) {

    api(
        "/play-video",
        {
            filename:
                filename
        }
    )

    .then(result => {

        if (
            result.status ===
            "success"
        ) {

            movieName.innerText =
                filename;


            timeline.value =
                0;


            timelineText.innerText =
                "0%";


            showPage(
                "vlcPlayerPage"
            );

        }

        else {

            alert(
                result.message
            );

        }

    });

}


function vlc(action) {

    api(
        "/vlc-control",
        {
            action:
                action
        }
    );

}


function seekVLC(value) {

    api(
        "/vlc-control",
        {

            action:
                "seek",

            value:
                value

        }
    );

}


function vlcVolume(value) {

    api(
        "/vlc-control",
        {

            action:
                "volume",

            value:
                value

        }
    );

}


function closeVLC() {

    api(
        "/vlc-control",
        {
            action:
                "close"
        }
    )

    .then(() => {

        showPage(
            "vlcPage"
        );

    });

}


// =========================================================
// NOTES
// =========================================================

function openNotes() {

    showPage(
        "notesPage"
    );


    fetch("/notes")

    .then(response => {

        if (
            response.status === 401
        ) {

            window.location =
                "/login";

        }

        return response.json();

    })

    .then(files => {

        notesList.innerHTML =
            "";


        if (
            files.length === 0
        ) {

            notesList.innerHTML =
                "<p>No notes.</p>";

            return;

        }


        files.forEach(
            file => {

                const button =
                    document.createElement(
                        "button"
                    );


                button.className =
                    "note";


                button.innerText =
                    "📄 " + file;


                button.onclick =
                    () => readNote(
                        file
                    );


                notesList.appendChild(
                    button
                );

            }
        );

    });

}


function newNote() {

    noteFilename.value =
        "";


    noteText.value =
        "";


    noteStatus.innerText =
        "New note";


    showPage(
        "noteEditorPage"
    );

}


function readNote(filename) {

    api(
        "/note/read",
        {
            filename:
                filename
        }
    )

    .then(result => {

        if (
            result.status ===
            "success"
        ) {

            noteFilename.value =
                result.filename;


            noteText.value =
                result.text;


            noteStatus.innerText =
                "Loaded";


            showPage(
                "noteEditorPage"
            );

        }

    });

}


function saveNote() {

    api(
        "/note/save",
        {

            filename:
                noteFilename.value,

            text:
                noteText.value

        }
    )

    .then(result => {

        noteStatus.innerText =
            result.message;


        if (
            result.status ===
            "success"
        ) {

            noteFilename.value =
                result.filename;

        }

    });

}


function openNoteLaptop() {

    api(
        "/note/open",
        {
            filename:
                noteFilename.value
        }
    )

    .then(result => {

        noteStatus.innerText =
            result.message;

    });

}


function deleteNote() {

    if (
        !confirm(
            "Delete this note?"
        )
    ) {

        return;

    }


    api(
        "/note/delete",
        {
            filename:
                noteFilename.value
        }
    )

    .then(result => {

        if (
            result.status ===
            "success"
        ) {

            openNotes();

        }

        else {

            noteStatus.innerText =
                result.message;

        }

    });

}


// =========================================================
// BRAVE
// =========================================================

function brave(action) {

    braveStatus.innerText =
        "Sending...";


    api(
        "/brave-control",
        {
            action:
                action
        }
    )

    .then(result => {

        braveStatus.innerText =
            result.message;

    });

}


function braveGo() {

    api(
        "/brave-control",
        {

            action:
                "go",

            value:
                braveInput.value

        }
    )

    .then(result => {

        braveStatus.innerText =
            result.message;

    });

}


// =========================================================
// BRAVE TOUCHPAD / MOUSE
// =========================================================

function braveMouse(action, dx = 0, dy = 0) {

    return api(
        "/brave-control",
        {
            action: action,
            dx: dx,
            dy: dy
        }
    ).then(result => {
        braveStatus.innerText = result.message;
        return result;
    });
}


function braveTypeText() {

    const text = braveTypeInput.value;

    if (!text) {
        return;
    }

    api(
        "/brave-control",
        {
            action: "type_text",
            value: text
        }
    ).then(result => {
        braveStatus.innerText = result.message;
    });
}


let touchpadLastX = null;
let touchpadLastY = null;
let touchpadMoved = false;
let touchpadPendingX = 0;
let touchpadPendingY = 0;
let touchpadSending = false;

function sendTouchpadMove() {

    if (touchpadSending || (touchpadPendingX === 0 && touchpadPendingY === 0)) {
        return;
    }

    const dx = touchpadPendingX;
    const dy = touchpadPendingY;

    touchpadPendingX = 0;
    touchpadPendingY = 0;
    touchpadSending = true;

    braveMouse("mouse_move", dx, dy).finally(() => {
        touchpadSending = false;
        if (touchpadPendingX !== 0 || touchpadPendingY !== 0) {
            sendTouchpadMove();
        }
    });
}

window.addEventListener("load", () => {

    const pad = document.getElementById("braveTouchpad");

    if (!pad) return;

    pad.addEventListener("pointerdown", event => {
        pad.setPointerCapture(event.pointerId);
        touchpadLastX = event.clientX;
        touchpadLastY = event.clientY;
        touchpadMoved = false;
    });

    pad.addEventListener("pointermove", event => {

        if (touchpadLastX === null || touchpadLastY === null) return;

        const dx = event.clientX - touchpadLastX;
        const dy = event.clientY - touchpadLastY;

        touchpadLastX = event.clientX;
        touchpadLastY = event.clientY;

        if (Math.abs(dx) + Math.abs(dy) > 1) {
            touchpadMoved = true;
            touchpadPendingX += Math.round(dx * 1.5);
            touchpadPendingY += Math.round(dy * 1.5);
            sendTouchpadMove();
        }
    });

    pad.addEventListener("pointerup", () => {
        if (!touchpadMoved) {
            braveMouse("left_click");
        }
        touchpadLastX = null;
        touchpadLastY = null;
    });

    pad.addEventListener("pointercancel", () => {
        touchpadLastX = null;
        touchpadLastY = null;
    });
});


// =========================================================
// YOUTUBE SEARCH
// =========================================================

function searchYouTube() {

    const query =
        youtubeSearch.value.trim();


    if (!query) {

        return;

    }


    youtubeStatus.innerText =
        "Searching YouTube...";


    youtubeResults.innerHTML =
        "Loading...";


    api(
        "/youtube/search",
        {
            query:
                query
        }
    )

    .then(result => {

        youtubeResults.innerHTML =
            "";


        if (
            result.status !==
            "success"
        ) {

            youtubeStatus.innerText =
                result.message;

            return;

        }


        youtubeStatus.innerText =
            result.results.length
            + " results";


        result.results.forEach(
            video => {

                const button =
                    document.createElement(
                        "button"
                    );


                button.className =
                    "youtube-result";


                const title =
                    document.createElement(
                        "div"
                    );


                title.className =
                    "youtube-title";


                title.textContent =
                    "▶ " + video.title;


                const channel =
                    document.createElement(
                        "div"
                    );


                channel.className =
                    "youtube-channel";


                channel.textContent =
                    video.channel || "";


                button.appendChild(
                    title
                );


                button.appendChild(
                    channel
                );


                button.onclick =
                    () => playYouTube(
                        video
                    );


                youtubeResults.appendChild(
                    button
                );

            }
        );

    });

}


// =========================================================
// PLAY YOUTUBE RESULT
// =========================================================

function playYouTube(video) {

    api(
        "/youtube/play",
        {
            id:
                video.id
        }
    )

    .then(result => {

        if (
            result.status ===
            "success"
        ) {

            youtubePlaying.innerText =
                video.title;


            youtubeChannel.innerText =
                video.channel || "";


            youtubeRemoteStatus.innerText =
                "Opening in Brave...";


            showPage(
                "youtubePlayerPage"
            );

        }

        else {

            youtubeStatus.innerText =
                result.message;

        }

    });

}


// =========================================================
// YOUTUBE CONTROL
// =========================================================

function youtubeControl(action) {

    youtubeRemoteStatus.innerText =
        "Sending...";


    api(
        "/youtube/control",
        {
            action:
                action
        }
    )

    .then(result => {

        youtubeRemoteStatus.innerText =
            result.message;

    });

}

</script>


</body>

</html>
"""


# =========================================================
# DISPLAY / VOLUME HELPERS
# =========================================================

def _run_brightness_powershell(command):

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            command
        ],
        capture_output=True,
        text=True,
        timeout=5
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or "Brightness command failed"
        )

    return result.stdout


def get_brightness():

    # Use the same WMI interface verified directly on this laptop.
    output = _run_brightness_powershell(
        "$m = Get-WmiObject -Namespace root/WMI "
        "-Class WmiMonitorBrightness; "
        "$m.CurrentBrightness"
    )

    values = [
        line.strip()
        for line in output.splitlines()
        if line.strip().isdigit()
    ]

    if not values:
        raise RuntimeError(
            "Brightness is not available"
        )

    return int(values[0])


def set_brightness_value(value):

    value = max(
        0,
        min(
            100,
            int(value)
        )
    )

    # This exact Get-WmiObject + WmiSetBrightness form was
    # verified successfully on the laptop before integration.
    command = (
        "$m = Get-WmiObject -Namespace root/WMI "
        "-Class WmiMonitorBrightnessMethods; "
        f"$m.WmiSetBrightness(1,{value}) | Out-Null"
    )

    _run_brightness_powershell(command)

    return value


def _with_volume_endpoint(callback):

    if not AUDIO_CONTROL_AVAILABLE:
        raise RuntimeError(
            "Install audio support: "
            "pip install pycaw comtypes"
        )

    # Flask handles requests on worker threads. COM must be
    # initialized inside the thread that uses the audio endpoint.
    comtypes.CoInitialize()

    try:
        device = AudioUtilities.GetSpeakers()
        endpoint = device.EndpointVolume

        if endpoint is None:
            raise RuntimeError(
                "Windows audio endpoint is not available"
            )

        return callback(endpoint)

    finally:
        comtypes.CoUninitialize()


def get_system_volume():

    def read(endpoint):
        volume = round(
            endpoint.GetMasterVolumeLevelScalar()
            * 100
        )

        muted = bool(
            endpoint.GetMute()
        )

        return volume, muted

    return _with_volume_endpoint(read)


def set_system_volume_value(value):

    value = max(
        0,
        min(
            100,
            int(value)
        )
    )

    def write(endpoint):
        endpoint.SetMasterVolumeLevelScalar(
            value / 100.0,
            None
        )
        return value

    return _with_volume_endpoint(write)


def toggle_system_mute():

    def toggle(endpoint):
        muted = bool(
            endpoint.GetMute()
        )

        new_muted = not muted

        endpoint.SetMute(
            new_muted,
            None
        )

        return new_muted

    return _with_volume_endpoint(toggle)


# =========================================================
# DISPLAY / VOLUME CONTROL
# =========================================================

@app.route(
    "/device-control",
    methods=["POST"]
)
def device_control():

    security = api_security()

    if security:

        return security

    data = request.get_json() or {}

    action = data.get(
        "action"
    )

    try:

        if action == "status":

            brightness = get_brightness()

            volume, muted = (
                get_system_volume()
            )

            return jsonify({
                "status": "success",
                "brightness": brightness,
                "volume": volume,
                "muted": muted
            })


        if action == "brightness":

            value = int(
                data.get(
                    "value",
                    50
                )
            )

            value = set_brightness_value(
                value
            )

            return jsonify({
                "status": "success",
                "message":
                    f"Brightness {value}%",
                "brightness": value
            })


        if action == "volume":

            value = int(
                data.get(
                    "value",
                    50
                )
            )

            value = set_system_volume_value(
                value
            )

            return jsonify({
                "status": "success",
                "message":
                    f"Volume {value}%",
                "volume": value
            })


        if action == "mute":

            new_muted = toggle_system_mute()

            return jsonify({
                "status": "success",
                "message":
                    "System audio muted"
                    if new_muted
                    else
                    "System audio unmuted",
                "muted": new_muted
            })


        return jsonify({
            "status": "error",
            "message":
                "Invalid device action"
        }), 400


    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "status": "error",
            "message":
                "Invalid value"
        }), 400


    except Exception as error:

        print(
            "Device control:",
            error
        )

        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500


# =========================================================
# SYSTEM CONTROL
# =========================================================

@app.route(
    "/system-control",
    methods=["POST"]
)
def system_control():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}

    action = data.get(
        "action"
    )


    # -----------------------------------------------------
    # LOCK
    # -----------------------------------------------------

    if action == "lock":

        try:

            ctypes.windll.user32.LockWorkStation()


            return jsonify({
                "status": "success",
                "message": "Laptop locked"
            })


        except Exception as error:

            print(
                "Lock error:",
                error
            )


            return jsonify({
                "status": "error",
                "message": "Could not lock laptop"
            }), 500


    # -----------------------------------------------------
    # RESTART / SHUTDOWN REQUIRE PASSWORD AGAIN
    # -----------------------------------------------------

    if action in (
        "restart",
        "shutdown"
    ):

        password = data.get(
            "password",
            ""
        )


        if not check_password(
            password
        ):

            return jsonify({
                "status": "error",
                "message": "Incorrect password"
            }), 403


        if action == "restart":

            subprocess.Popen([
                "shutdown",
                "/r",
                "/t",
                "0"
            ])


            return jsonify({
                "status": "success",
                "message": "Restarting laptop..."
            })


        subprocess.Popen([
            "shutdown",
            "/s",
            "/t",
            "0"
        ])


        return jsonify({
            "status": "success",
            "message": "Shutting down laptop..."
        })


    return jsonify({
        "status": "error",
        "message": "Invalid system action"
    }), 400


# =========================================================
# VIDEO LIST
# =========================================================

@app.route("/videos")
def videos():

    if not authenticated():

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401


    result = []


    try:

        for filename in os.listdir(
            VIDEO_FOLDER
        ):

            if filename.lower().endswith(
                (
                    ".mp4",
                    ".mkv",
                    ".avi",
                    ".mov",
                    ".webm"
                )
            ):

                result.append(
                    filename
                )


        result.sort()


        return jsonify(
            result
        )


    except Exception as error:

        print(
            "Videos:",
            error
        )


        return jsonify([])


# =========================================================
# PLAY VIDEO
# =========================================================

@app.route(
    "/play-video",
    methods=["POST"]
)
def play_video():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}

    filename = data.get(
        "filename",
        ""
    )


    filename = os.path.basename(
        filename
    )


    path = os.path.abspath(
        os.path.join(
            VIDEO_FOLDER,
            filename
        )
    )


    root = os.path.abspath(
        VIDEO_FOLDER
    )


    try:

        if (
            os.path.commonpath(
                [root, path]
            )
            != root
        ):

            raise ValueError(
                "Invalid path"
            )

    except ValueError:

        return jsonify({
            "status": "error",
            "message": "Invalid video path"
        }), 400


    if not os.path.isfile(
        path
    ):

        return jsonify({
            "status": "error",
            "message": "Video not found"
        }), 404


    subprocess.run(

        [
            "taskkill",
            "/F",
            "/IM",
            "vlc.exe"
        ],

        stdout=subprocess.DEVNULL,

        stderr=subprocess.DEVNULL

    )


    time.sleep(0.2)


    subprocess.Popen([

        VLC_PATH,

        "--extraintf=rc",

        "--rc-host=127.0.0.1:4212",

        path

    ])


    return jsonify({
        "status": "success",
        "message": "Playing " + filename
    })


# =========================================================
# VLC CONTROL
# =========================================================

@app.route(
    "/vlc-control",
    methods=["POST"]
)
def vlc_control():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}

    action = data.get(
        "action"
    )


    if action == "pause":

        success = vlc_command(
            "pause"
        )


    elif action == "fullscreen":

        success = vlc_command(
            "fullscreen"
        )


    elif action == "seek":

        try:

            value = int(
                data.get(
                    "value",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            return jsonify({
                "status": "error",
                "message": "Invalid seek"
            }), 400


        value = max(
            0,
            min(
                100,
                value
            )
        )


        success = vlc_command(
            f"seek {value}%"
        )


    elif action == "volume":

        try:

            value = int(
                data.get(
                    "value",
                    50
                )
            )

        except (
            TypeError,
            ValueError
        ):

            return jsonify({
                "status": "error",
                "message": "Invalid volume"
            }), 400


        value = max(
            0,
            min(
                100,
                value
            )
        )


        vlc_value = int(
            value
            * 256
            / 100
        )


        success = vlc_command(
            f"volume {vlc_value}"
        )


    elif action == "close":

        subprocess.run(

            [
                "taskkill",
                "/F",
                "/IM",
                "vlc.exe"
            ],

            stdout=subprocess.DEVNULL,

            stderr=subprocess.DEVNULL

        )


        return jsonify({
            "status": "success",
            "message": "VLC closed"
        })


    else:

        return jsonify({
            "status": "error",
            "message": "Invalid VLC action"
        }), 400


    if not success:

        return jsonify({
            "status": "error",
            "message": "VLC not responding"
        }), 503


    return jsonify({
        "status": "success",
        "message": "Command sent"
    })


# =========================================================
# NOTES LIST
# =========================================================

@app.route("/notes")
def notes():

    if not authenticated():

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401


    result = []


    try:

        for filename in os.listdir(
            NOTES_FOLDER
        ):

            if filename.lower().endswith(
                ".txt"
            ):

                result.append(
                    filename
                )


        result.sort()


        return jsonify(
            result
        )


    except Exception:

        return jsonify([])


# =========================================================
# READ NOTE
# =========================================================

@app.route(
    "/note/read",
    methods=["POST"]
)
def note_read():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}


    path = safe_note_path(
        data.get(
            "filename",
            ""
        )
    )


    if (
        not path
        or
        not os.path.isfile(path)
    ):

        return jsonify({
            "status": "error",
            "message": "Note not found"
        }), 404


    with open(
        path,
        "r",
        encoding="utf-8"
    ) as file:

        text = file.read()


    return jsonify({

        "status": "success",

        "filename":
            os.path.basename(
                path
            ),

        "text":
            text

    })


# =========================================================
# SAVE NOTE
# =========================================================

@app.route(
    "/note/save",
    methods=["POST"]
)
def note_save():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}


    path = safe_note_path(
        data.get(
            "filename",
            ""
        )
    )


    if not path:

        return jsonify({
            "status": "error",
            "message": "Invalid filename"
        }), 400


    text = data.get(
        "text",
        ""
    )


    if not isinstance(
        text,
        str
    ):

        return jsonify({
            "status": "error",
            "message": "Invalid text"
        }), 400


    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            text
        )


    return jsonify({

        "status": "success",

        "message": "Saved",

        "filename":
            os.path.basename(
                path
            )

    })


# =========================================================
# OPEN NOTE
# =========================================================

@app.route(
    "/note/open",
    methods=["POST"]
)
def note_open():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}


    path = safe_note_path(
        data.get(
            "filename",
            ""
        )
    )


    if (
        not path
        or
        not os.path.isfile(path)
    ):

        return jsonify({
            "status": "error",
            "message": "Save the note first"
        }), 404


    subprocess.Popen([
        "notepad.exe",
        path
    ])


    return jsonify({
        "status": "success",
        "message": "Opened in Notepad"
    })


# =========================================================
# DELETE NOTE
# =========================================================

@app.route(
    "/note/delete",
    methods=["POST"]
)
def note_delete():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}


    path = safe_note_path(
        data.get(
            "filename",
            ""
        )
    )


    if (
        not path
        or
        not os.path.isfile(path)
    ):

        return jsonify({
            "status": "error",
            "message": "Note not found"
        }), 404


    os.remove(
        path
    )


    return jsonify({
        "status": "success",
        "message": "Deleted"
    })


# =========================================================
# BRAVE CONTROL
# =========================================================

@app.route(
    "/brave-control",
    methods=["POST"]
)
def brave_control():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}

    action = data.get(
        "action"
    )


    # -----------------------------------------------------
    # OPEN
    # -----------------------------------------------------

    if action == "open":

        subprocess.Popen([
            BRAVE_PATH
        ])


        return jsonify({
            "status": "success",
            "message": "Brave opened"
        })


    # -----------------------------------------------------
    # SEARCH / URL
    # -----------------------------------------------------

    if action == "go":

        value = data.get(
            "value",
            ""
        ).strip()


        if not value:

            return jsonify({
                "status": "error",
                "message": "Enter search or URL"
            }), 400


        if (
            "." in value
            and
            " " not in value
        ):

            if not value.startswith(
                (
                    "http://",
                    "https://"
                )
            ):

                value = (
                    "https://"
                    + value
                )


            target = value


        else:

            target = (
                "https://www.google.com/search?q="
                + urllib.parse.quote_plus(
                    value
                )
            )


        if not navigate_brave_url(
            target
        ):

            return jsonify({
                "status": "error",
                "message": "Brave not found"
            }), 500


        return jsonify({
            "status": "success",
            "message": "Opened"
        })


    # -----------------------------------------------------
    # NEW TAB
    # -----------------------------------------------------

    if action == "new_tab":

        subprocess.Popen([

            BRAVE_PATH,

            "--new-tab",

            "brave://newtab"

        ])


        return jsonify({
            "status": "success",
            "message": "New tab opened"
        })


    # -----------------------------------------------------
    # CLOSE BRAVE
    # -----------------------------------------------------

    if action == "close_brave":

        subprocess.run(

            [
                "taskkill",
                "/F",
                "/IM",
                "brave.exe"
            ],

            stdout=subprocess.DEVNULL,

            stderr=subprocess.DEVNULL

        )


        return jsonify({
            "status": "success",
            "message": "Brave closed"
        })


    # -----------------------------------------------------
    # FOCUS REQUIRED
    # -----------------------------------------------------

    if not focus_brave():

        return jsonify({
            "status": "error",
            "message": "Brave window not found"
        }), 404


    # -----------------------------------------------------
    # TOUCHPAD / MOUSE / TEXT
    # -----------------------------------------------------

    if action == "mouse_move":

        try:
            dx = int(data.get("dx", 0))
            dy = int(data.get("dy", 0))
        except (TypeError, ValueError):
            return jsonify({
                "status": "error",
                "message": "Invalid mouse movement"
            }), 400

        # Limit each request so a bad phone event cannot throw
        # the pointer an extreme distance.
        dx = max(-300, min(300, dx))
        dy = max(-300, min(300, dy))

        pyautogui.moveRel(dx, dy, duration=0)

        return jsonify({
            "status": "success",
            "message": "Mouse moved"
        })


    if action == "left_click":

        pyautogui.click()

        return jsonify({
            "status": "success",
            "message": "Clicked"
        })


    if action == "right_click":

        pyautogui.rightClick()

        return jsonify({
            "status": "success",
            "message": "Right clicked"
        })


    if action == "type_text":

        value = str(data.get("value", ""))

        if not value:
            return jsonify({
                "status": "error",
                "message": "Enter text"
            }), 400

        if len(value) > 500:
            return jsonify({
                "status": "error",
                "message": "Text is too long"
            }), 400

        pyautogui.write(value, interval=0.01)

        return jsonify({
            "status": "success",
            "message": "Text typed"
        })


    commands = {

        "back":
            lambda:
            pyautogui.hotkey(
                "alt",
                "left"
            ),

        "forward":
            lambda:
            pyautogui.hotkey(
                "alt",
                "right"
            ),

        "refresh":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "r"
            ),

        "scroll_up":
            lambda:
            pyautogui.scroll(
                5
            ),

        "scroll_down":
            lambda:
            pyautogui.scroll(
                -5
            ),

        "page_up":
            lambda:
            pyautogui.press(
                "pageup"
            ),

        "page_down":
            lambda:
            pyautogui.press(
                "pagedown"
            ),

        "top":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "home"
            ),

        "bottom":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "end"
            ),

        "zoom_in":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "+"
            ),

        "zoom_out":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "-"
            ),

        "zoom_reset":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "0"
            ),

        "next_tab":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "tab"
            ),

        "previous_tab":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "shift",
                "tab"
            ),

        "close_tab":
            lambda:
            pyautogui.hotkey(
                "ctrl",
                "w"
            ),

        "media_play":
            lambda:
            pyautogui.press(
                "space"
            ),

        "media_back":
            lambda:
            pyautogui.press(
                "left"
            ),

        "media_forward":
            lambda:
            pyautogui.press(
                "right"
            ),

        "media_mute":
            lambda:
            pyautogui.press(
                "m"
            ),

        "media_fullscreen":
            lambda:
            pyautogui.press(
                "f"
            )

    }


    command = commands.get(
        action
    )


    if not command:

        return jsonify({
            "status": "error",
            "message": "Invalid Brave action"
        }), 400


    command()


    return jsonify({
        "status": "success",
        "message": "Command sent"
    })







# =========================================================
# QUICK LAUNCHER
# =========================================================

@app.route(
    "/launcher/open",
    methods=["POST"]
)
def launcher_open():

    security = api_security()

    if security:
        return security

    app_name = (
        (request.get_json() or {})
        .get("app", "")
    )

    # Fixed allow-list only. The phone cannot send an arbitrary
    # command or executable path to this endpoint.
    try:



        if app_name == "calculator":

            subprocess.Popen(
                ["calc.exe"]
            )

            message = "Calculator opened"


        elif app_name == "explorer":

            subprocess.Popen(
                ["explorer.exe"]
            )

            message = "File Explorer opened"


        elif app_name == "rock_folder":

            rock_folder = ROCK_PROJECT_FOLDER

            if not os.path.isdir(
                rock_folder
            ):
                return jsonify({
                    "status": "error",
                    "message": "Rocky project folder was not found"
                }), 404

            subprocess.Popen(
                [
                    "explorer.exe",
                    rock_folder
                ]
            )

            message = "Rocky project folder opened"


        elif app_name == "vscode":

            # 'code' works when VS Code added itself to PATH.
            code_path = shutil.which(
                "code"
            )

            if code_path:

                subprocess.Popen(
                    [
                        code_path,
                        ROCK_PROJECT_FOLDER
                    ]
                )

            else:

                possible_code = os.path.join(
                    os.environ.get(
                        "LOCALAPPDATA",
                        ""
                    ),
                    "Programs",
                    "Microsoft VS Code",
                    "Code.exe"
                )

                if not os.path.isfile(
                    possible_code
                ):
                    return jsonify({
                        "status": "error",
                        "message": "VS Code was not found"
                    }), 404

                subprocess.Popen(
                    [
                        possible_code,
                        ROCK_PROJECT_FOLDER
                    ]
                )

            message = "VS Code opened with Rocky"


        elif app_name == "gitbash":

            candidates = [
                os.path.join(
                    os.environ.get(
                        "ProgramFiles",
                        r"C:\Program Files"
                    ),
                    "Git",
                    "git-bash.exe"
                ),
                os.path.join(
                    os.environ.get(
                        "LOCALAPPDATA",
                        ""
                    ),
                    "Programs",
                    "Git",
                    "git-bash.exe"
                )
            ]

            git_bash = next(
                (
                    path
                    for path in candidates
                    if os.path.isfile(path)
                ),
                None
            )

            if not git_bash:

                return jsonify({
                    "status": "error",
                    "message": "Git Bash was not found"
                }), 404

            subprocess.Popen(
                [
                    git_bash,
                    "--cd="
                    + os.path.join(
                        home,
                        "Desktop",
                        "rocky"
                    )
                ]
            )

            message = "Git Bash opened in Rocky"



        else:

            return jsonify({
                "status": "error",
                "message": "Unknown launcher item"
            }), 400


        return jsonify({
            "status": "success",
            "message": message
        })


    except Exception as error:

        print(
            "Quick launcher:",
            error
        )

        return jsonify({
            "status": "error",
            "message": "Could not open application"
        }), 500


# =========================================================
# DESKTOP REMOTE
# =========================================================


@app.route(
    "/desktop/screenshot",
    methods=["POST"]
)
def desktop_screenshot():

    security = api_security()

    if security:
        return security

    try:

        # Capture directly into memory. No screenshot file is created.
        screenshot = pyautogui.screenshot()

        # PyAutoGUI screenshots do not include the Windows cursor.
        # Draw a high-visibility cursor marker into the in-memory image.
        try:
            from PIL import ImageDraw

            mouse_x, mouse_y = pyautogui.position()

            draw = ImageDraw.Draw(screenshot)

            radius = 10

            draw.ellipse(
                (
                    mouse_x - radius,
                    mouse_y - radius,
                    mouse_x + radius,
                    mouse_y + radius
                ),
                fill="white",
                outline="black",
                width=3
            )

            draw.line(
                (
                    mouse_x - 16,
                    mouse_y,
                    mouse_x + 16,
                    mouse_y
                ),
                fill="black",
                width=2
            )

            draw.line(
                (
                    mouse_x,
                    mouse_y - 16,
                    mouse_x,
                    mouse_y + 16
                ),
                fill="black",
                width=2
            )

        except Exception as cursor_error:
            print(
                "Cursor marker:",
                cursor_error
            )

        # Reduce resolution before transfer to keep CPU/network/battery use low.
        max_width = 1280

        if screenshot.width > max_width:

            ratio = (
                max_width
                / screenshot.width
            )

            new_height = max(
                1,
                int(
                    screenshot.height
                    * ratio
                )
            )

            screenshot = screenshot.resize(
                (
                    max_width,
                    new_height
                )
            )

        image_buffer = BytesIO()

        screenshot.convert(
            "RGB"
        ).save(
            image_buffer,
            format="JPEG",
            quality=65,
            optimize=True
        )

        image_buffer.seek(0)

        response = send_file(
            image_buffer,
            mimetype="image/jpeg",
            download_name="rock-screen.jpg"
        )

        # Prevent browsers/proxies from keeping old desktop screenshots.
        response.headers[
            "Cache-Control"
        ] = (
            "no-store, no-cache, "
            "must-revalidate, max-age=0"
        )

        response.headers[
            "Pragma"
        ] = "no-cache"

        return response

    except Exception as error:

        print(
            "Screenshot:",
            error
        )

        return jsonify({
            "status": "error",
            "message": "Could not capture screen"
        }), 500


@app.route(
    "/desktop/move",
    methods=["POST"]
)
def desktop_move():

    security = api_security()

    if security:
        return security

    data = request.get_json() or {}

    try:
        dx = int(data.get("dx", 0))
        dy = int(data.get("dy", 0))
    except (TypeError, ValueError):
        return jsonify({
            "status": "error",
            "message": "Invalid movement"
        }), 400

    # Limit each request so malformed input cannot throw
    # the pointer wildly across the desktop.
    dx = max(-250, min(250, dx))
    dy = max(-250, min(250, dy))

    pyautogui.moveRel(
        dx,
        dy,
        duration=0
    )

    return jsonify({
        "status": "success"
    })


@app.route(
    "/desktop/mouse",
    methods=["POST"]
)
def desktop_mouse():

    security = api_security()

    if security:
        return security

    action = (
        (request.get_json() or {})
        .get("action", "")
    )

    if action == "left_click":
        pyautogui.click()

    elif action == "right_click":
        pyautogui.rightClick()

    elif action == "double_click":
        pyautogui.doubleClick(
            interval=0.12
        )

    elif action == "scroll_up":
        pyautogui.scroll(5)

    elif action == "scroll_down":
        pyautogui.scroll(-5)

    else:
        return jsonify({
            "status": "error",
            "message": "Invalid mouse action"
        }), 400

    return jsonify({
        "status": "success",
        "message": "Done"
    })


@app.route(
    "/desktop/type",
    methods=["POST"]
)
def desktop_type():

    security = api_security()

    if security:
        return security

    value = (
        (request.get_json() or {})
        .get("text", "")
    )

    if not isinstance(value, str):
        return jsonify({
            "status": "error",
            "message": "Invalid text"
        }), 400

    if len(value) > 10000:
        return jsonify({
            "status": "error",
            "message": "Text is too long"
        }), 413

    # Clipboard paste handles Unicode text more reliably than
    # pyautogui.write on Windows.
    try:
        old_clipboard = pyperclip.paste()
    except Exception:
        old_clipboard = None

    try:
        pyperclip.copy(value)
        pyautogui.hotkey(
            "ctrl",
            "v"
        )

        return jsonify({
            "status": "success",
            "message": "Typed on laptop"
        })

    finally:
        if old_clipboard is not None:
            try:
                time.sleep(0.05)
                pyperclip.copy(
                    old_clipboard
                )
            except Exception:
                pass


@app.route(
    "/desktop/key",
    methods=["POST"]
)
def desktop_key():

    security = api_security()

    if security:
        return security

    key = (
        (request.get_json() or {})
        .get("key", "")
    )

    allowed = {
        "enter",
        "escape",
        "tab",
        "backspace",
        "up",
        "down",
        "left",
        "right"
    }

    if key not in allowed:
        return jsonify({
            "status": "error",
            "message": "Invalid key"
        }), 400

    pyautogui.press(
        key
    )

    return jsonify({
        "status": "success"
    })


@app.route(
    "/desktop/shortcut",
    methods=["POST"]
)
def desktop_shortcut():

    security = api_security()

    if security:
        return security

    action = (
        (request.get_json() or {})
        .get("action", "")
    )

    if action == "copy":
        pyautogui.hotkey(
            "ctrl",
            "c"
        )

    elif action == "paste":
        pyautogui.hotkey(
            "ctrl",
            "v"
        )

    elif action == "select_all":
        pyautogui.hotkey(
            "ctrl",
            "a"
        )

    elif action == "undo":
        pyautogui.hotkey(
            "ctrl",
            "z"
        )

    elif action == "alt_tab":
        pyautogui.hotkey(
            "alt",
            "tab"
        )

    elif action == "desktop":
        pyautogui.hotkey(
            "win",
            "d"
        )

    elif action == "task_manager":
        pyautogui.hotkey(
            "ctrl",
            "shift",
            "esc"
        )

    else:
        return jsonify({
            "status": "error",
            "message": "Invalid shortcut"
        }), 400

    return jsonify({
        "status": "success"
    })


# =========================================================
# LAPTOP STATUS
# =========================================================

@app.route(
    "/system/status",
    methods=["POST"]
)
def system_status():

    security = api_security()

    if security:
        return security

    if not PSUTIL_AVAILABLE:
        return jsonify({
            "status": "error",
            "message": "Install psutil: python -m pip install psutil"
        }), 500

    try:

        battery_info = psutil.sensors_battery()

        if battery_info is None:
            battery = {
                "available": False,
                "percent": 0,
                "charging": False
            }
        else:
            battery = {
                "available": True,
                "percent": round(battery_info.percent),
                "charging": bool(battery_info.power_plugged)
            }

        cpu_percent = round(
            psutil.cpu_percent(interval=0.15),
            1
        )

        memory = psutil.virtual_memory()

        ram = {
            "percent": round(memory.percent, 1),
            "used_gb": round(
                memory.used / (1024 ** 3),
                1
            ),
            "total_gb": round(
                memory.total / (1024 ** 3),
                1
            )
        }

        system_drive = (
            os.environ.get("SystemDrive", "C:")
            + os.sep
        )

        disk_usage = psutil.disk_usage(
            system_drive
        )

        disk = {
            "percent": round(disk_usage.percent, 1),
            "free_gb": round(
                disk_usage.free / (1024 ** 3),
                1
            )
        }

        hostname = socket.gethostname()

        # Determine the local IP used for outbound/local-network traffic
        # without sending application data.
        local_ip = "Unavailable"

        try:
            probe = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM
            )

            probe.connect(
                ("8.8.8.8", 80)
            )

            local_ip = probe.getsockname()[0]

            probe.close()

        except Exception:
            try:
                local_ip = socket.gethostbyname(
                    hostname
                )
            except Exception:
                pass

        uptime_seconds = max(
            0,
            int(time.time() - psutil.boot_time())
        )

        days, remainder = divmod(
            uptime_seconds,
            86400
        )

        hours, remainder = divmod(
            remainder,
            3600
        )

        minutes, _ = divmod(
            remainder,
            60
        )

        uptime_parts = []

        if days:
            uptime_parts.append(
                f"{days}d"
            )

        if hours or days:
            uptime_parts.append(
                f"{hours}h"
            )

        uptime_parts.append(
            f"{minutes}m"
        )

        return jsonify({
            "status": "success",
            "battery": battery,
            "cpu_percent": cpu_percent,
            "ram": ram,
            "disk": disk,
            "hostname": hostname,
            "ip": local_ip,
            "uptime": " ".join(uptime_parts)
        })

    except Exception as error:

        print(
            "System status:",
            error
        )

        return jsonify({
            "status": "error",
            "message": "Could not read laptop status"
        }), 500


# =========================================================
# ROCK FILES
# =========================================================

@app.route("/files/list", methods=["POST"])
def files_list():
    security = api_security()
    if security:
        return security

    data = request.get_json() or {}
    relative = data.get("path", "")
    folder = safe_share_path(relative)

    if folder is None or not os.path.isdir(folder):
        return jsonify({"status": "error", "message": "Invalid folder"}), 400

    try:
        items = []
        for name in sorted(os.listdir(folder), key=str.lower):
            full = os.path.join(folder, name)
            items.append({
                "name": name,
                "path": share_relative_path(full),
                "type": "folder" if os.path.isdir(full) else "file"
            })

        current = "" if os.path.abspath(folder) == os.path.abspath(ROCK_SHARE_FOLDER) else share_relative_path(folder)
        return jsonify({"status": "success", "path": current, "items": items})
    except Exception as error:
        print("Files list:", error)
        return jsonify({"status": "error", "message": "Could not list files"}), 500


@app.route("/files/upload", methods=["POST"])
def files_upload():
    security = api_security()
    if security:
        return security

    upload = request.files.get("file")
    relative = request.form.get("path", "")
    folder = safe_share_path(relative)

    if folder is None or not os.path.isdir(folder) or upload is None or not upload.filename:
        return jsonify({"status": "error", "message": "Invalid upload"}), 400

    if request.content_length and request.content_length > 100 * 1024 * 1024:
        return jsonify({"status": "error", "message": "File is larger than 100 MB"}), 413

    filename = os.path.basename(upload.filename.replace("\\", "/"))
    if filename in ("", ".", ".."):
        return jsonify({"status": "error", "message": "Invalid filename"}), 400

    destination = safe_share_path(os.path.join(relative, filename))
    if destination is None:
        return jsonify({"status": "error", "message": "Invalid filename"}), 400

    try:
        upload.save(destination)
        return jsonify({"status": "success", "message": "Uploaded to laptop"})
    except Exception as error:
        print("File upload:", error)
        return jsonify({"status": "error", "message": "Upload failed"}), 500


@app.route("/files/download", methods=["GET"])
def files_download():
    security = api_security()
    if security:
        return security

    full = safe_share_path(request.args.get("path", ""))
    if full is None or not os.path.isfile(full):
        return "File not found", 404

    return send_file(full, as_attachment=True, download_name=os.path.basename(full))


@app.route("/files/mkdir", methods=["POST"])
def files_mkdir():
    security = api_security()
    if security:
        return security

    data = request.get_json() or {}
    relative = data.get("path", "")
    name = str(data.get("name", "")).strip()

    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return jsonify({"status": "error", "message": "Invalid folder name"}), 400

    target = safe_share_path(os.path.join(relative, name))
    if target is None:
        return jsonify({"status": "error", "message": "Invalid folder"}), 400

    try:
        os.mkdir(target)
        return jsonify({"status": "success", "message": "Folder created"})
    except FileExistsError:
        return jsonify({"status": "error", "message": "That name already exists"}), 409
    except Exception as error:
        print("Create folder:", error)
        return jsonify({"status": "error", "message": "Could not create folder"}), 500


@app.route("/files/rename", methods=["POST"])
def files_rename():
    security = api_security()
    if security:
        return security

    data = request.get_json() or {}
    old_full = safe_share_path(data.get("path", ""))
    new_name = str(data.get("name", "")).strip()

    if not new_name or new_name in (".", "..") or "/" in new_name or "\\" in new_name:
        return jsonify({"status": "error", "message": "Invalid name"}), 400

    if old_full is None or not os.path.exists(old_full) or os.path.abspath(old_full) == os.path.abspath(ROCK_SHARE_FOLDER):
        return jsonify({"status": "error", "message": "Item not found"}), 404

    new_full = safe_share_path(os.path.join(share_relative_path(os.path.dirname(old_full)), new_name))
    if new_full is None:
        return jsonify({"status": "error", "message": "Invalid name"}), 400
    if os.path.exists(new_full):
        return jsonify({"status": "error", "message": "That name already exists"}), 409

    try:
        os.rename(old_full, new_full)
        return jsonify({"status": "success", "message": "Renamed"})
    except Exception as error:
        print("Rename:", error)
        return jsonify({"status": "error", "message": "Rename failed"}), 500


@app.route("/files/delete", methods=["POST"])
def files_delete():
    security = api_security()
    if security:
        return security

    full = safe_share_path((request.get_json() or {}).get("path", ""))

    if full is None or not os.path.exists(full) or os.path.abspath(full) == os.path.abspath(ROCK_SHARE_FOLDER):
        return jsonify({"status": "error", "message": "Item not found"}), 404

    try:
        if os.path.isdir(full):
            os.rmdir(full)
        else:
            os.remove(full)
        return jsonify({"status": "success", "message": "Deleted"})
    except OSError:
        return jsonify({"status": "error", "message": "Folder must be empty before deleting it"}), 409
    except Exception as error:
        print("Delete:", error)
        return jsonify({"status": "error", "message": "Delete failed"}), 500


# =========================================================
# ROCK CLIPBOARD
# =========================================================

@app.route(
    "/clipboard/set",
    methods=["POST"]
)
def clipboard_set():

    security = api_security()

    if security:
        return security

    data = request.get_json() or {}
    value = data.get("text", "")

    if not isinstance(value, str):
        return jsonify({
            "status": "error",
            "message": "Invalid clipboard text"
        }), 400

    # Keep the endpoint text-only and place a reasonable size limit.
    if len(value) > 200000:
        return jsonify({
            "status": "error",
            "message": "Clipboard text is too large"
        }), 413

    try:
        pyperclip.copy(value)

        return jsonify({
            "status": "success",
            "message": "Copied to laptop clipboard"
        })

    except Exception as error:
        print("Clipboard set:", error)

        return jsonify({
            "status": "error",
            "message": "Could not access laptop clipboard"
        }), 500


@app.route(
    "/clipboard/get",
    methods=["POST"]
)
def clipboard_get():

    security = api_security()

    if security:
        return security

    try:
        value = pyperclip.paste()

        return jsonify({
            "status": "success",
            "text": value,
            "message": "Laptop clipboard received"
        })

    except Exception as error:
        print("Clipboard get:", error)

        return jsonify({
            "status": "error",
            "message": "Could not access laptop clipboard"
        }), 500


# =========================================================
# YOUTUBE SEARCH
# =========================================================

@app.route(
    "/youtube/search",
    methods=["POST"]
)
def youtube_search():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}

    query = data.get(
        "query",
        ""
    ).strip()


    if not query:

        return jsonify({
            "status": "error",
            "message": "Enter a search"
        }), 400


    try:

        options = {

            "quiet": True,

            "no_warnings": True,

            "extract_flat": True,

            "skip_download": True

        }


        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(

                "ytsearch10:"
                + query,

                download=False

            )


        results = []


        for item in (
            info.get(
                "entries",
                []
            )
            or []
        ):

            if not item:

                continue


            video_id = item.get(
                "id"
            )


            if not video_id:

                continue


            results.append({

                "id":
                    video_id,

                "title":
                    item.get(
                        "title"
                    )
                    or
                    "Untitled",

                "channel":
                    item.get(
                        "channel"
                    )
                    or
                    item.get(
                        "uploader"
                    )
                    or
                    ""

            })


        return jsonify({

            "status":
                "success",

            "results":
                results

        })


    except Exception as error:

        print(
            "YouTube search:",
            error
        )


        return jsonify({

            "status":
                "error",

            "message":
                "YouTube search failed"

        }), 500


# =========================================================
# PLAY YOUTUBE VIDEO
# =========================================================

@app.route(
    "/youtube/play",
    methods=["POST"]
)
def youtube_play():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}

    video_id = data.get(
        "id",
        ""
    ).strip()


    # YouTube IDs use a limited character set.
    if not video_id:

        return jsonify({
            "status": "error",
            "message": "Invalid video"
        }), 400


    if not all(

        character.isalnum()
        or
        character in "-_"

        for character
        in video_id

    ):

        return jsonify({
            "status": "error",
            "message": "Invalid video ID"
        }), 400


    url = (
        "https://www.youtube.com/watch?v="
        + video_id
    )


    if not navigate_brave_url(
        url
    ):

        return jsonify({
            "status": "error",
            "message": "Brave not found"
        }), 500


    return jsonify({
        "status": "success",
        "message": "Opening video"
    })


# =========================================================
# YOUTUBE REMOTE
# =========================================================

@app.route(
    "/youtube/control",
    methods=["POST"]
)
def youtube_control():

    security = api_security()

    if security:

        return security


    data = request.get_json() or {}

    action = data.get(
        "action"
    )


    if not focus_brave():

        return jsonify({
            "status": "error",
            "message": "Brave not found"
        }), 404


    # YouTube-specific shortcuts.
    #
    # k = play/pause
    # j = backward 10 sec
    # l = forward 10 sec
    # m = mute
    # f = fullscreen
    # c = captions
    # t = theater
    # shift+n = next video
    # shift+p = previous video


    if action == "bring_front":

        # focus_brave() already restored and activated Brave.
        pass


    elif action == "play":

        pyautogui.press(
            "k"
        )


    elif action == "back10":

        pyautogui.press(
            "j"
        )


    elif action == "forward10":

        pyautogui.press(
            "l"
        )


    elif action == "mute":

        pyautogui.press(
            "m"
        )


    elif action == "fullscreen":

        pyautogui.press(
            "f"
        )


    elif action == "captions":

        pyautogui.press(
            "c"
        )


    elif action == "theater":

        pyautogui.press(
            "t"
        )


    elif action == "volume_up":

        pyautogui.press(
            "up"
        )


    elif action == "volume_down":

        pyautogui.press(
            "down"
        )


    elif action == "next":

        pyautogui.hotkey(
            "shift",
            "n"
        )


    elif action == "previous":

        pyautogui.hotkey(
            "shift",
            "p"
        )


    if action == "bring_front":

        # focus_brave() already restored and activated Brave.
        pass


    elif action == "close_tab":

        pyautogui.hotkey(
            "ctrl",
            "w"
        )


    else:

        return jsonify({
            "status": "error",
            "message": "Invalid YouTube action"
        }), 400


    return jsonify({
        "status": "success",
        "message": "Command sent"
    })


# =========================================================
# FIND CORRECT LAN IP
# =========================================================

def get_lan_ip():

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    try:
        # No actual data needs to be sent.
        # This lets Windows choose the active network adapter.
        sock.connect(("8.8.8.8", 80))

        ip = sock.getsockname()[0]

        return ip

    except Exception:
        return "127.0.0.1"

    finally:
        sock.close()


# =========================================================
# START GVA-LR
# =========================================================

if __name__ == "__main__":

    lan_ip = get_lan_ip()

    print()
    print("========================================")
    print("              ⚡ GVA-LR")
    print("========================================")
    print()
    print("💻 Laptop:")
    print("   http://127.0.0.1:5000")
    print()
    print("📱 PHONE - OPEN THIS:")
    print()
    print(f"   http://{lan_ip}:5000")
    print()
    print("🔐 GVA-LR authentication enabled")
    print()
    print("🎬 Videos :", VIDEO_FOLDER)
    print("📝 Notes  :", NOTES_FOLDER)
    print()
    print("⚠ Use HTTP, not HTTPS")
    print("⚠ Keep GVA-LR on your trusted local network")
    print()
    print("========================================")
    print()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )