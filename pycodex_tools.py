# tools.py
import os
import sys
import json
import subprocess
import platform
import datetime
import pathlib
import shutil # Added for copy_file
from typing import Dict, Any, Optional, List

# --- Dependencies (Add requests to requirements.txt) ---
try:
    import requests
except ImportError:
    print("Error: The 'requests' library is required for fetch_web_page. "
          "Please install it using 'pip install requests'.", file=sys.stderr)
    requests = None

# --- Tool Definitions (JSON Schema for OpenAI API) ---

SHELL_EXEC_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "shell_exec",
        "description": "Execute a shell command and return its stdout, stderr, and exit code. Use OS-specific commands (cmd.exe on Windows, sh/bash on Linux/macOS). Requires user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command string to execute.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Optional directory path to execute the command in.",
                    "nullable": True,
                },
                "timeout_seconds": { # <-- Schema uses timeout_seconds
                    "type": "integer",
                    "description": "Optional timeout in seconds.",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
}

READ_FILE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Reads the entire content of a specified file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The relative or absolute path to the file to read.",
                }
            },
            "required": ["path"],
        },
    },
}

WRITE_FILE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Writes content to a specified file. Creates directories if needed. Requires user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The relative or absolute path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite the file if it exists.",
                    "default": False,
                },
            },
            "required": ["path", "content"],
        },
    },
}

# --- NEW: Copy File Tool Schema ---
COPY_FILE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "copy_file",
        "description": "Copies a source file to a destination path. Creates destination directories if needed. Requires user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "The relative or absolute path of the file to copy.",
                },
                "destination_path": {
                    "type": "string",
                    "description": "The relative or absolute path where the file should be copied.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite the destination file if it already exists.",
                    "default": False,
                },
            },
            "required": ["source_path", "destination_path"],
        },
    },
}


LIST_DIRECTORY_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_directory",
        "description": "Lists the files and subdirectories within a specified directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The relative or absolute path to the directory.",
                    "default": ".",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list contents recursively (use with caution on large directories).",
                    "default": False,
                },
            },
            "required": [],
        },
    },
}

CREATE_DIRECTORY_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_directory",
        "description": "Creates a new directory, including any necessary parent directories. Requires user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The relative or absolute directory path to create.",
                }
            },
            "required": ["path"],
        },
    },
}

FETCH_WEB_PAGE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_web_page",
        "description": "Fetches the text content of a given URL. Requires user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must include http:// or https://).",
                },
                "timeout_seconds": { # <-- Schema uses timeout_seconds
                    "type": "integer",
                    "description": "Optional timeout in seconds.",
                    "default": 10,
                },
            },
            "required": ["url"],
        },
    },
}

ASK_USER_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": "Asks the human user a question and returns their response.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user.",
                }
            },
            "required": ["question"],
        },
    },
}


# --- Updated TOOLS_LIST ---
TOOLS_LIST = [
    SHELL_EXEC_TOOL_SCHEMA,
    READ_FILE_TOOL_SCHEMA,
    WRITE_FILE_TOOL_SCHEMA,
    COPY_FILE_TOOL_SCHEMA,
    LIST_DIRECTORY_TOOL_SCHEMA,
    CREATE_DIRECTORY_TOOL_SCHEMA,
    FETCH_WEB_PAGE_TOOL_SCHEMA,
    ASK_USER_TOOL_SCHEMA,
]

# --- Tool Implementation Functions ---

def execute_shell_command(command: str, working_directory: Optional[str] = None, timeout_seconds: int = 60) -> Dict[str, Any]:
    """Executes a shell command and returns its output."""
    result = {"stdout": "", "stderr": "", "exit_code": None, "error": None}
    effective_cwd = working_directory or os.getcwd()
    print(f"  (Executing in: {effective_cwd})")

    if not os.path.isdir(effective_cwd):
         result["error"] = f"Working directory not found: {effective_cwd}"
         result["exit_code"] = -2
         return result

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=effective_cwd,
            timeout=timeout_seconds, # Use the renamed parameter
            check=False,
        )
        result["stdout"] = proc.stdout.strip()
        result["stderr"] = proc.stderr.strip()
        result["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        result["error"] = f"Command timed out after {timeout_seconds} seconds."
        result["exit_code"] = -1
    except FileNotFoundError:
        result["error"] = f"Command not found or invalid: {command.split()[0]}"
        result["exit_code"] = -2
    except Exception as e:
        result["error"] = f"Failed to execute command: {e}"
        result["exit_code"] = -3
        if not result["stderr"]:
             result["stderr"] = str(e)
    return result

def read_file(path: str) -> Dict[str, Any]:
    """Reads the content of a file."""
    result = {"content": None, "error": None}
    try:
        p = pathlib.Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Source path is not a file: {path}")
        result["content"] = p.read_text(encoding='utf-8', errors='replace')
    except FileNotFoundError:
        result["error"] = f"File not found: {path}"
    except PermissionError:
        result["error"] = f"Permission denied to read file: {path}"
    except UnicodeDecodeError as e:
        result["error"] = f"Cannot decode file content (not valid UTF-8?): {path} - {e}"
    except Exception as e:
        result["error"] = f"Failed to read file '{path}': {e}"
    return result

def write_file(path: str, content: str, overwrite: bool = False) -> Dict[str, Any]:
    """Writes content to a file."""
    result = {"success": False, "error": None}
    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = 'w' if overwrite else 'x'
        with p.open(mode=mode, encoding='utf-8') as f:
            f.write(content)
        result["success"] = True
    except FileExistsError:
        result["error"] = f"File already exists and overwrite is false: {path}"
    except IsADirectoryError: # Catch if path is actually a directory
        result["error"] = f"Path is a directory, cannot write file: {path}"
    except PermissionError:
        result["error"] = f"Permission denied to write file: {path}"
    except Exception as e:
        result["error"] = f"Failed to write file '{path}': {e}"
    return result

def copy_file(source_path: str, destination_path: str, overwrite: bool = False) -> Dict[str, Any]:
    """Copies a file from source to destination."""
    result = {"success": False, "error": None}
    try:
        src = pathlib.Path(source_path)
        dest = pathlib.Path(destination_path)

        if not src.is_file():
            raise FileNotFoundError(f"Source path is not a file or does not exist: {source_path}")

        if dest.exists() and not overwrite:
            raise FileExistsError(f"Destination path already exists and overwrite is false: {destination_path}")
        elif dest.exists() and dest.is_dir():
             raise IsADirectoryError(f"Destination path is a directory, cannot overwrite with a file: {destination_path}")
        elif dest.exists() and overwrite and not dest.is_file():
             # Safety check: don't overwrite non-files even if overwrite=True
             raise ValueError(f"Destination path exists but is not a file, cannot overwrite: {destination_path}")

        # Ensure destination directory exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Perform the copy
        shutil.copy2(src, dest) # copy2 preserves metadata like timestamps
        result["success"] = True

    except FileNotFoundError as e:
        result["error"] = str(e)
    except FileExistsError as e:
        result["error"] = str(e)
    except IsADirectoryError as e:
        result["error"] = str(e)
    except PermissionError:
        result["error"] = f"Permission denied during copy operation (source: {source_path}, dest: {destination_path})"
    except shutil.Error as e: # Catch specific shutil errors
         result["error"] = f"File copy error: {e}"
    except Exception as e:
        result["error"] = f"Failed to copy file from '{source_path}' to '{destination_path}': {e}"
    return result


def list_directory(path: str = ".", recursive: bool = False) -> Dict[str, Any]:
    """Lists directory contents."""
    result: Dict[str, Any] = {"entries": None, "error": None}
    try:
        p = pathlib.Path(path)
        if not p.is_dir():
            raise FileNotFoundError(f"Path is not a directory: {path}")
        entries = []
        if recursive:
            for root, dirs, files in os.walk(path, topdown=True): # topdown=True is default, explicit here
                # To prevent recursion into potentially huge/problematic dirs,
                # one could filter `dirs` list here based on name, depth, etc.
                # Example: dirs[:] = [d for d in dirs if not d.startswith('.')] # skip hidden
                rel_root = os.path.relpath(root, path)
                if rel_root == ".": rel_root = ""
                prefix = f"{rel_root}{os.sep}" if rel_root else ""
                for name in sorted(dirs):
                    entries.append(f"{prefix}{name}{os.sep}")
                for name in sorted(files):
                    entries.append(f"{prefix}{name}")
        else:
            for entry in sorted(os.listdir(path)):
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    entries.append(entry + os.sep)
                else:
                    entries.append(entry)
        result["entries"] = entries
    except FileNotFoundError:
        result["error"] = f"Directory not found: {path}"
    except PermissionError:
        result["error"] = f"Permission denied to list directory: {path}"
    except Exception as e:
        result["error"] = f"Failed to list directory '{path}': {e}"
    return result

def create_directory(path: str) -> Dict[str, Any]:
    """Creates a directory."""
    result = {"success": False, "error": None}
    try:
        p = pathlib.Path(path)
        p.mkdir(parents=True, exist_ok=True)
        result["success"] = True
    except PermissionError:
        result["error"] = f"Permission denied to create directory: {path}"
    except FileExistsError: # Although exist_ok=True, check if it's a file
        if not p.is_dir():
            result["error"] = f"Path exists but is not a directory: {path}"
        else: # Directory already exists, which is fine with exist_ok=True
             result["success"] = True
    except Exception as e:
        result["error"] = f"Failed to create directory '{path}': {e}"
    return result

# *** FIX: Changed timeout parameter name to timeout_seconds to match schema ***
def fetch_web_page(url: str, timeout_seconds: int = 10) -> Dict[str, Any]:
    """Fetches the text content of a web page."""
    result: Dict[str, Any] = {"content": None, "status_code": None, "error": None}
    if requests is None:
        result["error"] = "The 'requests' library is not installed."
        return result
    if not url.startswith(('http://', 'https://')):
        result["error"] = "URL must start with http:// or https://"
        return result

    try:
        response = requests.get(url, timeout=timeout_seconds, headers={'User-Agent': 'PythonAgent/1.0'})
        result["status_code"] = response.status_code
        response.raise_for_status()
        response.encoding = response.apparent_encoding or 'utf-8'
        result["content"] = response.text
    except requests.exceptions.Timeout:
        result["error"] = f"Request timed out after {timeout_seconds} seconds."
    except requests.exceptions.RequestException as e:
        result["error"] = f"Failed to fetch URL '{url}': {e}"
        if hasattr(e, 'response') and e.response is not None:
            result["status_code"] = e.response.status_code
    except Exception as e:
         result["error"] = f"An unexpected error occurred fetching URL '{url}': {e}"
    return result

def ask_user(question: str, CUSER: str, CRESET: str) -> Dict[str, Any]:
    """Asks the user a question."""
    result = {"response": None, "error": None}
    try:
        response = input(f"\n{CUSER}Assistant asks:{CRESET} {question}\nYour response: ")
        result["response"] = response
    except KeyboardInterrupt:
        result["error"] = "User interrupted the question."
    except EOFError:
        result["error"] = "Input stream closed while asking question."
    except Exception as e:
        result["error"] = f"An error occurred asking the user: {e}"
    return result


# --- Updated TOOL_EXECUTORS ---
TOOL_EXECUTORS = {
    "shell_exec": execute_shell_command,
    "read_file": read_file,
    "write_file": write_file,
    "copy_file": copy_file,
    "list_directory": list_directory,
    "create_directory": create_directory,
    "fetch_web_page": fetch_web_page,
    "ask_user": ask_user,
}

# --- Updated DANGEROUS_TOOLS ---
DANGEROUS_TOOLS = {
    "shell_exec",
    "write_file",
    "copy_file",
    "create_directory",
    "fetch_web_page",
}