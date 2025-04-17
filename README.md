# Python OpenAI Agent CLI

A simple Python command-line interface (CLI) script that acts as an agent interacting with OpenAI-compatible APIs. It can maintain a conversation, use various tools to interact with the file system, fetch web content, ask the user questions, and execute shell commands (with user approval). It can be configured to connect to different models and endpoints.

This script provides a basic alternative to more complex CLI tools, focusing on core agentic functionality and extensibility through tools defined in `pycodex_tools.py`.

## Features

*   **Interactive Chat:** Engage in a back-and-forth conversation.
*   **Single Prompt Execution:** Run the agent for a single, specific task.
*   **Modular Tools (`pycodex_tools.py`):**
    *   `shell_exec`: Execute shell commands.
    *   `read_file`: Read file contents.
    *   `write_file`: Write content to files.
    *   `list_directory`: List files and directories.
    *   `create_directory`: Create directories.
    *   `fetch_web_page`: Fetch content from a URL.
    *   `ask_user`: Pause and ask the user for input during execution.
*   **User Approval:** Prompts the user before executing potentially dangerous tool actions (shell commands, file writing, directory creation, web fetching).
*   **Configurable:** Set API Key, Base URL, and Model via environment variables or command-line arguments.

## Setup

1.  **Clone or Download:** Get the `pycodex.py`, `pycodex_tools.py`, and `requirements.txt` files and place them in the same directory.
2.  **Install Dependencies:** Create a virtual environment (recommended) and install the required packages:
    ```bash
    python -m venv .venv
    # Activate the virtual environment
    # On Windows (cmd.exe): .venv\Scripts\activate.bat
    # On Windows (PowerShell): .venv\Scripts\Activate.ps1
    # On Linux/macOS: source .venv/bin/activate

    pip install -r requirements.txt
    ```
    *(This installs `openai`, `colorama`, and `requests`)*.
3.  **Set API Key:** You need an API key from OpenAI or your compatible API provider.
    *   **Recommended:** Set the environment variable:
        ```bash
        # Linux/macOS
        export OPENAI_API_KEY='your_api_key_here'

        # Windows (cmd.exe)
        set OPENAI_API_KEY=your_api_key_here

        # Windows (PowerShell)
        $env:OPENAI_API_KEY='your_api_key_here'
        ```
    *   Alternatively, use the `--api-key` command-line flag when running the script.

## Usage

Make sure the script (`pycodex.py`) is executable or run it using `python`.

**Interactive Mode:**

Simply run the script without a prompt argument:

```bash
python pycodex.py [options]
```

Type your messages and press Enter. The agent may use tools to fulfill your request, potentially asking for approval for certain actions. To exit, type `quit` or `exit`, or press `Ctrl+C`.

**Single Prompt Mode:**

Provide the prompt as a command-line argument:

```bash
python pycodex.py [options] "Your prompt here"
```

Example:
```bash
python pycodex.py "Read the first 5 lines of README.md and then list the files in the 'src' directory."
```

**Options:**

*   `--api-key YOUR_KEY`: Specify the API key directly.
*   `--base-url YOUR_URL`: Specify a custom API endpoint (e.g., `http://localhost:11434/v1`).
*   `--model MODEL_NAME`: Specify the model to use (default: `llama3.1:8b`).

Example with options:
```bash
python pycodex.py --model llama3.1:8b --base-url http://localhost:11434/v1 "Fetch the content from https://example.com and summarize it."
```

## Security Warning

⚠️ **Executing shell commands, writing files, creating directories, or fetching web pages via agent tools can be dangerous.** This script runs commands directly on your system *without* sandboxing. Review every action carefully before approving execution with 'y'. Do not approve actions unless you fully understand the potential consequences.

## Code Structure

*   `pycodex.py`: The main script containing the agent loop, user interaction logic, and API call management.
*   `pycodex_tools.py`: Contains the definitions (JSON schema) and Python implementation functions for all tools the agent can use. This file can be extended with new tools.
