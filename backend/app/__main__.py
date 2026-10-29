"""python -m app で起動する（コンソールなしの pythonw でも動く）。"""

import sys

import uvicorn

from . import config

if __name__ == "__main__":
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        # pythonw で起動したときは画面がないので、ログをファイルに書く
        log = open(config.DATA_DIR / "backend.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="info")
