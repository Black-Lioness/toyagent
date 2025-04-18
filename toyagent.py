import argparse
import json
import platform
import datetime
import sys
import os
import openai
from typing import List, Dict, Any, Optional
import toyagent_tools as agent_tools
try:
    import colorama
    colorama.init(autoreset=True)
    CWARN = colorama.Fore.YELLOW
    CERROR = colorama.Fore.RED + colorama.Style.BRIGHT
    CWARN_SEVERE = colorama.Fore.RED
    CASSIST = colorama.Fore.BLUE + colorama.Style.BRIGHT
    CTOOL = colorama.Fore.MAGENTA + colorama.Style.BRIGHT
    CTOOL_RESULT = colorama.Fore.LIGHTBLACK_EX
    CUSER = colorama.Fore.GREEN + colorama.Style.BRIGHT
    CRESET = colorama.Style.RESET_ALL
except ImportError:
    print("Warning: The 'colorama' library is recommended for colored output. Install with 'pip install colorama'.", file=sys.stderr)
    colorama = None # type: ignore
    CWARN, CERROR, CWARN_SEVERE, CASSIST, CTOOL, CTOOL_RESULT, CUSER, CRESET = ("",) * 8

# --- Configuration ---
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.6
DEFAULT_TOP_P = 0.9
ENV_API_KEY = "OPENAI_API_KEY"
ENV_BASE_URL = "OPENAI_BASE_URL"

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
        if func.name == "execute_python_code" and "code" in args:
             args_display = args.copy()
             code_str = str(args_display.get("code", ""))
             args_display["code"] = "\n      " + code_str.replace("\n", "\n      ")
             print(f"  Arguments:\n{json.dumps(args_display, indent=2)}")
        else:
             print(f"  Arguments:\n{json.dumps(args, indent=2)}")
        return args
    except json.JSONDecodeError:
        print(f"  Arguments (raw): {func.arguments}")
        print_error("Could not parse tool arguments as JSON.")
        return None
    except Exception as e:
        print_error(f"Could not display tool arguments: {e}")
        print(f"  Arguments (raw): {func.arguments}")
        return None


def print_tool_result(tool_call_id: str, name: str, content: str):
    print(f"\n{CTOOL_RESULT}Tool Result ({name} [{tool_call_id[:8]}...]):{CRESET}")
    try:
        # Nicely format JSON results.
        print(json.dumps(json.loads(content), indent=2))
    except json.JSONDecodeError:
        print(content)
    except Exception as e:
        print_error(f"Could not display tool result: {e}")
        print(content)

# --- User Approval Logic ---
def ask_for_approval(action_description: str, details: str) -> bool:
    print("\n-------------------------------------")
    print_warning("The assistant wants to perform the following action:")
    print(f"  Action: {action_description}")
    if action_description == "Execute Python Code":
        code_details = str(details) if details is not None else "<Code not available>"
        print(f"  Code:\n-------\n{code_details}\n-------")
    else:
        details_str = str(details) if details is not None else "<Details not available>"
        print(f"  Details: {details_str}")
    print(f"OS: {get_current_os_info()}")
    base_warning = "Executing commands, writing/copying files, creating directories, or accessing the web can be dangerous."
    if action_description == "Execute Python Code":
        print_severe_warning("Executing Python code is EXTREMELY DANGEROUS and runs with script permissions.")
    elif action_description == "Execute Shell Command":
        print_severe_warning(base_warning + "\nExecuting SHELL commands can have unintended consequences. Review carefully.")
    else:
        print_warning(base_warning)

    print("-------------------------------------")
    while True:
        try:
            sys.stdout.flush()
            response = input(f"Allow this action? ({CUSER}y{CRESET}/{CWARN_SEVERE}N{CRESET}): ").lower().strip()
            if response == 'y': return True
            if response == 'n' or response == '': return False
            print("Invalid input. Please enter 'y' or 'n'.")
        except (EOFError, KeyboardInterrupt):
            print_error("\nInterrupted/Input closed. Assuming 'No'.")
            return False

# --- Main Logic ---
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

    for tool_call in tool_calls:
        parsed_args = print_tool_call_request(tool_call)
        function_name = tool_call.function.name
        tool_call_id = tool_call.id
        executor_func = agent_tools.TOOL_EXECUTORS.get(function_name)
        tool_content: Dict[str, Any] = {} # Ensure it's always a dict
        approved = True # Assume approved unless dangerous and denied.

        if not executor_func:
            print_error(f"Unsupported function called: {function_name}")
            tool_content = {"error": f"Unsupported function: {function_name}", "exit_code": -6} # Internal error code
        elif parsed_args is None:
            print_error(f"Cannot execute tool '{function_name}' due to invalid arguments.")
            tool_content = {"error": "Invalid arguments provided to tool.", "exit_code": -5} # Internal error code
        else:
            # --- Approval Check ---
            if function_name in agent_tools.DANGEROUS_TOOLS:
                info = agent_tools.DANGEROUS_TOOL_INFO.get(function_name, {})
                action_desc = info.get("desc", f"Execute {function_name}") # Default description
                detail_arg_name = info.get("detail_arg")
                approval_details_raw = parsed_args.get(detail_arg_name) if detail_arg_name else None
                approval_details = approval_details_raw if approval_details_raw is not None else json.dumps(parsed_args)
                details_to_show = approval_details_raw if function_name == "execute_python_code" and detail_arg_name == "code" else approval_details
                approved = ask_for_approval(action_desc, str(details_to_show)) # Ensure details are string for prompt
            # --- End Approval Check ---

            if approved:
                print(f"{CTOOL_RESULT}Running tool: {function_name}...{CRESET}")
                try:
                    if function_name == "ask_user":
                         print(f"\n{CUSER}Assistant asks:{CRESET}", end=" ") # Print prompt prefix
                         tool_content = executor_func(**parsed_args)
                    else:
                         tool_content = executor_func(**parsed_args)

                    if not isinstance(tool_content, dict):
                         print_error(f"Tool '{function_name}' returned unexpected type: {type(tool_content)}. Content: {tool_content}")
                         tool_content = {"error": "Tool returned invalid data type.", "tool_output": str(tool_content)}

                    print(f"{CTOOL_RESULT}Tool {function_name} finished.{CRESET}")
                except Exception as e:
                    print_error(f"Error executing tool '{function_name}': {e}")
                    tool_content = {"error": f"Tool execution failed: {e}"}
                    if "exit_code" not in tool_content: tool_content["exit_code"] = -7 # Internal error code

            else:
                print(f"{CTOOL_RESULT}Action skipped by user.{CRESET}")
                tool_content = {"error": "Action denied by user."}
                if "exit_code" not in tool_content: tool_content["exit_code"] = -4 # Internal error code

        # --- Prepare and Store Result ---
        # Ensure content is JSON serializable string. Handles dicts, primitives.
        try:
            content_str = json.dumps(tool_content)
        except TypeError as e:
            print_error(f"Failed to serialize tool result for '{function_name}': {e}. Content: {tool_content}")
            content_str = json.dumps({"error": "Failed to serialize tool result.", "original_content": str(tool_content)})

        result_data = {
            "tool_call_id": tool_call_id,
            "role": "tool",
            "name": function_name,
            "content": content_str, # MUST be a string for the API history
        }
        tool_results.append(result_data)
        print_tool_result(tool_call_id, function_name, result_data["content"])

    history.extend(tool_results)
    return True # Signal that another API call is needed to process the tool results.

# --- Main Execution Modes ---
def create_system_prompt(task_description: str) -> Dict[str, str]:
    tool_names = ', '.join(agent_tools.TOOL_EXECUTORS.keys())
    return {
        "role": "system",
        "content": (
            f"You are a helpful coding assistant running in a CLI environment on {get_current_os_info()}, {task_description}. "
            f"Current date/time: {get_current_datetime()}. " # Added datetime
            f"Available tools: {tool_names}. "
            f"Use tools precisely. Adhere to OS-specific commands ('{ 'cmd.exe' if platform.system() == 'Windows' else 'sh/bash' }' syntax). "
            f"Requires user approval for potentially dangerous actions (e.g., file system changes, code/shell execution, web access). "
            f"Be clear about required approvals."
        ),
    }

def run_loop(client: openai.OpenAI, model: str, history: List[Dict[str, Any]], temperature: float, top_p: float):
    """Handles the main loop of API calls and response processing."""
    needs_another_call = True
    while needs_another_call:
        print(f"\n{CTOOL_RESULT}Waiting for assistant...{CRESET}")
        response = call_api(client, model, history, temperature, top_p)
        if response:
            needs_another_call = process_api_response(history, response)
        else:
            print_error("API call failed. Cannot continue this turn.")
            needs_another_call = False

def run_interactive(client: openai.OpenAI, model: str, temperature: float, top_p: float):
    """Runs the agent in interactive mode."""
    print(f"Starting interactive session (Model: {model}, Temp: {temperature}, Top-P: {top_p}, OS: {get_current_os_info()})")
    print("Type 'quit' or 'exit' to end.")
    print_warning("Review ALL actions requiring approval VERY carefully, especially code/shell execution.")
    if platform.system() == "Windows":
        print_warning("Ensure requested shell commands use cmd.exe syntax (e.g., 'dir', 'copy').")
    history = [create_system_prompt("ready for interactive user requests")]

    while True:
        try:
            user_input = input(f"\n{CUSER}User:{CRESET}\n").strip()
            if user_input.lower() in ['quit', 'exit']: break
            if not user_input: continue # Skip empty input
            history.append({"role": "user", "content": user_input})
            run_loop(client, model, history, temperature, top_p)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

def run_single_pass(client: openai.OpenAI, model: str, initial_prompt: str, temperature: float, top_p: float):
    """Runs the agent for a single task."""
    print(f"Running single prompt (Model: {model}, Temp: {temperature}, Top-P: {top_p}, OS: {get_current_os_info()})")
    print_warning("Review ALL actions requiring approval VERY carefully, especially code/shell execution.")
    if platform.system() == "Windows":
        print_warning("Ensure requested shell commands use cmd.exe syntax.")
    history = [
        create_system_prompt("executing a single task given by the user"),
        {"role": "user", "content": initial_prompt}
    ]
    run_loop(client, model, history, temperature, top_p)
    print("\nTask finished.")

# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(
        description="Python CLI agent interacting with OpenAI-compatible APIs using tools.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("prompt", nargs="?", help="Initial prompt. If omitted, enters interactive mode.")
    parser.add_argument("-k", "--api-key", default=os.getenv(ENV_API_KEY), help=f"API key (or use ${ENV_API_KEY}). REQUIRED.")
    parser.add_argument("-b", "--base-url", default=os.getenv(ENV_BASE_URL), help=f"API base URL (for non-OpenAI providers, or use ${ENV_BASE_URL}). Optional.")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Model name.")
    parser.add_argument("-t", "--temperature", type=float, default=DEFAULT_TEMPERATURE, help="Sampling temperature (e.g., 0.6).")
    parser.add_argument("-p", "--top-p", type=float, default=DEFAULT_TOP_P, help="Nucleus sampling 'top_p' (e.g., 0.9).")
    args = parser.parse_args()

    if not args.api_key:
        print_error(f"API key required via --api-key or environment variable ${ENV_API_KEY}.")
        sys.exit(1)

    try:
        client_options = {"api_key": args.api_key}
        if args.base_url:
            client_options["base_url"] = args.base_url
        client = openai.OpenAI(**client_options) # type: ignore
    except Exception as e:
        print_error(f"Failed to initialize OpenAI client: {e}")
        sys.exit(1)

    if args.prompt:
        run_single_pass(client, args.model, args.prompt, args.temperature, args.top_p)
    else:
        run_interactive(client, args.model, args.temperature, args.top_p)

if __name__ == "__main__":
    main()