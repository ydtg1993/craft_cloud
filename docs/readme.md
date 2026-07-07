<p align="left">
    <span>
        <b>English</b>
    </span>
    <span> • </span>
    <a href="readme-CH.md">
        中文
    </a>
</p>

# CraftCloud v2.7.7 🌐 [craftcloud.cc.cd](https://craftcloud.cc.cd/)

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%2BQFluentWidgets-green)](https://doc.qt.io/qtforpython-6/)
[![Telegram API](https://img.shields.io/badge/Telegram-Telethon-0088cc)](https://telethon.dev/)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE.txt)

**CraftCloud** turns Telegram into unlimited cloud storage. It provides a cloud‑drive‑like desktop interface with file upload, download, online preview, directory management, and automatic local folder sync. The app minimizes to the system tray and runs background sync tasks without interrupting your workflow.

---

## Preview

<table>
  <tr>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/picture/preview1.png"/></td>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/picture/preview2.png"/></td>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/picture/preview3.png"/></td>
  </tr>
  <tr>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/picture/preview4.png"/></td>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/picture/preview5.png"/></td>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/picture/preview6.png"/></td>
  </tr>
</table>

### Tutorial

<table>
  <tr>
    <td align="center"><b>Login</b></td>
    <td align="center"><b>File Operations</b></td>
    <td align="center"><b>Auto Sync</b></td>
  </tr>
  <tr>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/tutorial/login_tutorial.gif"/></td>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/tutorial/operate_tutorial.gif"/></td>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/tutorial/sync_tutorial.gif"/></td>
  </tr>
</table>

---

<p align="center">
  <a href="https://github.com/ydtg1993/craft_cloud/releases" target="_blank">
    <img align="center" alt="download" src="https://nickemanarin.github.io/ScreenToGif-Website/wiki/download-now.png"/>
  </a>
</p>

---

> To obtain Telegram API credentials: visit [my.telegram.org](https://my.telegram.org/), create an application, and get your `api_id` and `api_hash`.

## Features

- 🔐 **Telegram Login**
  QR code login via API ID / API Hash. Session persistence, multi-account support, logout anytime.

- 🌐 **Multi-Language**
  Supports 6 languages: 中文, English, Français, Deutsch, Русский, 한국어. Switch at runtime in Settings.

- 📁 **File Management**
  List / Icon dual‑view, drag‑and‑drop move (cross‑directory), batch delete/rename/move, property inspection. Right‑click context menu for upload, download, new folder, etc.

- 👀 **File Preview**
  Online preview for images, audio (with seek bar), video, and text files. Files larger than 100 MB cannot be previewed.

- 📤 **Upload & Download**
  Batch upload files or folders with configurable retry (default 3). Real‑time progress display. All tasks run asynchronously in the background via a shared worker thread.

- 🔍 **Smart Search**
  Fuzzy filename search. For datasets < 10k files a simple SQL `LIKE` query is used; beyond that, Whoosh full‑text indexing with jieba Chinese word segmentation is enabled automatically.

- 📂 **Directory & Channel Binding**
  App directories auto‑bind to Telegram channels. Multi‑level subdirectories supported. If a channel becomes invalid, the app intelligently rebuilds the binding.

- 🔄 **Automatic Sync**
  Add local folders and schedule sync to a Telegram directory at minute / hour / day intervals. Sync runs only when the window is minimized to the tray; it pauses automatically when restored. During sync, local‑remote directory structure is kept consistent.

- 📊 **Upload Limits**
  Optional daily upload size / file count limits, counted in UTC+8 (Beijing time). Current usage vs. limit displayed in the bottom status bar of the home page. When disabled, limits show ∞.

- 🧩 **Task Queue**
  Persistent task history table showing upload / download progress and sync status. Records survive app restarts.

- 🖥️ **System Tray**
  Close to tray with sync auto‑resume. Right‑click menu: "Open Cloud" / "Exit". Double‑click restores the window.

- 🎨 **Modern Interface**
  Built with QFluentWidgets, supporting dark / light themes. Auto‑sync folders are marked with a special icon in the directory tree.

- 📝 **Logging System**
  Structured logging via loguru — console + daily rotating files, kept for 7 days. Telethon session noise is filtered.

---

## Architecture

```
main.py          →  Entry point, config init, login / main window flow
core/            →  Infrastructure (config, DB engine, worker thread, task routing)
model/           →  Data layer (SQLAlchemy ORM models + repositories)
services/        →  Business logic (upload, download, search, sync, file CRUD)
view/            →  UI layer (PySide6 + QFluentWidgets, signals‑driven)
```

The app uses a **single shared Telegram client** (`TgWorkerThread`) — one thread, one event loop, one `Telethon` client. All operations (upload / download / rename / delete / preview) queue through it via `asyncio.run_coroutine_threadsafe()`, with per‑operation‑type `asyncio.Semaphore` concurrency control.

## Tech Stack

| Category | Library |
|----------|---------|
| GUI | PySide6 ≥6.5, PySide6-Fluent-Widgets ≥1.11 |
| Telegram | Telethon ≥1.36, cryptg ≥0.4 |
| Database | SQLAlchemy ≥2.0 (ORM), SQLite 3 (WAL mode) |
| Config | Pydantic ≥2.0, PyYAML ≥6.0 |
| Logging | loguru ≥0.7 |
| Search | Whoosh ≥2.7, jieba ≥0.42 |
| Caching | diskcache ≥5.0 |
| Imaging | Pillow ≥9.0, qrcode ≥7.4 |
| Misc | numpy <2 |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

---

## License

This project is licensed under the MIT License. See [LICENSE.txt](LICENSE.txt) for details.

When using Telegram to store files, please comply with Telegram's Terms of Service and applicable laws. The developer assumes no responsibility for data loss or account risks.

---

## Contributing

Issues and Pull Requests are welcome.

**Thank you for using CraftCloud!**
