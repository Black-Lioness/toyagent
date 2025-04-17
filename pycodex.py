#!/usr/bin/env python3

import argparse
import os
import sys
import json
# Removed subprocess import - now handled in pycodex_tools.py
import platform
import datetime
from typing import List, Dict, Any, Optional, Tuple

# --- Dependencies ---
try:
    import openai
except ImportError:
    print("Error: The 'openai' library is required. Please install it using 'pip install openai'.")
    sys.exit(1)

try:
    import colorama
    colorama.init(autoreset=True)
except ImportError:
    print("Warning: The 'colorama' library is recommended for colored output on Windows.")
    print("Install it using 'pip install colorama'.")
    colorama = None

# --- Import Tools ---
try:
    # Import the tools module and the list of tool definitions
    import pycodex_tools as agent_tools
except ImportError:
    print("Error: Could not find the 'pycodex_tools.py' file in the same directory.", file=sys.stderr)
    sys.exit(1)


# --- Configuration ---
DEFAULT_MODEL = "gpt-4o-mini"
ENV_API_KEY = "OPENAI_API_KEY"
ENV_BASE_URL = "OPENAI_BASE_URL"

# --- ANSI Color Codes ---
if colorama:
    CWARN = colorama.Fore.YELLOW
    CERROR = colorama.Fore.RED
    CASSIST = colorama.Fore.BLUE + colorama.Style.BRIGHT
    CTOOL = colorama.Fore.MAGENTA + colorama.Style.BRIGHT
    CTOOL_RESULT = colorama.Fore.LIGHTBLACK_EX
    CUSER = colorama.Fore.GREEN + colorama.Style.BRIGHT
    CRESET = colorama.Style.RESET_ALL
else:
    CWARN, CERROR, CASSIST, CTOOL, CTOOL_RESULT, CUSER, CRESET = ("",)*7

# --- Helper Functions --- (Keep OS/Date/Print helpers here)
def get_current_os_info() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()})"

def get_current_datetime() -> str:
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def print_warning(message: str):
    print(f"{CWARN}Warning: {message}{CRESET}", file=sys.stderr)

def print_error(message: str):
    print(f"{CERROR}Error: {message}{CRESET}", file=sys.stderr)

def print_assistant_message(content: str):
    print(f"\n{CASSIST}Assistant:{CRESET}\n{content}")

def print_tool_call_request(tool_call: Any):
    func = tool_call.function
    print(f"\n{CTOOL}Tool Call Request:{CRESET}")
    print(f"  Function: {func.name}")
    try:
        args = json.loads(func.arguments)
        print(f"  Arguments: {json.dumps(args, indent=2)}")
        return args
    except json.JSONDecodeError:
        print(f"  Arguments (raw): {func.arguments}")
        print_error("Could not parse tool arguments as JSON.")
        return None

def print_tool_result(tool_call_id: str, name: str, content: str):
    print(f"\n{CTOOL_RESULT}Tool Result ({name} [{tool_call_id[:8]}...]):{CRESET}")
    try:
        data = json.loads(content)
        print(json.dumps(data, indent=2))
    except json.JSONDecodeError:
        print(content)

# --- User Approval Logic (Stays in main script) ---
def ask_for_approval(action_description: str, details: str) -> bool:
    """Asks the user to approve a potentially dangerous action."""
    print("\n-------------------------------------")
    print_warning(f"The assistant wants to perform the following action:")
    print(f"  Action: {action_description}")
    print(f"  Details: {details}")
    print(f"OS: {get_current_os_info()}")
    print_warning("Executing commands, writing files, or accessing the web can be dangerous.")
    print("-------------------------------------")
    while True:
        try:
            sys.stdout.flush()
            response = input("Allow this action? (y/N): ").lower().strip()
            if response == 'y':
                return True
            elif response == 'n' or response == '':
                return False
            else:
                print("Invalid input. Please enter 'y' or 'n'.")
        except EOFError:
            print_error("\nInput stream closed. Assuming 'No'.")
            return False
        except KeyboardInterrupt:
            print_error("\nInterrupted. Assuming 'No'.")
            return False

# --- Main Logic ---

def call_api(client: openai.OpenAI, model: str, history: List[Dict[str, Any]]) -> Optional[openai.types.chat.ChatCompletion]:
    """Calls the OpenAI API."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=history,
            tools=agent_tools.TOOLS_LIST, # Use the list from pycodex_tools.py
            tool_choice="auto",
        )
        return response
    except openai.APIConnectionError as e:
        print_error(f"API Connection Error: {e}")
    except openai.RateLimitError as e:
        print_error(f"API Rate Limit Error: {e}")
    except openai.AuthenticationError as e:
        print_error(f"API Authentication Error: Check your API key and permissions. {e}")
    except openai.APIStatusError as e:
        print_error(f"API Status Error: Status={e.status_code}, Response={e.response}")
    except Exception as e:
        print_error(f"An unexpected error occurred calling the API: {e}")
    return None

def process_api_response(client: openai.OpenAI, model: str, history: List[Dict[str, Any]], response: openai.types.chat.ChatCompletion) -> bool:
    """Processes the API response, handling text and dispatching tool calls."""
    response_message = response.choices[0].message
    history.append(response_message.model_dump(exclude_unset=True))

    tool_calls = response_message.tool_calls
    if tool_calls:
        tool_results = []
        print("") # Newline before tool processing starts

        for tool_call in tool_calls:
            parsed_args = print_tool_call_request(tool_call)
            function_name = tool_call.function.name
            tool_call_id = tool_call.id

            executor_func = agent_tools.TOOL_EXECUTORS.get(function_name)

            if executor_func:
                if parsed_args is None:
                    # Handle cases where argument parsing failed earlier
                    print_error(f"Cannot execute tool '{function_name}' due to invalid arguments.")
                    tool_results.append({
                        "tool_call_id": tool_call_id, "role": "tool", "name": function_name,
                        "content": json.dumps({"error": "Invalid arguments provided to tool.", "exit_code": -5})
                    })
                    continue # Skip to next tool call

                # --- Approval Check for Dangerous Tools ---
                needs_approval = function_name in agent_tools.DANGEROUS_TOOLS
                approved = True # Assume safe unless proven otherwise
                approval_details = "" # String describing the action for the user

                if needs_approval:
                    if function_name == "shell_exec":
                         action_desc = "Execute Shell Command"
                         approval_details = parsed_args.get('command', '<missing command>')
                    elif function_name == "write_file":
                         action_desc = "Write to File"
                         approval_details = parsed_args.get('path', '<missing path>')
                    elif function_name == "create_directory":
                         action_desc = "Create Directory"
                         approval_details = parsed_args.get('path', '<missing path>')
                    elif function_name == "fetch_web_page":
                         action_desc = "Fetch Web Page"
                         approval_details = parsed_args.get('url', '<missing url>')
                    else: # Should not happen if DANGEROUS_TOOLS is correct
                         action_desc = f"Execute {function_name}"
                         approval_details = json.dumps(parsed_args)

                    approved = ask_for_approval(action_desc, approval_details)
                # --- End Approval Check ---

                tool_content = {}
                if approved:
                    print(f"{CTOOL_RESULT}Running tool: {function_name}...{CRESET}")
                    try:
                        # Pass color codes only if the tool is ask_user
                        if function_name == "ask_user":
                            tool_content = executor_func(CUSER=CUSER, CRESET=CRESET, **parsed_args)
                        else:
                            tool_content = executor_func(**parsed_args)
                        print(f"{CTOOL_RESULT}Tool {function_name} finished.{CRESET}")
                    except Exception as e:
                        # Catch errors within the tool execution itself
                        print_error(f"Error executing tool '{function_name}': {e}")
                        tool_content = {"error": f"Tool execution failed: {e}"}
                        if "exit_code" not in tool_content: # Add exit code if not present
                             tool_content["exit_code"] = -7
                else:
                    print(f"{CTOOL_RESULT}Action skipped by user.{CRESET}")
                    tool_content = {"error": "Action denied by user."}
                    if "exit_code" not in tool_content: # Add specific exit code for denial
                         tool_content["exit_code"] = -4

                tool_results.append({
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(tool_content),
                })
                print_tool_result(tool_call_id, function_name, json.dumps(tool_content))

            else:
                print_error(f"Unsupported function called: {function_name}")
                tool_results.append({
                    "tool_call_id": tool_call_id, "role": "tool", "name": function_name,
                    "content": json.dumps({"error": f"Unsupported function: {function_name}", "exit_code": -6})
                })

        history.extend(tool_results)
        return True # Indicate another API call is needed

    elif response_message.content:
        print_assistant_message(response_message.content)

    return False # No tool calls, interaction loop can wait for user

# --- Interactive and Single-Pass Functions (remain largely the same) ---

def run_interactive(client: openai.OpenAI, model: str):
    """Runs the agent in interactive mode."""
    print(f"Starting interactive session with model: {model}")
    print(f"Running on: {get_current_os_info()}")
    print("Type 'quit' or 'exit' to end the session.")
    print_warning("Review dangerous actions (shell commands, file writes, web fetches) carefully.")
    if platform.system() == "Windows":
        print_warning("You are on Windows. Ensure shell commands use cmd.exe syntax (e.g., 'dir').")

    history: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                f"You are a helpful coding assistant running in a CLI environment on {get_current_os_info()}. "
                f"You can use tools like 'shell_exec', 'read_file', 'write_file', 'list_directory', "
                f"'create_directory', 'fetch_web_page', and 'ask_user' to interact with the system and user. "
                f"Be precise and careful. Ensure shell commands are compatible with the OS. "
                f"Today's date is {get_current_datetime()}"
            ),
        }
    ]

    while True:
        try:
            user_input = input(f"\n{CUSER}User:{CRESET}\n").strip()
            if user_input.lower() in ['quit', 'exit']:
                break
            if not user_input:
                continue

            history.append({"role": "user", "content": user_input})

            needs_another_call = True
            while needs_another_call:
                print(f"{CTOOL_RESULT}Waiting for assistant...{CRESET}")
                response = call_api(client, model, history)
                if response:
                    needs_another_call = process_api_response(client, model, history, response)
                else:
                    needs_another_call = False

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except EOFError:
            print("\nExiting...")
            break

def run_single_pass(client: openai.OpenAI, model: str, initial_prompt: str):
    """Runs the agent for a single prompt."""
    print(f"Running single prompt with model: {model}")
    print(f"Running on: {get_current_os_info()}")
    print_warning("Review dangerous actions (shell commands, file writes, web fetches) carefully.")
    if platform.system() == "Windows":
        print_warning("You are on Windows. Ensure shell commands use cmd.exe syntax.")

    history: List[Dict[str, Any]] = [
         {
            "role": "system",
            "content": (
                f"You are a helpful coding assistant running in a CLI environment on {get_current_os_info()}, executing a single task. "
                f"You can use tools like 'shell_exec', 'read_file', 'write_file', 'list_directory', "
                f"'create_directory', 'fetch_web_page', and 'ask_user' to interact with the system and user. "
                f"Be precise and careful. Ensure shell commands are compatible with the OS. "
                f"Today's date is {get_current_datetime()}"
            ),
        },
        {"role": "user", "content": initial_prompt}
    ]

    needs_another_call = True
    while needs_another_call:
        print(f"{CTOOL_RESULT}Waiting for assistant...{CRESET}")
        response = call_api(client, model, history)
        if response:
            needs_another_call = process_api_response(client, model, history, response)
        else:
            needs_another_call = False
            print_error("Failed to get response from API.")

    print("\nTask finished.")

# --- Main Execution ---

def main():
    if colorama:
        colorama.init(autoreset=True)

    parser = argparse.ArgumentParser(
        description="A Python CLI agent with tools, interacting with OpenAI-compatible APIs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("prompt", nargs="?", help="Initial prompt. If omitted, enters interactive mode.")
    parser.add_argument("-k", "--api-key", default=os.getenv(ENV_API_KEY), help=f"API key (or use ${ENV_API_KEY}).")
    parser.add_argument("-b", "--base-url", default=os.getenv(ENV_BASE_URL), help=f"API base URL (or use ${ENV_BASE_URL}).")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Model name.")

    args = parser.parse_args()

    if not args.api_key:
        print_error(f"API key is required via --api-key or ${ENV_API_KEY}.")
        sys.exit(1)

    try:
        client = openai.OpenAI(api_key=args.api_key, base_url=args.base_url)
    except Exception as e:
        print_error(f"Failed to initialize OpenAI client: {e}")
        sys.exit(1)

    if args.prompt:
        run_single_pass(client, args.model, args.prompt)
    else:
        run_interactive(client, args.model)

if __name__ == "__main__":
    main()