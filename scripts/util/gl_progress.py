# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""vvp launcher that prefixes wall-clock and prints avg/ETA on `frame N/M` lines.

Runs vvp through a PTY so its stdout stays line-buffered.
Usage: gl_progress.py vvp sim.vvp +frames=300 ...
"""

import os
import pty
import re
import select
import sys
import time

FRAME_RE = re.compile(r"frame (\d+) / (\d+)")


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: gl_progress.py <cmd> [args...]\n")
        return 2

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(sys.argv[1], sys.argv[1:])

    t0 = time.time()
    buf = b""
    out = sys.stdout
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 1.0)
            if r:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace")
                    elapsed = time.time() - t0
                    out.write(f"[+{elapsed:6.1f}s] {text}\n")
                    m = FRAME_RE.search(text)
                    if m:
                        n, total = int(m.group(1)), int(m.group(2))
                        # +1 to account for pre-vsync warmup (~1 frame of work).
                        avg = elapsed / (n + 1)
                        eta = avg * (total - n)
                        out.write(
                            f"[+{elapsed:6.1f}s]   ── avg {avg:5.1f}s/frame, "
                            f"ETA {eta/60:5.1f} min ({total - n} left)\n"
                        )
                    out.flush()
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    sys.exit(main())
