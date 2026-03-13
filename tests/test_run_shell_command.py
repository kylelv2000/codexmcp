import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from codexmcp.server import run_shell_command


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_pid(path: Path, timeout_seconds: float = 2.0) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            if raw:
                return int(raw)
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for pid file: {path}")


def _wait_for_exit(pid: int, timeout_seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(0.05)
    return not _pid_exists(pid)


class RunShellCommandCleanupTests(unittest.TestCase):
    def test_generator_close_terminates_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / "pid.txt"
            child_pid_file = Path(temp_dir) / "child_pid.txt"
            command = [
                "bash",
                "-lc",
                (
                    f"echo $$ > '{pid_file}'; "
                    f"sleep 30 & echo $! > '{child_pid_file}'; "
                    "echo ready; "
                    "wait"
                ),
            ]

            with mock.patch("codexmcp.server.shutil.which", return_value=None):
                stream = run_shell_command(command)
                first_line = next(stream)
                self.assertEqual(first_line, "ready")
                pid = _wait_for_pid(pid_file)
                child_pid = _wait_for_pid(child_pid_file)
                stream.close()

            self.assertTrue(
                _wait_for_exit(pid),
                msg=f"Child process {pid} should be terminated when stream is closed early.",
            )
            self.assertTrue(
                _wait_for_exit(child_pid),
                msg=f"Descendant process {child_pid} should be terminated when stream is closed early.",
            )

    def test_turn_completed_stops_long_running_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / "pid.txt"
            command = [
                "bash",
                "-lc",
                (
                    f"echo $$ > '{pid_file}'; "
                    "printf '{\"type\":\"turn.completed\"}\\n'; "
                    "sleep 30; "
                    "echo should_not_happen"
                ),
            ]

            with mock.patch("codexmcp.server.shutil.which", return_value=None):
                start = time.monotonic()
                lines = list(run_shell_command(command))
                duration = time.monotonic() - start

            pid = _wait_for_pid(pid_file)
            self.assertLess(duration, 8.0, "run_shell_command should stop quickly after turn completion.")
            self.assertIn('{"type":"turn.completed"}', lines)
            self.assertNotIn("should_not_happen", lines)
            self.assertTrue(
                _wait_for_exit(pid),
                msg=f"Child process {pid} should be terminated after turn completion.",
            )


if __name__ == "__main__":
    unittest.main()
