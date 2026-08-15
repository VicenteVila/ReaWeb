from tools.base import Tool, ToolRegistry
from tools.file_io import ReadFile, WriteFile, ListFiles, EditFile
from tools.code_exec import PythonExec, BashExec

registry = ToolRegistry(
    [
        ReadFile(),
        WriteFile(),
        ListFiles(),
        EditFile(),
        PythonExec(),
        BashExec(),
    ]
)