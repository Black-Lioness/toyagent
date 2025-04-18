import argparse
import json
import platform
import datetime
import sys
import os
from typing import List, Dict, Any, Optional
try:
    import openai
except ImportError:
    print("Error: The 'openai' library is required. Please install it using 'pip install openai'.", file=sys.stderr)
    sys.exit(1)
try:
    import colorama
    colorama.init(autoreset=True)
except ImportError:
    print("Warning: The 'colorama' library is recommended for colored output.", file=sys.stderr)
    colorama = None
try:
    import toyagent_tools as agent_tools
except ImportError:
    print("Error: Could not find 'toyagent_tools.py' in the same directory.", file=sys.stderr)
    sys.exit(1)

# --- Configuration ---
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.6
DEFAULT_TOP_P = 0.9
ENV_API_KEY = "OPENAI_API_KEY"
ENV_BASE_URL = "OPENAI_BASE_URL"

# --- ANSI Color Codes ---
if colorama:
    CWARN = colorama.Fore.YELLOW
    CERROR = colorama.Fore.RED + colorama.Style.BRIGHT
    CWARN_SEVERE = colorama.Fore.RED
    CASSIST = colorama.Fore.BLUE + colorama.Style.BRIGHT
    CTOOL = colorama.Fore.MAGENTA + colorama.Style.BRIGHT
    CTOOL_RESULT = colorama.Fore.LIGHTBLACK_EX
    CUSER = colorama.Fore.GREEN + colorama.Style.BRIGHT
    CRESET = colorama.Style.RESET_ALL
else:
    CWARN, CERROR, CASSIST, CTOOL, CTOOL_RESULT, CUSER, CRESET = ("",) * 7

# --- Helper Functions ---
def get_current_os_info() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()})"

def get_current_datetime() -> str:
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def print_warning(message: str):
    print(f"{CWARN}Warning: {message}{CRESET}", file=sys.stderr)

def print_severe_warning(message: str):
    print(f"{CWARN_SEVERE}Warning: {message}{CRESET}", file=sys.stderr)

def print_error(message: str):
    print(f"{CERROR}Error: {message}{CRESET}", file=sys.stderr)

def print_assistant_message(content: str):
    print(f"\n{CASSIST}Assistant:{CRESET}\n{content}")

def print_tool_call_request(tool_call: Any) -> Optional[Dict]:
    func = tool_call.function
    print(f"\n{CTOOL}Tool Call Request:{CRESET}\n  Function: {func.name}")
    try:
        args = json.loads(func.arguments)
        # Indent code for readability in the request details
        if func.name == "execute_python_code" and "code" in args:
             args_display = args.copy()
             args_display["code"] = "\n      " + args_display["code"].replace("\n", "\n      ")
             print(f"  Arguments: {json.dumps(args_display, indent=2)}")
        else:
             print(f"  Arguments: {json.dumps(args, indent=2)}")
        return args
    except json.JSONDecodeError:
        print(f"  Arguments (raw): {func.arguments}")
        print_error("Could not parse tool arguments as JSON.")
        return None

def print_tool_result(tool_call_id: str, name: str, content: str):
    print(f"\n{CTOOL_RESULT}Tool Result ({name} [{tool_call_id[:8]}...]):{CRESET}")
    try:
        print(json.dumps(json.loads(content), indent=2))
    except json.JSONDecodeError:
        print(content)

# --- User Approval Logic ---
def ask_for_approval(action_description: str, details: str) -> bool:
    print("\n-------------------------------------")
    print_warning("The assistant wants to perform the following action:")
    print(f"  Action: {action_description}")
    # Special handling for Python code to make it more readable in prompt
    if action_description == "Execute Python Code":
        print(f"  Code:\n-------\n{details}\n-------")
    else:
        print(f"  Details: {details}")
    print(f"OS: {get_current_os_info()}")
    # Add specific warning for code execution
    base_warning = "Executing commands, writing/copying files, creating directories, or accessing the web can be dangerous."
    if action_description == "Execute Python Code":
        print_severe_warning(base_warning + "\nExecuting Python code is EXTREMELY DANGEROUS and runs with script permissions.")
    else:
        print_warning(base_warning)

    print("-------------------------------------")
    while True:
        try:
            sys.stdout.flush()
            response = input("Allow this action? (y/N): ").lower().strip()
            if response == 'y': return True
            if response == 'n' or response == '': return False
            print("Invalid input. Please enter 'y' or 'n'.")
        except (EOFError, KeyboardInterrupt):
            print_error("\nInterrupted/Input closed. Assuming 'No'.")
            return False

# --- Main Logic ---

# Updated DANGEROUS_TOOL_INFO map
DANGEROUS_TOOL_INFO = {
    "execute_shell_command":          {"desc": "Execute Shell Command", "detail_arg": "command"},
    "write_file":          {"desc": "Write to File",         "detail_arg": "path"},
    "copy_file":           {"desc": "Copy File",             "detail_arg": "destination_path"},
    "create_directory":    {"desc": "Create Directory",      "detail_arg": "path"},
    "fetch_web_page":      {"desc": "Fetch Web Page",        "detail_arg": "url"},
    "execute_python_code": {"desc": "Execute Python Code",   "detail_arg": "code"}, # Added
}

def call_api(client: openai.OpenAI, model: str, history: List[Dict[str, Any]], temperature: float, top_p: float) -> Optional[openai.types.chat.ChatCompletion]:
    """Calls the OpenAI API, handling common errors."""
    try:
        return client.chat.completions.create(
            model=model, messages=history, tools=agent_tools.TOOLS_LIST,
            tool_choice="auto", temperature=temperature, top_p=top_p,
        )
    except openai.APIConnectionError as e: print_error(f"API Connection Error: {e}")
    except openai.RateLimitError as e: print_error(f"API Rate Limit Error: {e}")
    except openai.AuthenticationError as e: print_error(f"API Authentication Error: Check key/permissions. {e}")
    except openai.APIStatusError as e: print_error(f"API Status Error: Status={e.status_code}, Response={e.response}")
    except Exception as e: print_error(f"Unexpected API error: {e}")
    return None

def process_api_response(history: List[Dict[str, Any]], response: openai.types.chat.ChatCompletion) -> bool:
    """Processes API response, handles text, dispatches tool calls, and manages history."""
    response_message = response.choices[0].message
    history.append(response_message.model_dump(exclude_unset=True))

    tool_calls = response_message.tool_calls
    if not tool_calls:
        if response_message.content: print_assistant_message(response_message.content)
        return False

    tool_results = []
    print("")

    for tool_call in tool_calls:
        parsed_args = print_tool_call_request(tool_call)
        function_name = tool_call.function.name
        tool_call_id = tool_call.id
        executor_func = agent_tools.TOOL_EXECUTORS.get(function_name)
        tool_content = {}
        approved = True

        if not executor_func:
            print_error(f"Unsupported function called: {function_name}")
            tool_content = {"error": f"Unsupported function: {function_name}", "exit_code": -6}
        elif parsed_args is None:
            print_error(f"Cannot execute tool '{function_name}' due to invalid arguments.")
            tool_content = {"error": "Invalid arguments provided to tool.", "exit_code": -5}
        else:
            # --- Approval Check ---
            if function_name in agent_tools.DANGEROUS_TOOLS:
                info = DANGEROUS_TOOL_INFO.get(function_name, {})
                action_desc = info.get("desc", f"Execute {function_name}")
                detail_arg_name = info.get("detail_arg")
                # Extract detail, handling potential missing key
                approval_details = parsed_args.get(detail_arg_name, '<missing detail>') if detail_arg_name else json.dumps(parsed_args)
                # For python code, just pass the code string directly for better formatting in ask_for_approval
                if function_name == "execute_python_code":
                     details_to_show = approval_details
                else: # Keep JSON structure for others unless it was simple string
                     details_to_show = json.dumps(parsed_args) if not isinstance(approval_details, str) else approval_details

                approved = ask_for_approval(action_desc, details_to_show)
            # --- End Approval Check ---

            if approved:
                print(f"{CTOOL_RESULT}Running tool: {function_name}...{CRESET}")
                try:
                    kwargs = {"CUSER": CUSER, "CRESET": CRESET} if function_name == "ask_user" else {}
                    tool_content = executor_func(**parsed_args, **kwargs)
                    print(f"{CTOOL_RESULT}Tool {function_name} finished.{CRESET}")
                except Exception as e:
                    print_error(f"Error executing tool '{function_name}': {e}")
                    tool_content = {"error": f"Tool execution failed: {e}"}
                    # Ensure exit code is present if tool fails internally (less likely now with try/except in tool func)
                    if "exit_code" not in tool_content: tool_content["exit_code"] = -7

            else:
                print(f"{CTOOL_RESULT}Action skipped by user.{CRESET}")
                tool_content = {"error": "Action denied by user."}
                # Add exit code for denial if tool didn't set one (it shouldn't have run)
                if "exit_code" not in tool_content: tool_content["exit_code"] = -4


        result_data = {
            "tool_call_id": tool_call_id, "role": "tool", "name": function_name,
            "content": json.dumps(tool_content),
        }
        tool_results.append(result_data)
        print_tool_result(tool_call_id, function_name, result_data["content"])

    history.extend(tool_results)
    return True

# --- Main Execution Modes ---

def create_system_prompt(task_description: str) -> Dict[str, str]:
    # Updated list of tools in prompt
    tool_names = ', '.join(agent_tools.TOOL_EXECUTORS.keys())
    return {
        "role": "system",
        "content": (
            f"You are a helpful coding assistant running in a CLI environment on {get_current_os_info()}, {task_description}. "
            f"Available tools: {tool_names}. "
            f"Be precise and careful. Ensure shell commands match the OS. Requires user approval for dangerous actions "
            f"(especially execute_shell_command and execute_python_code). Current date: {get_current_datetime()}."
        ),
    }

def run_loop(client: openai.OpenAI, model: str, history: List[Dict[str, Any]], temperature: float, top_p: float):
    needs_another_call = True
    while needs_another_call:
        print(f"{CTOOL_RESULT}Waiting for assistant...{CRESET}")
        response = call_api(client, model, history, temperature, top_p)
        if response:
            needs_another_call = process_api_response(history, response)
        else:
            needs_another_call = False

def run_interactive(client: openai.OpenAI, model: str, temperature: float, top_p: float):
    print(f"Starting interactive session (Model: {model}, Temp: {temperature}, Top-P: {top_p}, OS: {get_current_os_info()})")
    print("Type 'quit' or 'exit' to end.")
    # Updated warning
    print_warning("Review dangerous actions (execute_shell_command, execute_python_code, file ops, web fetch) VERY carefully.")
    if platform.system() == "Windows":
        print_warning("On Windows, ensure shell commands use cmd.exe syntax (e.g., 'dir').")

    history = [create_system_prompt("ready for interactive user requests")]

    while True:
        try:
            user_input = input(f"\n{CUSER}User:{CRESET}\n").strip()
            if user_input.lower() in ['quit', 'exit']: break
            if not user_input: continue
            history.append({"role": "user", "content": user_input})
            run_loop(client, model, history, temperature, top_p)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

def run_single_pass(client: openai.OpenAI, model: str, initial_prompt: str, temperature: float, top_p: float):
    print(f"Running single prompt (Model: {model}, Temp: {temperature}, Top-P: {top_p}, OS: {get_current_os_info()})")
    # Updated warning
    print_warning("Review dangerous actions (execute_shell_command, execute_python_code, file ops, web fetch) VERY carefully.")
    if platform.system() == "Windows":
        print_warning("On Windows, ensure shell commands use cmd.exe syntax.")

    history = [
        create_system_prompt("executing a single task given by the user"),
        {"role": "user", "content": initial_prompt}
    ]
    run_loop(client, model, history, temperature, top_p)
    print("\nTask finished.")

# --- Main Execution ---

def main():
    if colorama: colorama.init(autoreset=True)

    parser = argparse.ArgumentParser(
        description="Python CLI agent interacting with OpenAI-compatible APIs using tools.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("prompt", nargs="?", help="Initial prompt. If omitted, enters interactive mode.")
    parser.add_argument("-k", "--api-key", default=os.getenv(ENV_API_KEY), help=f"API key (or use ${ENV_API_KEY}).")
    parser.add_argument("-b", "--base-url", default=os.getenv(ENV_BASE_URL), help=f"API base URL (or use ${ENV_BASE_URL}).")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Model name.")
    parser.add_argument("-t", "--temperature", type=float, default=DEFAULT_TEMPERATURE, help="Sampling temperature (e.g., 0.6).")
    parser.add_argument("-p", "--top-p", type=float, default=DEFAULT_TOP_P, help="Nucleus sampling 'top_p' (e.g., 0.9).")
    args = parser.parse_args()

    if not args.api_key:
        print_error(f"API key required via --api-key or ${ENV_API_KEY}.")
        sys.exit(1)

    try:
        client = openai.OpenAI(api_key=args.api_key, base_url=args.base_url)
    except Exception as e:
        print_error(f"Failed to initialize OpenAI client: {e}")
        sys.exit(1)

    if args.prompt:
        run_single_pass(client, args.model, args.prompt, args.temperature, args.top_p)
    else:
        run_interactive(client, args.model, args.temperature, args.top_p)

if __name__ == "__main__":
    main()