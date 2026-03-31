import os
import shutil
from pathlib import Path

from streamlit import file_util
from streamlit.web import bootstrap

APP_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = str(APP_DIR / "app.py")
APP_FAVICON = APP_DIR / "favicon.png"


def _prepare_custom_static_dir() -> Path:
    base_static_dir = Path(file_util.get_static_dir())
    runtime_root = APP_DIR / ".runtime_static"
    custom_static_dir = runtime_root / "static"
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(base_static_dir, custom_static_dir, dirs_exist_ok=True)

    if APP_FAVICON.exists():
        shutil.copyfile(APP_FAVICON, custom_static_dir / "favicon.png")

    return custom_static_dir


CUSTOM_STATIC_DIR = _prepare_custom_static_dir()
file_util.get_static_dir = lambda: str(CUSTOM_STATIC_DIR)

flag_options = {
    "server_headless": True,
    "server_port": int(os.getenv("PORT", "8501")),
    "server_address": "0.0.0.0",
    "server_fileWatcherType": "none",
    "browser_gatherUsageStats": False,
}

bootstrap.run(MAIN_SCRIPT, False, [], flag_options)
