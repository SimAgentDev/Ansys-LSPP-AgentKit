# utils.py

import os
import re
import shutil
import subprocess
import time
import sys

# --- ANSI Color Code Definitions ---
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"

# --- Hardcoded Partial Colors (for console output, actual config values should not contain them) ---
# Note: The HARDCODED_COLOR variable below is only used to color-mark config values during printing.
# Actual values in LSPREPOST_EXE_PATH and LLM_CONFIGS will be pure strings, without color codes.
HARDCODED_COLOR = f"{BOLD}{YELLOW}" # Color tag used internally to mark hardcoded values

# --- LS-PrePost Configuration ---
# !!! Be sure to modify this to the actual path of your LS-PrePost executable !!!
# LSPREPOST_EXE_PATH is a hardcoded configuration
LSPREPOST_EXE_PATH = r"Please modify it to your LS-PrePost executable path, for example: D:\LS-PrePost 4.6\lsprepost4.6_x64.exe"
GENERAL_COORD_TOLERANCE = 0.1 # Fixed value

# --- LLM Model Configuration (Consistent with configuration in llm_interaction.py, color markers removed) ---
LLM_CONFIGS = {
    # Default Model (DeepSeek-V3)
    "Pro/deepseek-ai/DeepSeek-V3": {
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_token": "Please modify it to your SiliconFlow API key", # Replace with your SiliconFlow API key
        "model": "Pro/deepseek-ai/DeepSeek-V3",
        "temperature": 0.2,
        "max_tokens": 1500,
        "top_p": 0.7
    },
    # OpenAI Model
    "gpt-3.5-turbo": {
        "api_url": "https://api.openai.com/v1/chat/completions",
        "api_token": "Please modify it to your OpenAI API key",  # Replace with your OpenAI API key
        "model": "gpt-3.5-turbo",
        "temperature": 0.7,
        "max_tokens": 512,
        "top_p": 0.7
    },
    # More SiliconFlow Models
    "Qwen/Qwen3-Next-80B-A3B-Instruct": {
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_token": "Please modify it to your SiliconFlow API key", # Replace with your SiliconFlow API key
        "model": "Qwen/Qwen3-Next-80B-A3B-Instruct",
        "temperature": 0.7,
        "max_tokens": 512,
        "top_p": 0.7
    },
    "THUDM/GLM-4-9B-0414": {
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_token": "Please modify it to your SiliconFlow API key", # Replace with your SiliconFlow API key
        "model": "THUDM/GLM-4-9B-0414",
        "temperature": 0.7,
        "max_tokens": 512,
        "top_p": 0.7
    },
    "deepseek-ai/DeepSeek-V3.2": {
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_token": "Please modify it to your SiliconFlow API key", # Replace with your SiliconFlow API key
        "model": "deepseek-ai/DeepSeek-V3.2",   
        "temperature": 0.7,
        "max_tokens": 512,
        "top_p": 0.7
    },
    # Newly added Together Models
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": {
        "api_token": "Please modify it to your Together API key", # Replace with your Together API key
        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "temperature": 0.7,
        "max_tokens": 512,
        "top_p": 0.7
    },
    "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": {
        "api_token": "Please modify it to your Together API key", # Replace with your Together API key
        "model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "temperature": 0.7,
        "max_tokens": 512,
        "top_p": 0.7
    },
    "meta-llama/Meta-Llama-3-8B-Instruct-Lite": {
        "api_token": "Please modify it to your Together API key", # Replace with your Together API key
        "model": "meta-llama/Meta-Llama-3-8B-Instruct-Lite",
        "temperature": 0.7,
        "max_tokens": 512,
        "top_p": 0.7
    },
}

# To address the issue where sys.stdout.reconfigure is unavailable in some environments
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass


# --- Helper Functions ---
def get_float_input(prompt, default_val=None):
    """Helper function: Robust float input"""
    while True:
        user_input = input(prompt).strip()
        if user_input == "":
            if default_val is not None:
                return default_val
            else:
                print("Input cannot be empty. Please provide a value.")
                continue
        try:
            return float(user_input)
        except ValueError:
            print("Invalid input. Please enter a number (e.g., '0.0', '10.5').")

def get_string_input(prompt, default_val=None):
    """Helper function: Robust string input"""
    while True:
        user_input = input(prompt).strip()
        if user_input == "":
            if default_val is not None:
                return default_val
            else:
                print("Input cannot be empty. Please provide a value.")
                continue
        return user_input

def _write_k_file_from_lines(k_file_path_to_write, lines):
    """Helper function: Write a list of lines to a K file."""
    try:
        output_dir = os.path.dirname(k_file_path_to_write)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(k_file_path_to_write, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return True, f"Successfully updated and saved as '{k_file_path_to_write}'."
    except Exception as e:
        return False, f"Error occurred while writing new file: {e}"
    
def prompt_yes_no(prompt_message):
    """Ask the user a question and get a yes/no answer"""
    while True:
        choice = input(f"LLM-Assistant: {prompt_message} (y/n): ").strip().lower()
        if choice in ['y', 'yes', '是']:
            return True
        elif choice in ['n', 'no', '否']:
            return False
        else:
            print("Invalid input, please enter 'y' or 'n'.")

def try_float(value):
    """Attempt to convert string to float, return None if failed."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def set_coord_range(params, coord_char, min_val, max_val, general_coord_tolerance=GENERAL_COORD_TOLERANCE):
    """
    Update the range of the specified coordinate, considering existing range and taking intersection.
    Treat None as infinite.
    Args:
        params (dict): Dictionary containing 'x_range', 'y_range', 'z_range' keys.
        coord_char (str): Coordinate axis character ('x', 'y', 'z').
        min_val: New minimum value, can be None or a number.
        max_val: New maximum value, can be None or a number.
        general_coord_tolerance (float): Coordinate tolerance used for exact value matching.
    """
    # Ensure passed min_val and max_val are already float or None
    min_val_safe = try_float(min_val) if isinstance(min_val, str) else min_val
    max_val_safe = try_float(max_val) if isinstance(max_val, str) else max_val

    # Get current range values, treat None as infinite
    current_min = params[f'{coord_char}_range'][0] if params[f'{coord_char}_range'][0] is not None else -float('inf')
    current_max = params[f'{coord_char}_range'][1] if params[f'{coord_char}_range'][1] is not None else float('inf')

    # Calculate new min and max values
    # If exact value specified, use tolerance
    if min_val_safe is not None and max_val_safe is not None and abs(min_val_safe - max_val_safe) < 1e-6: # Check if it is an approximate exact value
        new_min = max(current_min, min_val_safe - general_coord_tolerance)
        new_max = min(current_max, max_val_safe + general_coord_tolerance)
    else:
        new_min = max(current_min, min_val_safe if min_val_safe is not None else current_min)
        new_max = min(current_max, max_val_safe if max_val_safe is not None else float('inf'))
    
    # Convert -inf and inf back to None to maintain consistency
    params[f'{coord_char}_range'][0] = new_min if new_min != -float('inf') else None
    params[f'{coord_char}_range'][1] = new_max if new_max != float('inf') else None


def parse_node_criteria_input(user_input, general_coord_tolerance=GENERAL_COORD_TOLERANCE):
    """
    Parse user input search criteria string.
    This function is now mainly used for debugging or as a fallback when the LLM fails.
    Returns a dictionary containing parameters required for find_nodes.find_nodes_by_criteria.
    If user inputs 'help', prints help information and returns None.
    """
    params = {
        'criteria_type': 'coord_range', # Default use range search
        'x_range': [None, None], 
        'y_range': [None, None],
        'z_range': [None, None]
    }
    
    # Unify input processing, remove extra spaces and convert to lower case
    processed_input = ' '.join(user_input.lower().replace(',', ' ').split())
    
    if "min_y" in processed_input.split():
        params['criteria_type'] = 'min_y'
        print(f"{CYAN}Info: 'min_y' is an independent search mode; if specified, other coordinate range conditions will be ignored.{RESET}")
        return params

    if "help" in processed_input.split():
        print(f"\n{BLUE}--- Search Criteria Examples (Flexible Expression) ---{RESET}")
        print(f"  - Find node with minimum Y coordinate: {GREEN}min_y{RESET}")
        print(f"  - Exact value: {GREEN}x=100, y=50, z=0{RESET}")
        print(f"  - Inequality: {GREEN}x<100, y>50, z<=20, x>=10{RESET}")
        print(f"  - Range (English keywords):")
        print(f"      - {GREEN}x in 10-20{RESET}")
        print(f"      - {GREEN}y from 50 to 100{RESET}")
        print(f"      - {GREEN}z between 0 and 15{RESET}")
        print(f"      - {GREEN}x range 10 20{RESET}")
        print(f"  - Range (Concise numbers): {GREEN}x 10 20{RESET} (Means x coordinate between 10 and 20)")
        print(f"  - Range (Chinese keywords):")
        print(f"      - {GREEN}x 在 10 到 20 之间{RESET}")
        print(f"      - {GREEN}y 从 50 到 100{RESET}")
        print(f"  - Combined conditions (space or comma separated): {GREEN}z=0 x from 10 to 20 y>5{RESET}")
        print(f"  - Note: 'min_y' is a special mode; if specified, other coordinate conditions will be ignored.")
        print(f"{BLUE}---{RESET}")
        return None 
    
    patterns = [
        # 1. Coordinate Exact Value/Inequality: x=100, y<50, z>=0
        # Matches `x=100` or `y<50` or `z>=0`
        (r'([xyz])\s*([<>=]{1,2})\s*([-+]?\d*\.?\d*(?:[eE][+-]?\d*)?)', 
         lambda m: {
             'coord': m.group(1),
             'op': m.group(2),
             'val': try_float(m.group(3)) # Convert to float directly here
         }),
        
        # 2. Coordinate from/between ... to/and ... range
        # Matches `x from 10 to 20` or `z 在 0 到 15 之间` (supports Chinese keywords)
        (r'([xyz])\s*(?:from|between|在|从)\s*([-+]?\d*\.?\d*(?:[eE][-+]?\d*)?)\s*(?:to|and|到|之间)\s*([-+]?\d*\.?\d*(?:[eE][-+]?\d*)?)(?:\s*之间)?', 
         lambda m: {
             'coord': m.group(1),
             'min_val': try_float(m.group(2)),
             'max_val': try_float(m.group(3))
         }),

        # 3. Coordinate in/range hyphenated range
        # Matches `x in 10-20`
        (r'([xyz])\s*(?:in|range)\s*([-+]?\d*\.?\d*(?:[eE][-+]?\d*)?)-([-+]?\d*\.?\d*(?:[eE][-+]?\d*)?)', 
         lambda m: {
             'coord': m.group(1),
             'min_val': try_float(m.group(2)),
             'max_val': try_float(m.group(3))
         }),
        
        # 4. Coordinate Concise number range (Note: this pattern conflicts easily, placed last)
        # Matches `x 10 20`
        (r'([xyz])\s*([-+]?\d*\.?\d*(?:[eE][+-]?\d*)?)\s*([-+]?\d*\.?\d*(?:[eE][-+]?\d*)?)', 
         lambda m: {
             'coord': m.group(1),
             'min_val': try_float(m.group(2)),
             'max_val': try_float(m.group(3))
         }),
    ]

    remaining_input = processed_input
    
    while True:
        matched_in_this_iteration = False
        for pattern_regex, extract_func in patterns:
            match = re.search(pattern_regex, remaining_input)
            
            if match:
                parsed_data = extract_func(match)
                coord_char = parsed_data['coord']
                
                if 'op' in parsed_data: # Exact value/Inequality mode
                    operator = parsed_data['op']
                    value = parsed_data['val']
                    
                    if value is not None:
                        if operator == '=':
                            set_coord_range(params, coord_char, value, value, general_coord_tolerance)
                        elif operator == '<':
                            set_coord_range(params, coord_char, None, value, general_coord_tolerance)
                        elif operator == '>':
                            set_coord_range(params, coord_char, value, None, general_coord_tolerance)
                        elif operator == '<=':
                            set_coord_range(params, coord_char, None, value, general_coord_tolerance)
                        elif operator == '>=':
                            set_coord_range(params, coord_char, value, None, general_coord_tolerance)
                    else:
                        print(f"{YELLOW}Warning: Could not extract valid number from '{match.group(0)}'.{RESET}")
                else: # Range mode
                    min_val = parsed_data['min_val']
                    max_val = parsed_data['max_val']
                    
                    # Prioritize cases where both are provided
                    if min_val is not None and max_val is not None:
                        set_coord_range(params, coord_char, min(min_val, max_val), max(min_val, max_val), general_coord_tolerance)
                    # If only first value provided and second is None, treat as open range
                    elif min_val is not None and max_val is None:
                        set_coord_range(params, coord_char, min_val, None, general_coord_tolerance) # From min_val to positive infinity
                    # If only second value provided and first is None, treat as open range
                    elif max_val is not None and min_val is None:
                        set_coord_range(params, coord_char, None, max_val, general_coord_tolerance) # From negative infinity to max_val
                    else:
                        print(f"{YELLOW}Warning: Could not extract valid number range from '{match.group(0)}'.{RESET}")
                
                # Remove matched part from remaining_input
                remaining_input = remaining_input[:match.start()] + ' ' * (match.end() - match.start()) + remaining_input[match.end():]
                remaining_input = ' '.join(remaining_input.split()) # Clean up extra spaces after removal
                
                matched_in_this_iteration = True
                break # Break and restart loop after finding a match to avoid overlap issues
        
        if not matched_in_this_iteration: # Exit loop if no matches found in this round
            break
    
    if remaining_input.strip():
        print(f"{YELLOW}Warning: Unrecognized condition part: '{remaining_input.strip()}'. Please check input format.{RESET}")

    # ly ensure values in range tuples are float or None
    params['x_range'] = tuple(params['x_range'])
    params['y_range'] = tuple(params['y_range'])
    params['z_range'] = tuple(params['z_range'])
    
    return params


def get_float_input(prompt, default_val=None):
    """Helper function: Robust float input"""
    while True:
        user_input = input(f"LLM-Assistant: {WHITE}{prompt}{RESET}").strip()
        if user_input == "":
            if default_val is not None:
                return default_val
            else:
                print(f"{RED}Input cannot be empty. Please provide a value.{RESET}")
                continue
        try:
            return float(user_input)
        except ValueError:
            print(f"{RED}Invalid input. Please enter a number (e.g., '0.0', '10.5').{RESET}")

def get_int_input(prompt, default_val=None):
    """Helper function: Robust integer input"""
    while True:
        user_input = input(f"LLM-Assistant: {WHITE}{prompt}{RESET}").strip()
        if user_input == "":
            if default_val is not None:
                return default_val
            else:
                print(f"{RED}Input cannot be empty. Please provide an integer.{RESET}")
                continue
        try:
            return int(user_input)
        except ValueError:
            print(f"{RED}Invalid input. Please enter an integer (e.g., '1', '100').{RESET}")

def get_string_input(prompt, default_val=None):
    """Helper function: Robust string input"""
    while True:
        user_input = input(f"LLM-Assistant: {WHITE}{prompt}{RESET}").strip()
        if user_input == "":
            if default_val is not None:
                return default_val
            else:
                print(f"{RED}Input cannot be empty. Please provide a value.{RESET}")
                continue
        return user_input

def prompt_yes_no(prompt_message):
    """Ask the user a question and get a yes/no answer"""
    while True:
        choice = input(f"{WHITE}LLM-Assistant: {prompt_message} (y/n): {RESET}").strip().lower()
        if choice in ['y', 'yes', '是']:
            return True
        elif choice in ['n', 'no', '否']:
            return False
        else:
            print(f"{RED}Invalid input, please enter 'y' or 'n'.{RESET}")

def _write_k_file_from_lines(k_file_path_to_write, lines):
    """Helper function: Write a list of lines to a K file."""
    try:
        output_dir = os.path.dirname(k_file_path_to_write)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(k_file_path_to_write, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return True, f"Successfully updated and saved as '{k_file_path_to_write}'."
    except Exception as e:
        return False, f"Error occurred while writing new file: {e}"

def run_lsprepost_command(lsprepost_path, command_string, process_shell=True):
    """
    Run LS-PrePost command.
    
    Args:
        lsprepost_path (str): Path to LS-PrePost executable.
        command_string (str): Command line arguments to pass to LS-PrePost (e.g., "c=path/to/cfile.cfile").
        process_shell (bool): Whether to use shell to execute the command.
    Returns:
        bool: Whether the command started successfully.
    """
    cmd = f'"{lsprepost_path}" {command_string}'
    print(f"\n{BLUE}Calling LS-PrePost to execute command stream...\n{CYAN}{cmd}{RESET}")
    try:
        subprocess.Popen(cmd, shell=process_shell) 
        print(f"{GREEN}✓ LS-PrePost started successfully.{RESET}")
        time.sleep(2) # Give LS-PrePost some time to start
        return True
    except Exception as e:
        print(f"{RED}❌ LS-PrePost failed to start, please check path and cfile content. Error: {e}{RESET}")
        return False

def run_lsprepost_command(lsprepost_path, command_string, process_shell=True):
    """
    Run LS-PrePost command.
    
    Args:
        lsprepost_path (str): Path to LS-PrePost executable.
        command_string (str): Command line arguments to pass to LS-PrePost (e.g., "c=path/to/cfile.cfile").
        process_shell (bool): Whether to use shell to execute the command.
    Returns:
        bool: Whether the command started successfully.
    """
    cmd = f'"{lsprepost_path}" {command_string}'
    print(f"\nCalling LS-PrePost to execute command stream...\n{cmd}")
    try:
        subprocess.Popen(cmd, shell=process_shell) 
        print("✓ LS-PrePost started successfully.")
        time.sleep(2) # Give LS-PrePost some time to start
        return True
    except Exception as e:
        print(f"❌ LS-PrePost failed to start, please check path and cfile content. Error: {e}")
        return False
