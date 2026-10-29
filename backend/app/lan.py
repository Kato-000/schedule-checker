"""スマホ用の入口（HTTPS・自宅LANのみ）。設定画面からの操作で、起動したまま開始・停止できる。"""

from __future__ import annotations

import logging
import socket
import threading

import uvicorn

from . import config, db

log = logging.getLogger(__name__)


def lan_addresses() -> list[str]:
    """このPCの自宅LANでのIPアドレス（スマホから開くURLに使う）。"""
    ips: list[str] = []
    try:
        # 送信はしない（経路を調べるだけ）
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.0.1", 9))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    from .security import is_lan
    return [ip for ip in ips if is_lan(ip)]


class LanServer:
    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server and self._server.started)

    def cert_ok(self) -> bool:
        return config.CERT_FILE.exists() and config.KEY_FILE.exists()

    def start(self, app) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            if not self.cert_ok():
                self.error = "証明書がありません。make_lan_cert.ps1 で作成してください。"
                return False
            cfg = uvicorn.Config(app, host="0.0.0.0", port=config.LAN_PORT, lifespan="off",
                                 ssl_certfile=str(config.CERT_FILE), ssl_keyfile=str(config.KEY_FILE),
                                 log_level="info", proxy_headers=False)
            self._server = uvicorn.Server(cfg)
            self.error = None

            def run():
                try:
                    self._server.run()
                except (OSError, SystemExit) as e:  # ポートが使用中など
                    self.error = f"LAN用の入口を開けませんでした: {e}"
                    log.error(self.error)

            self._thread = threading.Thread(target=run, name="lan-server", daemon=True)
            self._thread.start()
            log.info("LAN用の入口を開きます: https://<このPC>:%d", config.LAN_PORT)
            return True

    def stop(self) -> None:
        with self._lock:
            if self._server:
                self._server.should_exit = True
            if self._thread:
                self._thread.join(timeout=5)
            self._server = self._thread = None

    def status(self) -> dict:
        s = db.get_settings()
        return {
            "enabled": s.get("lan_enabled") == "1",
            "pin_set": bool(s.get("pin_hash")),
            "cert_ok": self.cert_ok(),
            "running": self.running,
            "error": self.error,
            "port": config.LAN_PORT,
            "urls": [f"https://{ip}:{config.LAN_PORT}" for ip in lan_addresses()],
        }


server = LanServer()
