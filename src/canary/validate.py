import os
import subprocess
import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    valid: bool
    output: str
    num_correct: int
    num_incorrect: int
    num_failed: int
    num_errors: int


def _parse_result(text: str) -> ValidationResult:
    # Parse the result.
    pattern = re.compile(
        r"(?P<correct>\d+) correct transformations.*?"
        r"(?P<incorrect>\d+) incorrect transformations.*?"
        r"(?P<failed>\d+) failed-to-prove transformations.*?"
        r"(?P<errors>\d+) Alive2 errors",
        re.DOTALL,
    )

    m = pattern.search(text)
    correct = int(m["correct"])
    incorrect = int(m["incorrect"])
    failed = int(m["failed"])
    errors = int(m["errors"])

    return correct, incorrect, failed, errors


def check_semantics(
    tv: str,
    src: str,
    tgt: str,
    cc: str = "clang",
    cflags: list[str] = [],
) -> ValidationResult:

    # Set up a pipe for command substitution
    tgt_read_fd, tgt_write_fd = os.pipe()
    src_read_fd, src_write_fd = os.pipe()

    try:
        compile_src = subprocess.Popen(
            [
                cc,
                "-emit-llvm",
                "-c",
                "-x",
                "c",
                "-",
                "-o",
                f"/dev/fd/{src_write_fd}",
            ]
            + cflags,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(src_write_fd,),
        )
        compile_tgt = subprocess.Popen(
            [
                cc,
                "-emit-llvm",
                "-c",
                "-x",
                "c",
                "-",
                "-o",
                f"/dev/fd/{tgt_write_fd}",
            ]
            + cflags,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(tgt_write_fd,),
        )
        alive = subprocess.Popen(
            [
                tv,
                "--src-unroll=10",
                "--tgt-unroll=10",
                f"/dev/fd/{src_read_fd}",
                f"/dev/fd/{tgt_read_fd}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(src_read_fd, tgt_read_fd),
        )

        # Close the pipe so the commands can use it.
        os.close(src_read_fd)
        os.close(src_write_fd)
        os.close(tgt_read_fd)
        os.close(tgt_write_fd)
        # Compile source
        compile_src.stdin.write(src.encode())
        compile_src.stdin.close()
        src_exitcode = compile_src.wait(timeout=600)
        if src_exitcode > 0:
            src_stdout, src_stderr = compile_src.communicate(timeout=600)
            print(
                f"Failed to compile:\n{compile_src.args}\n\n{src}\n\nstderr:\n{src_stderr}"
            )
        # Compile target
        compile_tgt.stdin.write(tgt.encode())
        compile_tgt.stdin.close()
        tgt_exitcode = compile_tgt.wait(timeout=600)
        if tgt_exitcode > 0:
            tgt_stdout, tgt_stderr = compile_tgt.communicate(timeout=600)
            print(
                f"Failed to compile:\n{compile_tgt.args}\n\n{tgt}\n\nstderr:\n{tgt_stderr}"
            )

        # Run alive
        stdout, stderr = alive.communicate(timeout=600)

        correct, incorrect, failed, errors = _parse_result(stdout.decode())

        valid = incorrect == 0 and failed == 0 and errors == 0

        return ValidationResult(
            valid,
            stdout.decode(),
            correct,
            incorrect,
            failed,
            errors,
        )

    except Exception:
        os.close(src_read_fd)
        os.close(src_write_fd)
        os.close(tgt_read_fd)
        os.close(tgt_write_fd)
        raise
