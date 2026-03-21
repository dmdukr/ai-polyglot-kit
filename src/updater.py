"""Auto-updater — checks GitHub releases and downloads new versions.

Flow:
  1. On startup (background thread): check latest GitHub release
  2. If newer version available: notify user via tray
  3. On user confirm: download installer, run it, exit current process
"""

import logging
import os
import subprocess
import tempfile
import threading
import time
from packaging.version import Version

import httpx

from .config import APP_VERSION, GITHUB_REPO, APP_DIR

logger = logging.getLogger(__name__)

CHECK_INTERVAL_S = 4 * 3600  # check every 4 hours
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class Updater:
    """Checks for updates and downloads new releases."""

    def __init__(self, on_update_available=None):
        """
        Args:
            on_update_available: callback(version: str, download_url: str)
                Called when a new version is found.
        """
        self._on_update_available = on_update_available
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        """Start background update checker."""
        self._thread = threading.Thread(
            target=self._check_loop, name="Updater", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop background checker."""
        self._stop.set()

    def check_now(self) -> dict | None:
        """Check for update immediately. Returns release info or None."""
        return self._check_release()

    def download_and_install(self, download_url: str, filename: str = "") -> bool:
        """Download installer and run it.

        Args:
            download_url: URL to the .exe installer asset.
            filename: Suggested filename.

        Returns:
            True if download+launch succeeded.
        """
        try:
            if not filename:
                filename = download_url.split("/")[-1]

            download_dir = APP_DIR / "updates"
            download_dir.mkdir(parents=True, exist_ok=True)
            installer_path = download_dir / filename

            # Remove old download if exists (avoids Permission denied)
            if installer_path.exists():
                try:
                    installer_path.unlink()
                    logger.info("Removed old update file: %s", installer_path)
                except OSError:
                    # File locked — use unique name
                    installer_path = download_dir / f"GroqDictation_{int(time.time())}.exe"
                    logger.info("Old file locked, using: %s", installer_path)

            logger.info("Downloading update: %s", download_url)

            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                with client.stream("GET", download_url) as resp:
                    resp.raise_for_status()
                    downloaded = 0

                    with open(installer_path, "wb") as f:
                        for chunk in resp.iter_bytes(8192):
                            f.write(chunk)
                            downloaded += len(chunk)

                    logger.info(
                        "Downloaded %d bytes to %s", downloaded, installer_path
                    )

            # Launch installer (handles killing old process, replacing files, restart)
            logger.info("Launching installer: %s", installer_path)
            subprocess.Popen(
                [str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )

            logger.info("Exiting for update...")
            os._exit(0)

        except Exception as e:
            logger.error("Update download failed: %s", e)
            return False

    # ── Internal ─────────────────────────────────────────────────────

    def _check_loop(self) -> None:
        """Background loop: check on startup + every CHECK_INTERVAL_S."""
        # Wait a bit after startup
        time.sleep(30)

        while not self._stop.is_set():
            try:
                self._check_release()
            except Exception as e:
                logger.debug("Update check error: %s", e)

            self._stop.wait(CHECK_INTERVAL_S)

    def _check_release(self) -> dict | None:
        """Query GitHub API for latest release.

        Returns dict with 'version', 'url', 'filename' if update available.
        """
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    GITHUB_API,
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code == 404:
                    logger.debug("No releases found on GitHub")
                    return None
                resp.raise_for_status()
                data = resp.json()

            tag = data.get("tag_name", "").lstrip("v")
            if not tag:
                return None

            try:
                remote_ver = Version(tag)
                local_ver = Version(APP_VERSION)
            except Exception:
                logger.debug("Cannot parse version: remote=%s local=%s", tag, APP_VERSION)
                return None

            if remote_ver <= local_ver:
                logger.debug("Up to date (local=%s, remote=%s)", APP_VERSION, tag)
                return None

            # Find setup installer asset (preferred for onedir mode)
            exe_url = ""
            exe_name = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.endswith(".exe") and "setup" in name.lower():
                    exe_url = asset.get("browser_download_url", "")
                    exe_name = name
                    break

            if not exe_url:
                # Fallback: any .exe
                for asset in data.get("assets", []):
                    name = asset.get("name", "")
                    if name.endswith(".exe"):
                        exe_url = asset.get("browser_download_url", "")
                        exe_name = name
                        break

            if not exe_url:
                logger.info("New version %s available but no exe asset found", tag)
                return None

            installer_url = exe_url
            installer_name = exe_name

            logger.info("Update available: %s → %s (%s)", APP_VERSION, tag, installer_name)

            result = {
                "version": tag,
                "url": installer_url,
                "filename": installer_name,
                "notes": data.get("body", "")[:200],
            }

            if self._on_update_available:
                self._on_update_available(tag, installer_url)

            return result

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.debug("GitHub rate limited, will retry later")
            else:
                logger.debug("GitHub API error: %s", e)
            return None
        except Exception as e:
            logger.debug("Update check failed: %s", e)
            return None
