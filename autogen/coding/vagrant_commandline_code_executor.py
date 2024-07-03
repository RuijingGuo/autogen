from __future__ import annotations

import atexit
import logging
import sys
import uuid
from hashlib import md5
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Dict, List, Optional, Type, Union

import vagrant
from fabric.api import env, execute, task, run, settings, put

from ..code_utils import TIMEOUT_MSG, _cmd
from .base import CodeBlock, CodeExecutor, CodeExtractor, CommandLineCodeResult
from .markdown_code_extractor import MarkdownCodeExtractor
from .utils import _get_file_name_from_content, silence_pip

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

__all__ = ("VagrantCommandLineCodeExecutor",)

class VagrantCommandLineCodeExecutor(CodeExecutor):
    DEFAULT_EXECUTION_POLICY: ClassVar[Dict[str, bool]] = {
        "bash": True,
        "shell": True,
        "sh": True,
        "pwsh": True,
        "powershell": False,
        "ps1": True,
        "python": True,
        "javascript": True,
        "html": False,
        "css": False,
    }
    LANGUAGE_ALIASES: ClassVar[Dict[str, str]] = {"py": "python", "js": "javascript"}

    def __init__(
        self,
        timeout: int = 60,
        work_dir: Union[Path, str] = Path("."),
        auto_remove: bool = True,
        execution_policies: Optional[Dict[str, bool]] = None,
    ):
        """(Experimental) A code executor class that executes code through
        a command line environment in a vagrant.

        The executor first saves each code block in a file in the working
        directory, and then executes the code file in the vagrant.
        The executor executes the code blocks in the order they are received.
        Currently, the executor only supports Python and shell scripts.
        For Python code, use the language "python" for the code block.
        For shell scripts, use the language "bash", "shell", or "sh" for the code
        block.

        Args:
            timeout (int, optional): The timeout for code execution. Defaults to 60.
            work_dir (Union[Path, str], optional): The working directory for the code
                execution. Defaults to Path(".").
            auto_remove (bool, optional): If true, will automatically remove the
                vagrant when it is stopped. Defaults to True.

        Raises:
            ValueError: On argument error, or if the vagrant fails to start.
        """
        if timeout < 1:
            raise ValueError("Timeout must be greater than or equal to 1.")

        if isinstance(work_dir, str):
            work_dir = Path(work_dir)
        work_dir.mkdir(exist_ok=True)

        self._v = vagrant.Vagrant()
        self._v.up()

        def cleanup() -> None:
            self._v.destroy()
            atexit.unregister(cleanup)

        self._cleanup = cleanup
        self._timeout = timeout
        self._work_dir: Path = work_dir
        self.execution_policies = self.DEFAULT_EXECUTION_POLICY.copy()
        if execution_policies is not None:
            self.execution_policies.update(execution_policies)

    @property
    def timeout(self) -> int:
        """Get the timeout for code execution."""
        return self._timeout

    @property
    def work_dir(self) -> Path:
        """Get the working directory for code execution."""
        return self._work_dir

    @property
    def code_extractor(self) -> CodeExtractor:
        """Get a code extractor instance for code blocks."""
        return MarkdownCodeExtractor()

    def execute_code_blocks(self, code_blocks: List[CodeBlock]) -> CommandLineCodeResult:
        """ Execute the code blocks and return the result.

        Args:
            code_blocks (List[CodeBlock]): List of code blocks to execute.

        Returns:
            CommandlineCodeResult: The result of the code execution."""

        if len(code_blocks) == 0:
            raise ValueError("No code blocks to execute.")

        outputs = []
        files = []
        last_exit_code = 0
        for code_block in code_blocks:
            lang = self.LANGUAGE_ALIASES.get(code_block.language.lower(), code_block.language.lower())
            if lang not in self.DEFAULT_EXECUTION_POLICY:
                outputs.append(f"Unsupported language {lang}\n")
                last_exit_code = 1
                break

            execute_code = self.execution_policies.get(lang, False)
            code = silence_pip(code_block.code, lang)

            # Check if there is a filename comment
            try:
                filename = _get_file_name_from_content(code, self._work_dir)
            except ValueError:
                outputs.append("Filename is not in the workspace")
                last_exit_code = 1
                break

            if not filename:
                filename = f"tmp_code_{md5(code.encode()).hexdigest()}.{lang}"

            code_path = self._work_dir / filename
            with code_path.open("w", encoding="utf-8") as fout:
                fout.write(code)
            files.append(code_path)

            if not execute_code:
                outputs.append(f"Code saved to {str(code_path)}\n")
                continue

            command = ["timeout", str(self._timeout), _cmd(lang), filename]
            with settings(host_string=self._v.user_hostname_port(),
                key_filename=self._v.keyfile(),
                disable_known_hosts=True,
                warn_only=True
            ):
                put(code_path, '~')
                output = run(' '.join(command))
                outputs.append(output[-200:])
                last_exit_code = output.return_code


        code_file = str(files[0]) if files else None
        return CommandLineCodeResult(exit_code=last_exit_code, output="".join(outputs), code_file=code_file)

    def restart(self) -> None:
        """Restart the code executor."""

    def stop(self) -> None:
        """Stop the code executor."""
        self._cleanup()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        self.stop()
