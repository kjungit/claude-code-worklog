"""Debug logging for hook failures (docs 17.3).

Exceptions in a hook must never surface to the user or change the exit
code -- they go here instead, silently. Rotation to the most recent
1000 lines is added alongside the /worklog-debug command.
"""

import os
import time

from paths import debug_log_path


def log(message):
    try:
        path = debug_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (timestamp, message))
    except OSError:
        pass  # logging must never be the reason a hook fails
