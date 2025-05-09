import os
import sys
import json
import subprocess
import platform
import pathlib
import shutil
from typing import Dict, Any, Optional, List, TypedDict
import requests

# --- Tool Definitions (JSON Schema for OpenAI API) ---
EXECUTE_PYTHON_CODE_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "execute_python_code",
        "description": ("Executes a given snippet of Python code in a separate process and returns its stdout and stderr. "
            "WARNING: This is highly dangerous and executes with the script's permissions. Requires careful user approval."),
        "parameters": {"type": "object", "properties": {
                "code": {"type": "string", "description": "The Python code snippet to execute.",},
                "timeout_seconds": {"type": "integer", "description": "Optional timeout in seconds for the execution.","default": 30,},},
            "required": ["code"]}}}
EXECUTE_SHELL_COMMAND_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "execute_shell_command",
        "description": "Execute a shell command and return its stdout, stderr, and exit code. Use OS-specific commands (cmd.exe on Windows, sh/bash on Linux/macOS). Requires user approval.",
        "parameters": { "type": "object", "properties": {
                "command": {"type": "string", "description": "The shell command string to execute."},
                "working_directory": {"type": "string", "description": "Optional directory path to execute the command in.", "nullable": True},
                "timeout_seconds": {"type": "integer", "description": "Optional timeout in seconds.", "default": 60}},
            "required": ["command"]}}}
READ_FILE_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "read_file",
        "description": "Reads the entire content of a specified file.",
        "parameters": { "type": "object", "properties": {
                "path": {"type": "string", "description": "The relative or absolute path to the file to read."}},
            "required": ["path"]}}}
WRITE_FILE_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "write_file",
        "description": "Writes content to a specified file. Creates directories if needed. Requires user approval.",
        "parameters": { "type": "object", "properties": {
                "path": {"type": "string", "description": "The relative or absolute path to the file to write."},
                "content": {"type": "string", "description": "The content to write to the file."},
                "overwrite": {"type": "boolean", "description": "Whether to overwrite the file if it exists.", "default": False}},
            "required": ["path", "content"]}}}
COPY_FILE_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "copy_file",
        "description": "Copies a source file to a destination path. Creates destination directories if needed. Requires user approval.",
        "parameters": { "type": "object", "properties": {
                "source_path": {"type": "string", "description": "The relative or absolute path of the file to copy."},
                "destination_path": {"type": "string", "description": "The relative or absolute path where the file should be copied."},
                "overwrite": {"type": "boolean", "description": "Whether to overwrite the destination file if it already exists.", "default": False}},
            "required": ["source_path", "destination_path"]}}}
LIST_DIRECTORY_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "list_directory",
        "description": "Lists the files and subdirectories within a specified directory.",
        "parameters": { "type": "object", "properties": {
                "path": {"type": "string", "description": "The relative or absolute path to the directory.", "default": "."},
                "recursive": {"type": "boolean", "description": "Whether to list contents recursively (use with caution).", "default": False}},
            "required": []}}}
CREATE_DIRECTORY_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "create_directory",
        "description": "Creates a new directory, including any necessary parent directories. Requires user approval.",
        "parameters": { "type": "object", "properties": {
                "path": {"type": "string", "description": "The relative or absolute directory path to create."}},
            "required": ["path"]}}}
FETCH_WEB_PAGE_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "fetch_web_page",
        "description": "Fetches the text content of a given URL. Requires user approval.",
        "parameters": { "type": "object", "properties": {
                "url": {"type": "string", "description": "The URL to fetch (must include http:// or https://)."},
                "timeout_seconds": {"type": "integer", "description": "Optional timeout in seconds.", "default": 10}},
            "required": ["url"]}}}
ASK_USER_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": "ask_user",
        "description": "Asks the human user a question and returns their response.",
        "parameters": { "type": "object", "properties": {
                "question": {"type": "string", "description": "The question to ask the user."}},
            "required": ["question"]}}}

TOOLS_LIST = [
    EXECUTE_PYTHON_CODE_TOOL_SCHEMA, EXECUTE_SHELL_COMMAND_TOOL_SCHEMA, READ_FILE_TOOL_SCHEMA, WRITE_FILE_TOOL_SCHEMA, COPY_FILE_TOOL_SCHEMA,
    LIST_DIRECTORY_TOOL_SCHEMA, CREATE_DIRECTORY_TOOL_SCHEMA, FETCH_WEB_PAGE_TOOL_SCHEMA, ASK_USER_TOOL_SCHEMA,
]

# --- Tool Implementation Functions ---
def execute_shell_command(command: str, working_directory: Optional[str] = None, timeout_seconds: int = 60) -> Dict[str, Any]:
    """Executes a shell command."""
    result = {"stdout": "", "stderr": "", "exit_code": None, "error": None}
    effective_cwd = working_directory or os.getcwd()
    print(f"  (Executing in: {effective_cwd})") # Context for user
    if not pathlib.Path(effective_cwd).is_dir():
        result["error"] = f"Working directory not found: {effective_cwd}"
        result["exit_code"] = -2 # Consistent error code
        return result
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            encoding='utf-8', errors='replace', cwd=effective_cwd,
            timeout=timeout_seconds, check=False, # Don't raise exception on non-zero exit. Smart.
        )
        result.update({"stdout": proc.stdout.strip(), "stderr": proc.stderr.strip(), "exit_code": proc.returncode})
    except subprocess.TimeoutExpired:
        result.update({"error": f"Timeout ({timeout_seconds}s)", "exit_code": -1})
    except FileNotFoundError: # This usually means the command itself isn't found, numpty!
        cmd_name = command.split()[0] if command else '<empty command>'
        result.update({"error": f"Command or executable not found: '{cmd_name}'", "exit_code": -2}) # Clarified message.
    except Exception as e:
        result.update({"error": f"Execution failed: {e}", "exit_code": -3})
        if not result["stderr"]: result["stderr"] = str(e) # Capture exception string if no stderr
    return result

def read_file(path: str) -> Dict[str, Any]:
    """Reads the content of a file."""
    try:
        p = pathlib.Path(path)
        if not p.is_file(): raise FileNotFoundError(f"Not a file: {path}")
        content = p.read_text(encoding='utf-8', errors='replace')
        return {"content": content, "error": None}
    except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError, OSError) as e: # Added IsADirectoryError for completeness
        return {"content": None, "error": f"Read failed: {e}"}
    except Exception as e:
        return {"content": None, "error": f"Unexpected read error: {e}"}

def write_file(path: str, content: str, overwrite: bool = False) -> Dict[str, Any]:
    """Writes content to a file."""
    try:
        p = pathlib.Path(path)
        if p.exists() and p.is_dir(): raise IsADirectoryError(f"Path is a directory: {path}")
        if p.exists() and not overwrite: raise FileExistsError(f"File exists, overwrite=False: {path}")
        p.parent.mkdir(parents=True, exist_ok=True) # Ensure parent dir exists. Essential.
        p.write_text(content, encoding='utf-8')
        return {"success": True, "error": None}
    except (FileExistsError, IsADirectoryError, PermissionError, OSError) as e:
        return {"success": False, "error": f"Write failed: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected write error: {e}"}

def copy_file(source_path: str, destination_path: str, overwrite: bool = False) -> Dict[str, Any]:
    """Copies a file from source to destination."""
    try:
        src = pathlib.Path(source_path)
        dest = pathlib.Path(destination_path)

        if not src.is_file(): raise FileNotFoundError(f"Source not found or not a file: {source_path}")
        if dest.exists():
            if dest.is_dir(): raise IsADirectoryError(f"Destination is a directory: {destination_path}")
            if not overwrite: raise FileExistsError(f"Destination exists, overwrite=False: {destination_path}")
            if not dest.is_file(): raise ValueError(f"Cannot overwrite non-file destination: {destination_path}")
        dest.parent.mkdir(parents=True, exist_ok=True) # Ensure parent dir exists
        shutil.copy2(src, dest) # copy2 preserves metadata. Good touch.
        return {"success": True, "error": None}
    except (FileNotFoundError, FileExistsError, IsADirectoryError, PermissionError, shutil.Error, ValueError, OSError) as e:
        return {"success": False, "error": f"Copy failed: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected copy error: {e}"}

def list_directory(path: str = ".", recursive: bool = False) -> Dict[str, Any]:
    """Lists directory contents."""
    try:
        p = pathlib.Path(path)
        if not p.is_dir(): raise FileNotFoundError(f"Not a directory: {path}")
        entries = []
        if recursive:
            for item in sorted(p.rglob('*')): # Sort directly here
                rel_path = item.relative_to(p)
                entry_str = f"{rel_path}{os.sep}" if item.is_dir() else str(rel_path)
                entries.append(entry_str)
        else:
             for item in sorted(p.iterdir()):
                  entries.append(f"{item.name}{os.sep}" if item.is_dir() else item.name)
        return {"entries": entries, "error": None}
    except (FileNotFoundError, PermissionError, OSError) as e:
        return {"entries": None, "error": f"List failed: {e}"}
    except Exception as e:
        return {"entries": None, "error": f"Unexpected list error: {e}"}

def create_directory(path: str) -> Dict[str, Any]:
    """Creates a directory."""
    try:
        p = pathlib.Path(path)
        if p.exists() and not p.is_dir():
            raise FileExistsError(f"Path exists but is a file: {path}")
        p.mkdir(parents=True, exist_ok=True) # exist_ok=True is crucial.
        if not p.is_dir(): raise OSError(f"Failed to create or confirm directory: {path}")
        return {"success": True, "error": None}
    except (FileExistsError, PermissionError, OSError) as e:
        return {"success": False, "error": f"Create dir failed: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected create dir error: {e}"}

def fetch_web_page(url: str, timeout_seconds: int = 10) -> Dict[str, Any]:
    """Fetches the text content of a web page."""
    if requests is None: return {"content": None, "status_code": None, "error": "'requests' library not installed."}
    if not url.startswith(('http://', 'https://')): return {"content": None, "status_code": None, "error": "URL must start with http:// or https://"}
    result = {"content": None, "status_code": None, "error": None}
    try:
        response = requests.get(url, timeout=timeout_seconds, headers={'User-Agent': 'PythonAgent/1.0'})
        result["status_code"] = response.status_code
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx). YES!
        response.encoding = response.apparent_encoding or 'utf-8'
        result["content"] = response.text
    except requests.exceptions.Timeout:
        result["error"] = f"Timeout ({timeout_seconds}s)"
    except requests.exceptions.RequestException as e:
        status_info = f" (Status: {e.response.status_code})" if hasattr(e, 'response') and e.response is not None else ""
        result["error"] = f"Fetch failed: {e}{status_info}"
        if hasattr(e, 'response') and e.response is not None: result["status_code"] = e.response.status_code # Redundant? Already in status_info maybe, but harmless.
    except Exception as e:
         result["error"] = f"Unexpected fetch error: {e}"
    return result

def ask_user(question: str) -> Dict[str, Any]:
    """Asks the user a question. Handles basic input."""
    try:
        response = input(f"{question}\nYour response: ")
        return {"response": response, "error": None}
    except (KeyboardInterrupt, EOFError):
        return {"response": None, "error": "User interrupted or input closed."}
    except Exception as e:
        return {"response": None, "error": f"Input error: {e}"}

def execute_python_code(code: str, timeout_seconds: int = 30) -> Dict[str, Any]:
    """Executes a Python code snippet in a subprocess."""
    result = {"stdout": None, "stderr": None, "error": None}
    if not code:
        result["error"] = "No code provided to execute."
        return result

    try:
        proc = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_seconds,
            check=False,
        )
        result["stdout"] = proc.stdout.strip()
        result["stderr"] = proc.stderr.strip()
        if proc.returncode != 0 and not result["stderr"]:
             result["stderr"] = f"Python process exited with non-zero code: {proc.returncode}"
    except subprocess.TimeoutExpired:
        result["error"] = f"Python code execution timed out after {timeout_seconds} seconds."
    except FileNotFoundError:
         result["error"] = f"Python executable not found: {sys.executable}" # Unlikely but possible.
    except Exception as e:
        result["error"] = f"Failed to execute Python code: {e}"
        if not result["stderr"]: result["stderr"] = str(e) # Capture exception if no stderr

    return result

TOOL_EXECUTORS = {
    "execute_shell_command": execute_shell_command,
    "read_file": read_file,
    "write_file": write_file,
    "copy_file": copy_file,
    "list_directory": list_directory,
    "create_directory": create_directory,
    "fetch_web_page": fetch_web_page,
    "ask_user": ask_user,
    "execute_python_code": execute_python_code,
}

# --- Dangerous Tool Info ---
class DangerousToolInfo(TypedDict):
    desc: str
    detail_arg: str

DANGEROUS_TOOL_INFO: Dict[str, DangerousToolInfo] = {
    "execute_shell_command":          {"desc": "Execute Shell Command", "detail_arg": "command"},
    "write_file":          {"desc": "Write to File",         "detail_arg": "path"},
    "copy_file":           {"desc": "Copy File",             "detail_arg": "destination_path"},
    "create_directory":    {"desc": "Create Directory",      "detail_arg": "path"},
    "fetch_web_page":      {"desc": "Fetch Web Page",        "detail_arg": "url"},
    "execute_python_code": {"desc": "Execute Python Code",   "detail_arg": "code"},
}
DANGEROUS_TOOLS = set(DANGEROUS_TOOL_INFO.keys())