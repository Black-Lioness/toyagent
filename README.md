# toyagent: Python OpenAI Agent CLI

toyagent is a simple Python command-line interface (CLI) script that acts as an agent interacting with OpenAI-compatible APIs. It can maintain a conversation, use various tools to interact with the file system, fetch web content, ask the user questions, and execute shell commands or Python code snippets (with careful user approval). It can be configured to connect to different models and endpoints.

This script provides a basic alternative to more complex CLI tools, focusing on core agentic functionality and extensibility through tools defined in `toyagent_tools.py`.

## Features

*   **Interactive Chat:** Engage in a back-and-forth conversation.
*   **Single Prompt Execution:** Run the agent for a single, specific task.
*   **Modular Tools:**
	*   `read_file`, `write_file`, `copy_file`, `list_directory`, `create_directory`: File operations.
    *   `execute_shell_command`: Execute shell commands.
	*   `execute_python_code`: Execute a Python code snippet.
    *   `fetch_web_page`: Fetch text content from a URL.
    *   `ask_user`: Pause and ask the user for input during execution.
*   **User Approval:** Prompts the user before executing potentially dangerous tool actions.
*   **Configurable:** Set API Key, Base URL, Model, Temperature, and Top-P via environment variables or command-line arguments.

## Setup

1.  **Download:** Get the repo.
	```bash
	git clone https://github.com/Black-Lioness/toyagent.git
	```
2.  **Install Dependencies:** Create a virtual environment (recommended) and install the required packages:
    ```bash
	pip install -r requirements.txt
    ```
    *(This installs `openai`, `colorama`, and `requests`)*.
3.  **Set API Key:** You need an API key from OpenAI or your API provider.
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

**Interactive Mode:**

Simply run the script without a prompt argument:

```bash
python toyagent.py [options]
```

Type your messages and press Enter. The agent may use tools to fulfill your request, potentially asking for approval for certain actions. To exit, type `quit` or `exit`, or press `Ctrl+C`.

**Single Prompt Mode:**

Provide the prompt as a command-line argument:

```bash
python toyagent.py [options] "Your prompt here"
```

Example:
```bash
python toyagent.py "Read the first 5 lines of README.md and then list the files in the current directory."
```

**Options:**

*   `prompt` (Positional): The initial prompt for single-pass mode. Omit for interactive mode.
*   `-k`, `--api-key YOUR_KEY`: Specify the API key directly (overrides environment variable).
*   `-b`, `--base-url YOUR_URL`: Specify a custom API endpoint (e.g., `http://localhost:8000/v1`).
*   `-m`, `--model MODEL_NAME`: Specify the model to use (default: `gpt-4o-mini`).
*   `-t`, `--temperature TEMP`: Set the sampling temperature (default: 0.6). Lower values are more deterministic.
*   `-p`, `--top-p TOP_P`: Set the nucleus sampling top-p value (default: 0.9).

Example with options:
```bash
python toyagent.py --base-url http://localhost:11434/v1 --api-key ollama --model ToolAce:latest "Fetch the content from https://example.com, execute a python script to count the words, and tell me the count."
```

## Security Warning

⚠️ **Executing shell commands or arbitrary Python code via agent tools is EXTREMELY DANGEROUS.** This script runs commands and code directly on your system *without* sandboxing and with the **same permissions as the script itself**.

⚠️ Writing files, creating directories, copying files, or fetching web pages can also have unintended consequences.

**Review every action requested by the agent VERY carefully before approving execution with 'y'. Do not approve actions unless you fully understand the potential consequences and trust the source of the command or code.**

## Code Structure

*   `toyagent.py`: The main script containing the agent loop, user interaction logic, argument parsing, and API call management.
*   `toyagent_tools.py`: Contains the definitions (JSON schema) and Python implementation functions for all tools the agent can use. This file can be extended with new tools.
