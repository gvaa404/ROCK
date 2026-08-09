# ROCK — Laptop Remote Controller

A local Flask-based remote-control dashboard for controlling a Windows laptop from another device on the same network.

## Features

- 🔐 Password-protected web dashboard
- 🖱️ Desktop mouse and keyboard remote
- 📸 Temporary desktop screenshots
- 🎬 VLC controls
- 🌐 Brave browser controls
- 📺 YouTube search and media controls
- 📋 Clipboard transfer
- 📁 Restricted `RockShare` file exchange
- 📝 Notes
- 📊 Laptop status
- 🔆 Brightness and volume controls
- 🚀 Safe allow-listed application launcher

## Public-repository safety

This repository is designed so personal Windows paths and secrets are not committed.

The application reads `GVA_LR_PASSWORD` and `GVA_LR_SECRET_KEY` from environment variables / `.env`. User folders and optional executable locations can also be configured through environment variables.

**Never commit `.env`.** Use `.env.example` as the template.

## Setup

### 1. Clone

```bash
git clone <your-repository-url>
cd <your-repository-folder>
```

### 2. Create a virtual environment

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Git Bash:

```bash
python -m venv .venv
source .venv/Scripts/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure secrets

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Set a strong password and a long random Flask secret key.

Example:

```env
GVA_LR_PASSWORD=your-own-strong-password
GVA_LR_SECRET_KEY=your-own-long-random-secret
```

### 5. Optional VLC / Brave configuration

If VLC or Brave is not available through your system `PATH`, set the executable path in `.env`.

You can also customize:

- `ROCK_VIDEO_FOLDER`
- `ROCK_NOTES_FOLDER`
- `ROCK_PROJECT_FOLDER`
- `ROCK_VLC_PATH`
- `ROCK_BRAVE_PATH`

Defaults are generic user folders and do not contain the developer's personal path.

### 6. Run

```bash
python rock.py
```

Then open the displayed local/network address from another device on the same network.

## Security notes

- Keep the application on a trusted network.
- Use a strong password.
- Do not expose the Flask development server directly to the public internet.
- Do not commit `.env`, passwords, tokens, screenshots, personal notes, or local media.
- The file-sharing feature is restricted to the application's `RockShare` directory.
- Application launching uses a fixed allow-list rather than accepting arbitrary executable paths.

## Project structure

```text
rock/
├── rock.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## License

Add the license you want to use before publishing.
