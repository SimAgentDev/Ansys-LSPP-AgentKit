# tool.py
# Implements specific operations callable by the LLM, representing the Agent's "actions".
# Includes K-file parsing, node lookup, CFILE generation & modification, LS-PrePost interaction, etc.

import os
import sys
import re
import subprocess
import time
import json
import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.decomposition import PCA
import joblib

# Import helper functions and constants from utils, ensuring single import and latest version
from utils import (
    LSPREPOST_EXE_PATH, get_float_input, get_string_input, _write_k_file_from_lines, prompt_yes_no, run_lsprepost_command, try_float, set_coord_range, LSPREPOST_EXE_PATH, GENERAL_COORD_TOLERANCE,
    RESET, BOLD, RED, YELLOW, BLUE, MAGENTA, CYAN, WHITE, HARDCODED_COLOR
)


# --- Helper Function: Parse Node Data from K-File (Merged, Boundary Condition Version) ---
def parse_k_file(k_filepath, gui_log_func=None): # <--- IMPORTANT: Add gui_log_func parameter
    """
    A more robust example function for parsing the *NODE section in LS-DYNA K-files.
    ...
    """
    # Helper log function, fallback to stderr if gui_log_func is not provided
    _log = gui_log_func if gui_log_func else (lambda msg, level="info": print(f"[{level.upper()}] {msg}", file=sys.stderr))

    nodes_data = {}
    in_node_section = False

    NID_START, NID_END = 0, 8
    X_START, X_END = 8, 24
    Y_START, Y_END = 24, 40
    Z_START, Z_END = 40, 56

    try:
        with open(k_filepath, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.rstrip('\n\r')
                line_stripped = line.strip()

                if not in_node_section:
                    if line_stripped.upper().startswith('*NODE'):
                        in_node_section = True
                        continue
                    elif line_stripped.upper().startswith('*END'):
                        break
                    elif line_stripped.startswith('$#') or not line_stripped:
                        continue
                    else:
                        continue

                if in_node_section:
                    if line_stripped.upper().startswith('*END'):
                        break

                    if line_stripped.startswith('$'):
                        continue

                    if line_stripped.startswith('*') and not line_stripped.upper().startswith('*NODE'):
                        break

                    try:
                        nid_str = line_stripped[NID_START:NID_END].strip()
                        x_str = line_stripped[X_START:X_END].strip()
                        y_str = line_stripped[Y_START:Y_END].strip()
                        z_str = line_stripped[Z_START:Z_END].strip()

                        nid, x, y, z = None, None, None, None

                        if nid_str:
                            try:
                                nid = int(nid_str)
                            except ValueError:
                                parts = line_stripped.split()
                                if parts:
                                    try:
                                        nid = int(parts[0])
                                    except ValueError:
                                        _log(f"{YELLOW}WARNING: Unable to parse NID on node line {line_num}: '{line_stripped}'. Skipping this line.", level="warning") # <--- FIX: Use _log
                                        continue
                                else:
                                    _log(f"{YELLOW}WARNING: Node line {line_num} is empty. Skipping this line.", level="warning") # <--- FIX: Use _log
                                    continue
                        else:
                            continue

                        if len(line_stripped) >= Z_END and x_str and y_str and z_str:
                            try:
                                x = float(x_str)
                                y = float(y_str)
                                z = float(z_str)
                            except ValueError:
                                parts = line_stripped.split()
                                if len(parts) >= 4:
                                    try:
                                        x = float(parts[1])
                                        y = float(parts[2])
                                        z = float(parts[3])
                                    except ValueError:
                                        _log(f"{YELLOW}WARNING: Unable to parse coordinates on node line {line_num} (both fixed width and split failed): '{line_stripped}'. Skipping this line.", level="warning") # <--- FIX: Use _log
                                        continue
                                else:
                                    _log(f"{YELLOW}WARNING: Node line {line_num} format unexpected (too few fields): '{line_stripped}'. Skipping this line.", level="warning") # <--- FIX: Use _log
                                    continue
                        else:
                            parts = line_stripped.split()
                            if len(parts) >= 4:
                                try:
                                    x = float(parts[1])
                                    y = float(parts[2])
                                    z = float(parts[3])
                                except ValueError:
                                    _log(f"{YELLOW}WARNING: Unable to parse coordinates on node line {line_num} (split failed): '{line_stripped}'. Skipping this line.", level="warning") # <--- FIX: Use _log
                                    continue
                            else:
                                _log(f"{YELLOW}WARNING: Node line {line_num} format unexpected (too few fields): '{line_stripped}'. Skipping this line.", level="warning") # <--- FIX: Use _log
                                continue


                        if nid is not None and x is not None and y is not None and z is not None:
                            nodes_data[nid] = [x, y, z]
                        else:
                            _log(f"{YELLOW}WARNING: Node line {line_num} data incomplete or missing: '{line_stripped}'. Skipping this line.", level="warning") # <--- FIX: Use _log
                            pass
                    except (ValueError, IndexError) as e:
                        _log(f"{YELLOW}WARNING: General error parsing node line {line_num}: '{line_stripped}'. Error: {e}. Skipping this line.", level="warning") # <--- FIX: Use _log
                        continue

    except FileNotFoundError:
        _log(f"{RED}ERROR: File {CYAN}'{k_filepath}'{RESET}{RED} not found.", level="error") # <--- FIX: Use _log
        return {}
    except Exception as e:
        _log(f"{RED}Unknown error occurred while parsing K-file: {e}{RESET}", level="error") # <--- FIX: Use _log
        return {}

    return nodes_data


# --- Tool Function Implementations ---

def find_specific_corner_node(k_filepath, tolerance=0.1):
    """
    Reads LS-DYNA K-file (or solid_nodes.txt) and finds a single node satisfying these conditions (within tolerance):
    - Overall minimum Z coordinate of the model.
    - Overall minimum X coordinate of the model.
    - Overall maximum Y coordinate of the model.

    Args:
        k_filepath (str): Path to the *TXT file containing node data* (e.g., solid_nodes.txt).
        tolerance (float): Tolerance value for float comparison. Default is 0.1.

    Returns:
        tuple: (dict or None, dict or None, str) -
               - Found corner node info (id, x, y, z)
               - Global extremum info (min_x, max_x, min_y, max_y, min_z, max_z)
               - Information message
               Returns (None, None, error message) if file doesn't exist or cannot be parsed.
    """
    print(f"\n{BOLD}--- Finding Specific Corner Node (File: {CYAN}'{k_filepath}'{RESET}{BOLD}) ---{RESET}")

    nodes_data = parse_k_file(k_filepath)
    if not nodes_data:
        msg = f"{RED}No nodes found in file or parsing failed.{RESET}"
        print(msg)
        return None, None, msg

    overall_min_z = float('inf')
    overall_max_z = float('-inf')
    overall_min_x = float('inf')
    overall_max_x = float('-inf')
    overall_min_y = float('inf')
    overall_max_y = float('-inf')

    parsed_nodes_list = [{'id': nid, 'x': coords[0], 'y': coords[1], 'z': coords[2]} for nid, coords in nodes_data.items()]

    print(f"  {BLUE}Phase 1: Finding global min/max coordinates from {len(parsed_nodes_list)} parsed nodes...{RESET}")
    for node in parsed_nodes_list:
        if node['z'] < overall_min_z: overall_min_z = node['z']
        if node['z'] > overall_max_z: overall_max_z = node['z']
        if node['x'] < overall_min_x: overall_min_x = node['x']
        if node['x'] > overall_max_x: overall_max_x = node['x']
        if node['y'] < overall_min_y: overall_min_y = node['y']
        if node['y'] > overall_max_y: overall_max_y = node['y']

    global_extremums = {
        'min_x': overall_min_x, 'max_x': overall_max_x,
        'min_y': overall_min_y, 'max_y': overall_max_y,
        'min_z': overall_min_z, 'max_z': overall_max_z
    }

    print(f"\n{BLUE}Global Extremums Found:{RESET}")
    print(f"  {HARDCODED_COLOR}Overall X coordinate range: [{overall_min_x:.6f}, {overall_max_x:.6f}]{RESET}")
    print(f"  {HARDCODED_COLOR}Overall Y coordinate range: [{overall_min_y:.6f}, {overall_max_y:.6f}]{RESET}")
    print(f"  {HARDCODED_COLOR}Overall Z coordinate range: [{overall_min_z:.6f}, {overall_max_z:.6f}]{RESET}")

    print(f"\n{BLUE}Phase 2: Searching for nodes matching these coordinates (tolerance ±{tolerance:.6f})...{RESET}")

    candidate_nodes = []
    for node_info in parsed_nodes_list:
        if (abs(node_info['x'] - overall_min_x) <= tolerance and
            abs(node_info['y'] - overall_max_y) <= tolerance and
            abs(node_info['z'] - overall_min_z) <= tolerance):
            candidate_nodes.append(node_info)

    if len(candidate_nodes) == 1:
        found_corner_node = candidate_nodes[0]
        info_msg = f"{BLUE}Successfully found a unique corner node: ID {found_corner_node['id']} at ({found_corner_node['x']:.6f}, {found_corner_node['y']:.6f}, {found_corner_node['z']:.6f}){RESET}"
        print(info_msg)
        return found_corner_node, global_extremums, info_msg
    elif len(candidate_nodes) > 1:
        found_corner_node = candidate_nodes[0]
        info_msg = f"{YELLOW}WARNING: Found {len(candidate_nodes)} matching nodes. Will use the first one found (ID {found_corner_node['id']}).{RESET}"
        print(info_msg)
        return found_corner_node, global_extremums, info_msg
    else:
        info_msg = f"{YELLOW}No corner node found satisfying all conditions. However, global extremums retrieved.{RESET}"
        print(info_msg)
        return None, global_extremums, info_msg


def create_cfile_from_template(cfile_template_path, output_cfile_path, k_filepath_to_open, final_save_k_path,
                               translate_x=None, translate_y=None, translate_z=None):
    """
    Generates CFILE from template, replacing placeholders and optional translation commands.
    This version assumes rotation commands are hardcoded in the template.
    """
    try:
        with open(cfile_template_path, 'r', encoding='utf-8') as f:
            content = f.read()

        print(f"{BLUE}Reading CFILE template: {CYAN}'{cfile_template_path}'{RESET}")

        original_k_filepath_lsprepost_format = k_filepath_to_open.replace('\\', '/')
        content = content.replace("KEYWORD_FILE_PATH_PLACEHOLDER", original_k_filepath_lsprepost_format)
        print(f"  {BLUE}- Replaced 'KEYWORD_FILE_PATH_PLACEHOLDER' -> {CYAN}'{original_k_filepath_lsprepost_format}'{RESET}")

        final_save_k_filepath_lsprepost_format = final_save_k_path.replace('\\', '/')
        save_keyword_pattern = r'^\s*save\s+keyword.*$'

        if "FINAL_SAVE_K_PATH_PLACEHOLDER" in content:
            content = content.replace("FINAL_SAVE_K_PATH_PLACEHOLDER", final_save_k_filepath_lsprepost_format)
            print(f"  {BLUE}- Replaced 'FINAL_SAVE_K_PATH_PLACEHOLDER' -> {CYAN}'{final_save_k_filepath_lsprepost_format}'{RESET}")
        elif re.search(save_keyword_pattern, content, re.IGNORECASE | re.MULTILINE):
            if not re.search(r'^\s*save\s+keyword(absolute|bylongfmt|byi10fmt|outversion)\s+.*$', content, re.IGNORECASE | re.MULTILINE):
                content = re.sub(save_keyword_pattern, f"save keyword \"{final_save_k_filepath_lsprepost_format}\"", content, flags=re.IGNORECASE | re.MULTILINE)
                print(f"  {BLUE}- Replaced 'save keyword' command -> 'save keyword {CYAN}\"{final_save_k_filepath_lsprepost_format}\"{RESET}{BLUE}'{RESET}")
            else:
                print(f"  {YELLOW}- WARNING: Template already contains a specific 'save keyword' command or placeholder, generic 'save keyword' replacement skipped.{RESET}")
        else:
            print(f"  {YELLOW}- WARNING: 'save keyword' or its placeholder not found in template for automatic path replacement. Please ensure the template contains this line or placeholder!{RESET}")

        if all(v is not None for v in [translate_x, translate_y, translate_z]):
            translate_command = f"translate_model {translate_x:.6f} {translate_y:.6f} {translate_z:.6f}"
            content, count = re.subn(r'^\s*translate_model\s+.*$', translate_command, content, flags=re.IGNORECASE | re.MULTILINE)
            if count > 0:
                print(f"  {BLUE}- Replaced 'translate_model' command -> '{translate_command}'{RESET}")
            else:
                print(f"  {YELLOW}- WARNING: 'translate_model' command or placeholder not found in template for replacement.{RESET}")
        else: # If no translation parameters provided, remove translate_model line from template
            content = re.sub(r'^\s*translate_model\s+.*$', '', content, flags=re.IGNORECASE | re.MULTILINE)

        rotate_matches = re.findall(r'^\s*rotate_model\s+.*$', content, re.IGNORECASE | re.MULTILINE)
        if rotate_matches:
            print(f"  {BLUE}- Template already contains preset rotation commands: {'; '.join(m.strip() for m in rotate_matches)}{RESET}")
        else:
            print(f"  {YELLOW}- WARNING: 'rotate_model' command not found in template. Please ensure the template contains the desired rotation instructions.{RESET}")


        with open(output_cfile_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, f"{BLUE}Successfully generated CFILE from template: {CYAN}'{output_cfile_path}'{RESET}"

    except Exception as e:
        return False, f"{RED}Error generating or writing CFILE: {e}{RESET}"


def apply_cfile_with_lsprepost(lsprepost_exe_path, cfile_to_apply, final_save_k_path, keep_open=True):
    """
    Executes the specified CFILE using LS-PrePost.
    :param lsprepost_exe_path: Path to LS-PrePost executable
    :param cfile_to_apply: Path to the CFILE to execute
    :param final_save_k_path: Path where K-file should be saved after LS-PrePost operation. If provided, used for mode hint.
    :param keep_open: If True, LS-PrePost window remains open after execution; otherwise closes automatically.
    :return: True and final K-file path on success, False and error message on failure.
    """
    if not os.path.exists(lsprepost_exe_path):
        return False, f"{RED}ERROR: LS-PrePost executable not found at path '{lsprepost_exe_path}'{RESET}"
    if not os.path.exists(cfile_to_apply):
        return False, f"{RED}ERROR: CFILE not found at path '{cfile_to_apply}'{RESET}"

    mode_str = "Keep Open" if keep_open else "Auto Execute and Close"
    print(f"\n{BOLD}Calling LS-PrePost, please wait...{RESET}")
    command = [lsprepost_exe_path, "-c", cfile_to_apply]

    print(f"  {BLUE}Executing command: {' '.join(command)}{RESET}")
    print(f"  {BLUE}Mode: {mode_str}. Sending instructions and {'waiting for result' if not keep_open else 'detaching process'}...{RESET}")

    try:
        if keep_open:
            subprocess.Popen(command)
            print(f"  {BLUE}LS-PrePost launched in background. Please check its window and operate manually or wait for it to finish.{RESET}")
            print(f"  {BLUE}Expected save path (if CFILE contains save instructions): {CYAN}'{final_save_k_path}'{RESET}")
            time.sleep(5) # Give LS-PrePost some time to start and process
            return True, f"{BLUE}LS-PrePost launched and executing CFILE {CYAN}'{cfile_to_apply}'{RESET}{BLUE}. You can close it manually to continue the Python script.{RESET}"
        else:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            if result.returncode == 0:
                print(f"  {BLUE}CFILE {CYAN}'{cfile_to_apply}'{BLUE} successfully executed and LS-PrePost closed automatically.{RESET}")
                print(f"  {BLUE}Resulting K-file should be saved to: {CYAN}'{final_save_k_path}'{RESET}")
                return True, final_save_k_path
            else:
                return False, f"{RED}LS-PrePost execution of CFILE failed, return code: {result.returncode}\nStdout: {result.stdout}\nStderr: {result.stderr}{RESET}"
    except subprocess.CalledProcessError as e:
        return False, f"{RED}LS-PrePost execution of CFILE failed: {e}\nStdout: {e.stdout}\nStderr: {e.stderr}{RESET}"
    except Exception as e:
        return False, f"{RED}Unknown error occurred while calling LS-PrePost: {e}{RESET}"


def create_translation_cfile_from_corner_node(lsprepost_exe_path, k_filepath, cfile_template_path, output_cfile_path, final_save_k_path, tolerance=0.1, nodes_source_filepath=None):
    """
    A complete workflow: Find corner, calculate translation vector, and generate modified CFILE.
    This is the tool function exposed to the Large Model.
    This function has been modified: even if a specific "corner node" is not found, as long as global extremums are obtained, they will be used for translation.
    """
    print(f"\n{BOLD}--- Executing Model Translation to Origin ---{RESET}")

    print(f"  {BLUE}Step 0: Extracting solid element nodes from original K-file {CYAN}'{k_filepath}'{BLUE} to {CYAN}'{nodes_source_filepath}'{RESET}{BLUE}...{RESET}")
    extract_success, extract_message = extract_solid_element_nodes_and_save_node_data(k_filepath, nodes_source_filepath)
    if not extract_success:
        final_return_message = f"{RED}Operation aborted: Unable to extract solid element nodes from {CYAN}'{k_filepath}'{RED}: {extract_message}{RESET}"
        print(final_return_message)
        return False, final_return_message
    print(f"  {BLUE}- Extraction successful: {extract_message}{RESET}")

    print(f"  {BLUE}Step 1: Finding target corner node...{RESET}")
    source_path_for_finding_nodes = nodes_source_filepath
    if not os.path.exists(source_path_for_finding_nodes):
        return False, f"{RED}ERROR: Node source file {CYAN}'{source_path_for_finding_nodes}'{RED} does not exist, cannot find corner node.{RESET}"

    print(f"  {BLUE}- Node lookup will be performed on file {CYAN}'{source_path_for_finding_nodes}'{BLUE}.{RESET}")
    specific_corner_node, global_extremums, info_msg = find_specific_corner_node(source_path_for_finding_nodes, tolerance=tolerance)

    if global_extremums:
        translate_dx = -global_extremums['min_x']
        translate_dy = -global_extremums['max_y']
        translate_dz = -global_extremums['min_z']

        print(f"  {BLUE}Calculating translation vector based on global extremums: DX={translate_dx:.6f}, DY={translate_dy:.6f}, DZ={translate_dz:.6f}{RESET}")

        print(f"\n{BLUE}Step 3: Generating CFILE for translation operation...{RESET}")
        cfile_generation_success, cfile_generation_message = create_cfile_from_template(
            cfile_template_path=cfile_template_path,
            output_cfile_path=output_cfile_path,
            k_filepath_to_open=k_filepath,
            final_save_k_path=final_save_k_path,
            translate_x=translate_dx,
            translate_y=translate_dy,
            translate_z=translate_dz
        )

        if cfile_generation_success:
            final_return_message = f"{BLUE}Operation successful. Generated {CYAN}'{output_cfile_path}'{BLUE}. This CFILE is ready to be applied.{RESET}"
            print(final_return_message)
            # LLM will need to call apply_cfile_with_lsprepost
            lsp_success, lsp_msg = apply_cfile_with_lsprepost(
                lsprepost_exe_path=lsprepost_exe_path,
                cfile_to_apply=output_cfile_path,
                final_save_k_path=final_save_k_path,
                keep_open=True # For initial translation, usually keep open for user review
            )
            if lsp_success:
                return True, final_save_k_path
            else:
                return False, f"{RED}Translation failed: LS-PrePost execution of CFILE failed: {lsp_msg}{RESET}"
        else:
            final_return_message = f"{RED}Operation failed: {cfile_generation_message}{RESET}"
            print(final_return_message)
            return False, final_return_message
    else:
        final_return_message = f"{RED}Operation aborted: Failed to parse global extremum information from model.{RESET}"
        print(final_return_message)
        return False, final_return_message


def normalize_model_direction(lsprepost_exe_path, cfile_template_path, output_cfile_path,
                              k_filepath_to_open, final_save_k_path,
                              min_x, max_y, min_z, keep_open=True):
    """
    Executes "Positive Direction Normalization" rotation using preset CFILE template.
    This function applies hardcoded rotation commands from the template.
    min_x, max_y, min_z parameters are not used for rotation calculation here but retained as context for LLM decision.
    """
    print(f"\n{BLUE}Step: Using preset CFILE template for direction normalization (Rotation)...{RESET}")
    print(f"  {BLUE}- Model Global Extremums (LLM Decision Reference): {HARDCODED_COLOR}MinX={min_x:.4f}, MaxY={max_y:.4f}, MinZ={min_z:.4f}{RESET}")

    cfile_success, cfile_msg = create_cfile_from_template(
        cfile_template_path=cfile_template_path,
        output_cfile_path=output_cfile_path,
        k_filepath_to_open=k_filepath_to_open,
        final_save_k_path=final_save_k_path
    )

    if not cfile_success:
        return False, f"{RED}Failed to generate or update CFILE: {cfile_msg}{RESET}"

    print(f"{BLUE}Rotation CFILE generated: {CYAN}'{output_cfile_path}'{BLUE}. Attempting to apply...{RESET}")

    lsp_success, lsp_msg = apply_cfile_with_lsprepost(
        lsprepost_exe_path=lsprepost_exe_path,
        cfile_to_apply=output_cfile_path,
        final_save_k_path=final_save_k_path,
        keep_open=keep_open
    )

    if lsp_success:
        return True, final_save_k_path
    else:
        return False, f"{RED}LS-PrePost execution of CFILE failed: {lsp_msg}{RESET}"


def generate_and_run_lsprepost_script(k_file_path_to_open, sid_to_show=None, temp_tcl_script_name="temp_lsprepost_script.tcl", temp_batch_script_name="run_lsprepost_script.bat"):
    """
    Generates a Tcl script and a batch file to launch LS-PrePost and execute the Tcl script.
    If sid_to_show is provided, activates and shows that node set; otherwise, shows all parts.

    Args:
    k_file_path_to_open (str): Full path of the K-file to load on LS-PrePost startup.
    sid_to_show (str/int, optional): Node Set SID to show. If None or empty, shows all parts.
    temp_tcl_script_name (str): Filename for the generated Tcl script.
    temp_batch_script_name (str): Filename for the generated batch script.
    """
    tcl_commands = []

    tcl_commands.append("puts \"--- Tcl Script Start ---\"")
    tcl_commands.append("puts \"Waiting 5 seconds for model to load and parse...\"")
    tcl_commands.append("wait 5000")
    tcl_commands.append("puts \"Wait finished. Model should be loaded.\"")

    if sid_to_show is not None and str(sid_to_show).strip() != "":
        sid_to_show_str = str(sid_to_show).strip()
        tcl_commands.append(f"puts \"--- Debugging Node Sets ---\"")
        tcl_commands.append(f"puts \"Listing all node sets in the model:\"")
        tcl_commands.append(f"set node_sets_list [entities node_set list]")
        tcl_commands.append(f"foreach ns $node_sets_list {{")
        tcl_commands.append(f"    puts \"    Node Set ID: [lindex $ns 0], Title: {{[lindex $ns 1]}}\"")
        tcl_commands.append(f"}}")
        tcl_commands.append(f"set target_sid_exists [lsearch -exact [lmap x $node_sets_list {{lindex $x 0}}] \"{sid_to_show_str}\"]")
        tcl_commands.append(f"if {{ $target_sid_exists == -1 }} {{")
        tcl_commands.append(f"    puts \"WARNING: Node Set SID {sid_to_show_str} was NOT found in the model's node set list.\"")
        tcl_commands.append(f"    puts \"Please ensure the SID is correct in your K-file. Showing all parts instead.\"")
        tcl_commands.append(f"    activatepart 1")
        tcl_commands.append(f"}} else {{")
        tcl_commands.append(f"    puts \"INFO: Node Set SID {sid_to_show_str} was found in the model's node set list.\"")
        tcl_commands.append(f"    puts \"Attempting to deactivate all parts...\"")
        tcl_commands.append(f"    activatepart 0")
        tcl_commands.append(f"    puts \"All parts deactivated.\"")
        tcl_commands.append(f"    puts \"Attempting to activate node set: {sid_to_show_str}\"")
        if sid_to_show_str.isdigit():
            tcl_commands.append(f"    if {{ [catch {{setpart active node_set \"{sid_to_show_str}\"}} err_msg] }} {{")
            tcl_commands.append(f"        puts \"ERROR: Failed to activate node set {sid_to_show_str}. Message: $err_msg\"")
            tcl_commands.append(f"        activatepart 1")
            tcl_commands.append(f"    }} else {{")
            tcl_commands.append(f"        activatepart 1")
            tcl_commands.append(f"        puts \"Node set {sid_to_show_str} activated successfully.\"")
            tcl_commands.append(f"        puts \"Setting display type to Node Set...\"")
            tcl_commands.append(f"        display node_set")
            tcl_commands.append(f"        puts \"Display type set to Node Set.\"")
            tcl_commands.append(f"    }}")
        else:
            tcl_commands.append(f"    puts \"WARNING: SID '{sid_to_show_str}' is not a valid integer. Showing all parts instead.\"")
            tcl_commands.append(f"    activatepart 1")
        tcl_commands.append(f"}}")
        tcl_commands.append("puts \"--- End Debugging Node Sets ---\"")
    else:
        tcl_commands.append("puts \"No specific Node Set ID provided. Activating all parts by default.\"")
        tcl_commands.append("activatepart 1")
        tcl_commands.append("puts \"All parts activated.\"")
        tcl_commands.append("puts \"Setting display type to Parts...\"")
        tcl_commands.append("display part")
        tcl_commands.append("puts \"Display type set to Parts.\"")


    tcl_commands.append("puts \"Attempting to fit view...\"")
    tcl_commands.append("fit")
    tcl_commands.append("puts \"View fitted.\"")

    tcl_commands.append("puts \"Attempting to refresh display...\"")
    tcl_commands.append("refresh")
    tcl_commands.append("puts \"Display refreshed.\"")

    tcl_commands.append("puts \"Tcl Script finished. Staying open.\"")
    tcl_commands.append("stay")
    tcl_commands.append("puts \"LS-PrePost should now remain open.\"")

    try:
        script_dir = os.path.dirname(k_file_path_to_open)
        clean_temp_tcl_script_name = temp_tcl_script_name.replace(HARDCODED_COLOR, '').replace(RESET, '')
        clean_temp_batch_script_name = temp_batch_script_name.replace(HARDCODED_COLOR, '').replace(RESET, '')

        full_temp_tcl_script_path = os.path.join(script_dir, clean_temp_tcl_script_name)
        full_temp_batch_script_path = os.path.join(script_dir, clean_temp_batch_script_name)

        tcl_script_content = "\n".join(tcl_commands).replace("\\", "/")
        with open(full_temp_tcl_script_path, 'w', encoding='utf-8') as f:
            f.write(tcl_script_content)
        print(f"  {BLUE}Tcl script generated:{RESET} {CYAN}'{full_temp_tcl_script_path}'{RESET}")

        lsprepost_exe_path_clean = LSPREPOST_EXE_PATH.replace(HARDCODED_COLOR, '').replace(RESET, '')
        lsprepost_exe_quoted = f'"{os.path.normpath(lsprepost_exe_path_clean)}"'
        k_file_path_quoted = f'"{os.path.normpath(k_file_path_to_open)}"'
        tcl_script_path_for_tcl_source = os.path.normpath(full_temp_tcl_script_path).replace(os.sep, '/')

        tcl_command_string = f'source \\"{tcl_script_path_for_tcl_source}\\"'

        bat_commands = [
            f'@echo off',
            f'start "" {lsprepost_exe_quoted} {k_file_path_quoted} -c "{tcl_command_string}"',
            f'exit'
        ]

        with open(full_temp_batch_script_path, 'w', encoding='ansi') as f:
            f.write("\n".join(bat_commands))
        print(f"  {BLUE}Batch script generated:{RESET} {CYAN}'{full_temp_batch_script_path}'{RESET}")

        if not os.path.exists(lsprepost_exe_path_clean):
            print(f"{RED}ERROR: LS-PrePost executable not found, please check path: {LSPREPOST_EXE_PATH.replace(HARDCODED_COLOR, '').replace(RESET, '')}{RESET}")
            return False

        print(f"\n{BOLD}--- LS-PrePost Launch Info ---{RESET}")
        print(f"Calling batch script {CYAN}'{os.path.basename(full_temp_batch_script_path)}'{RESET} to launch LS-PrePost...")
        print(f"Please ensure the LS-PrePost window pops up, then wait patiently for model loading ({HARDCODED_COLOR}approx. 5 seconds{RESET} or longer depending on model size).")
        print(f"Please check the {BOLD}Tcl/Tk Console{RESET} (Tools -> Tcl/Tk Console) in LS-PrePost for debug output.")
        print(f"It will indicate if the node set exists and if activation was successful.")
        print(f"{BOLD}--------------------------{RESET}\n")

        subprocess.Popen([full_temp_batch_script_path], shell=True)

        return True
    except Exception as e:
        print(f"{RED}Failed to call LS-PrePost: {e}{RESET}")
        return False


def generate_set_node_list_block(node_ids, sid, title_string):
    """
    Generates *SET_NODE_LIST text block based on given node ID list, SID, and title string.
    Strictly follows LS-DYNA K-file format requirements:
    - *SET_NODE_LIST_TITLE
    - User provided title
    - SID control line: SID 10 chars right-aligned, followed by fixed format
    - Node ID data lines: 8 IDs per line, each ID 10 chars, right-aligned.
    Does not include empty line at the end of the block.
    """
    block_lines = []

    block_lines.append(f"*SET_NODE_LIST_TITLE")
    block_lines.append(f"{title_string}")

    block_lines.append(f"$#     sid       da1       da2       da3       da4    solver       its         -")
    block_lines.append(f"{sid:>10}       0.0       0.0       0.0       0.0MECH      1                   ")

    block_lines.append(f"$#    nid1      nid2      nid3      nid4      nid5      nid6      nid7      nid8")

    for i in range(0, len(node_ids), 8):
        current_line_ids = node_ids[i:i+8]
        formatted_ids = "".join(f"{nid:>10}" for nid in current_line_ids)
        block_lines.append(f"{formatted_ids}")

    return [s + '\n' for s in block_lines]


def parse_existing_nodes_from_set_node_list(k_file_path, sid_to_find):
    """
    Parses existing node IDs from *SET_NODE_LIST_TITLE block for specific SID in K-file.
    Returns a list containing node IDs.
    Adapts to new SID line format: SID 10 char slot followed by other data.
    """
    existing_node_ids = []

    try:
        with open(k_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            upper_line = line.upper()

            if upper_line.startswith('*SET_NODE_LIST_TITLE'):
                if i + 3 < len(lines):
                    sid_data_line = lines[i+3]
                    try:
                        current_sid = int(sid_data_line[0:10].strip())
                        if current_sid == sid_to_find:
                            j = i + 4

                            while j < len(lines):
                                data_line = lines[j].strip()
                                upper_data_line = data_line.upper()

                                if (upper_data_line.startswith('*') and not upper_data_line.startswith('*COMMENT')):
                                    break
                                if upper_data_line.startswith('$#'):
                                    j += 1
                                    continue

                                ids_on_line = []
                                for k_idx in range(0, len(data_line), 10):
                                    node_id_str = data_line[k_idx:k_idx+10].strip()
                                    if node_id_str:
                                        try:
                                            ids_on_line.append(int(node_id_str))
                                        except ValueError:
                                            break
                                ids_on_line_count = len(ids_on_line)
                                if ids_on_line_count > 0:
                                    existing_node_ids.extend(ids_on_line)
                                else:
                                    if not data_line:
                                        break
                                j += 1

                            return sorted(list(set(existing_node_ids)))
                    except ValueError:
                        pass
            i += 1

    except FileNotFoundError:
        print(f"{YELLOW}WARNING: File {CYAN}'{k_file_path}'{RESET} does not exist. Unable to parse existing nodes.{RESET}")
    except Exception as e:
        print(f"{RED}Error parsing file {CYAN}'{k_file_path}'{RESET}: {e}{RESET}")

    return sorted(list(set(existing_node_ids)))


def process_and_replace_nodeset_in_kfile(node_ids_to_write, target_sid, title_string, input_kfile_path_for_read, output_kfile_path_for_write):
    """
    Writes specified node ID list to target SID's *SET_NODE_LIST_TITLE block and saves as new K-file.
    If the SID node set already exists in the file, it replaces it; otherwise, appends new content after the last *SET_NODE_LIST_TITLE block.
    Reads input_kfile_path_for_read, modifies it, and writes to output_kfile_path_for_write.
    If no *SET_NODE_LIST_TITLE block exists, appends to end of file (or before global *END).
    """
    if not node_ids_to_write:
        print(f"No nodes to write to SID {target_sid}. Operation skipped.")
        return False, "skipped"

    print(f"\n--- Generating new *SET_NODE_LIST text block (SID: {target_sid}, Title: '{title_string}') ---")
    
    full_new_block_lines = generate_set_node_list_block(node_ids_to_write, target_sid, title_string)

    print(f"--- Reading file '{input_kfile_path_for_read}' and preparing to process ---")
    original_lines = []
    try:
        with open(input_kfile_path_for_read, 'r', encoding='utf-8', errors='ignore') as f:
            original_lines = f.readlines()
    except FileNotFoundError:
        print(f"WARNING: Input file '{input_kfile_path_for_read}' does not exist. Creating a new file '{output_kfile_path_for_write}' and writing content.")
        original_lines = []
    except Exception as e:
        print(f"Error reading input file: {e}")
        return False, "read_error"

    target_sid_block_start = -1
    target_sid_block_end = -1
    operation_type = ""

    i = 0
    while i < len(original_lines):
        line = original_lines[i].strip().upper()
        if line.startswith('*SET_NODE_LIST_TITLE'):
            current_block_start = i
            if i + 3 < len(original_lines):
                sid_data_line = original_lines[i+3]
                try:
                    current_sid_in_file = int(sid_data_line[0:10].strip()) 
                    if current_sid_in_file == target_sid:
                        target_sid_block_start = current_block_start
                        
                        j = i + 1
                        block_end_found = False
                        while j < len(original_lines):
                            check_line = original_lines[j].strip().upper()
                            if check_line.startswith('*') and not check_line.startswith('*COMMENT') and len(check_line) > 1:
                                target_sid_block_end = j
                                block_end_found = True
                                break
                            j += 1
                        if not block_end_found:
                            target_sid_block_end = len(original_lines)
                        
                        operation_type = "replace"
                        break
                except ValueError:
                    pass
        i += 1
    
    final_lines = []

    if operation_type == "replace":
        print(f"Found existing node set block for SID {target_sid}. Replaced its content.")
        final_lines = original_lines[:target_sid_block_start] + full_new_block_lines + original_lines[target_sid_block_end:]
    else:
        insert_idx = -1
        last_set_node_list_title_found = False

        i = len(original_lines) - 1
        while i >= 0:
            line = original_lines[i].strip().upper()
            if line.startswith('*SET_NODE_LIST_TITLE'):
                last_set_node_list_title_found = True
                
                j = i + 1 
                block_end_found = False
                while j < len(original_lines):
                    current_check_line = original_lines[j].strip().upper()
                    if current_check_line.startswith('*') and not current_check_line.startswith('*COMMENT') and len(current_check_line) > 1:
                        insert_idx = j 
                        block_end_found = True
                        break
                    j += 1
                
                if not block_end_found: 
                    insert_idx = len(original_lines)
                
                break 
            i -= 1

        if last_set_node_list_title_found:
            final_lines = original_lines[:insert_idx] + full_new_block_lines + original_lines[insert_idx:]
            operation_type = "append after last *SET_NODE_LIST_TITLE"
        else:
            global_end_keyword_index = -1
            for k in range(len(original_lines) - 1, -1, -1):
                if original_lines[k].strip().upper() == '*END':
                    global_end_keyword_index = k
                    break

            if global_end_keyword_index != -1:
                final_lines = original_lines[:global_end_keyword_index] + full_new_block_lines + original_lines[global_end_keyword_index:]
                operation_type = "insert before global *END"
            else:
                final_lines = original_lines + full_new_block_lines
                operation_type = "append to end (no global *END found)"

    try:
        output_dir = os.path.dirname(output_kfile_path_for_write)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(output_kfile_path_for_write, 'w', encoding='utf-8') as f:
            f.writelines(final_lines) 
        print(f"--- Successfully generated file containing {('updated' if operation_type == 'replace' else 'appended')} content: '{output_kfile_path_for_write}' ---")
        
        print(f"\n>>>> Location of Node Set (SID: {target_sid}, Title: '{title_string}'): ")
        if operation_type == "replace":
            print(f"     It replaced the existing block for SID {target_sid} in file '{input_kfile_path_for_read}' and wrote results to '{output_kfile_path_for_write}'.")
        elif operation_type == "append after last *SET_NODE_LIST_TITLE":
            print(f"     It was appended as a new node set block after the last '*SET_NODE_LIST_TITLE' in file '{input_kfile_path_for_read}' and wrote results to '{output_kfile_path_for_write}'.")
        elif operation_type == "insert before global *END":
            print(f"     It was inserted as a new node set block before the global '*END' keyword in file '{input_kfile_path_for_read}' and wrote results to '{output_kfile_path_for_write}'.")
        elif operation_type == "append to end (no global *END found)":
            print(f"     It was appended to the very end of file '{input_kfile_path_for_read}' and wrote results to '{output_kfile_path_for_write}'.")
        print(f"     You can search for keywords: '*SET_NODE_LIST_TITLE' and 'SID {target_sid}' in file '{output_kfile_path_for_write}' to find it.")

        return True, operation_type
    except Exception as e:
        print(f"Error writing new file: {e}")
        return False, "write_error"


def add_boundary_spc_set_id(k_file_path_to_read, k_file_path_to_write, boundary_id, heading, nodeset_id_to_fix):
    """
    Finds last *SET_NODE_LIST_TITLE block in K-file and inserts *BOUNDARY_SPC_SET_ID block after it.
    If no *SET_NODE_LIST_TITLE exists, appends to end of file or before *END keyword.

    Args:
    k_file_path_to_read (str): K-file path to read.
    k_file_path_to_write (str): New K-file path to write.
    boundary_id (int): ID for *BOUNDARY_SPC_SET_ID.
    heading (str): Heading for *BOUNDARY_SPC_SET_ID.
    nodeset_id_to_fix (int): Node set ID (nsid) to fix.
    """
    print(f"\n{BOLD}--- Adding *BOUNDARY_SPC_SET_ID to file {CYAN}'{k_file_path_to_read}'{RESET} ---{RESET}")

    boundary_block_lines = [
        f"*BOUNDARY_SPC_SET_ID\n",
        f"$#      id                                                               heading\n",
        f"{boundary_id:>10}{heading}\n",
        f"$#    nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz\n",
        f"{nodeset_id_to_fix:>10}         0         1         1         1         1         1         1\n",
    ]

    try:
        with open(k_file_path_to_read, 'r', encoding='utf-8', errors='ignore') as f:
            original_lines = f.readlines()
    except FileNotFoundError:
        msg = f"{RED}ERROR: Input file {CYAN}'{k_file_path_to_read}'{RESET} does not exist. Cannot perform fix operation.{RESET}"
        print(msg)
        return False, "file_not_found"
    except Exception as e:
        msg = f"{RED}Error reading file {CYAN}'{k_file_path_to_read}'{RESET}: {e}{RESET}"
        print(msg)
        return False, "read_error"

    insert_index = -1
    last_set_node_list_title_end_index = -1

    i = 0
    while i < len(original_lines):
        line = original_lines[i].strip().upper()
        if line.startswith('*SET_NODE_LIST_TITLE'):
            block_end = len(original_lines)
            for j in range(i + 1, len(original_lines)):
                check_line = original_lines[j].strip().upper()
                if check_line.startswith('*') and not check_line.startswith('*COMMENT') and len(check_line) > 1:
                    block_end = j
                    break
            last_set_node_list_title_end_index = block_end
            i = block_end
        else:
            i += 1

    if last_set_node_list_title_end_index != -1:
        insert_index = last_set_node_list_title_end_index
        print(f"  {BLUE}Inserted after the last '{BOLD}*SET_NODE_LIST_TITLE{RESET}{BLUE}' block (approx. line {insert_index+1}).{RESET}")
    else:
        print(f"  {YELLOW}WARNING: Keyword '{BOLD}*SET_NODE_LIST_TITLE{RESET}{YELLOW}' not found in file. '{BOLD}*BOUNDARY_SPC_SET_ID{RESET}{YELLOW}' will be added to end of file or before '{BOLD}*END{RESET}{YELLOW}'.{RESET}")
        global_end_keyword_index = -1
        for k in range(len(original_lines) - 1, -1, -1):
            if original_lines[k].strip().upper() == '*END':
                global_end_keyword_index = k
                break

        if global_end_keyword_index != -1:
            insert_index = global_end_keyword_index
            print(f"  {BLUE}Inserted before '{BOLD}*END{RESET}{BLUE}' keyword (line {global_end_keyword_index+1}).{RESET}")
        else:
            insert_index = len(original_lines)
            print(f"  {BLUE}Inserted at the very end of the file.{RESET}")

    modified_lines = original_lines[:insert_index] + boundary_block_lines + original_lines[insert_index:]

    try:
        output_dir = os.path.dirname(k_file_path_to_write)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(k_file_path_to_write, 'w', encoding='utf-8') as f:
            f.writelines(modified_lines)

        success_msg = f"{BLUE}Successfully added {BOLD}*BOUNDARY_SPC_SET_ID{RESET}{BLUE} in {CYAN}'{k_file_path_to_read}'{BLUE} and saved as {CYAN}'{k_file_path_to_write}'{RESET}{BLUE}.{RESET}"
        print(success_msg)
        return True, success_msg
    except Exception as e:
        error_msg = f"{RED}Error writing new file: {e}{RESET}"
        print(error_msg)
        return False, "write_error"


def add_pulse_curve_to_kfile(k_file_path_to_read, k_file_path_to_write, title, lcid, points):
    """
    Adds *DEFINE_CURVE_TITLE block to K-file.
    This function inserts the curve sorted by lcid.
    If no other curves exist, it inserts after the last *PART block.

    Args:
    k_file_path_to_read (str): K-file path to read.
    k_file_path_to_write (str): New K-file path to write.
    title (str): Title of the curve.
    lcid (int): Curve ID.
    points (list of tuples): List of coordinate points, e.g., [(x1, y1), (x2, y2), ...].
    """
    print(f"\n{BOLD}--- Adding Pulse Curve to file {CYAN}'{k_file_path_to_read}'{RESET} (lcid: {lcid}) ---{RESET}")

    try:
        with open(k_file_path_to_read, 'r', encoding='utf-8', errors='ignore') as f:
            original_lines = f.readlines()
    except FileNotFoundError:
        msg = f"{RED}ERROR: Input file {CYAN}'{k_file_path_to_read}'{RESET} does not exist. Cannot add pulse curve.{RESET}"
        print(msg)
        return False, msg
    except Exception as e:
        msg = f"{RED}Error reading file {CYAN}'{k_file_path_to_read}'{RESET}: {e}{RESET}"
        print(msg)
        return False, msg

    curve_block_lines = []
    curve_block_lines.append("*DEFINE_CURVE_TITLE\n")
    curve_block_lines.append(f"{title}\n")
    curve_block_lines.append("$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint\n")
    curve_block_lines.append(f"{lcid:>10}{0:>10}{'1.0':>10}{'1.0':>10}{'0.0':>10}{'0.0':>10}{0:>10}{0:>10}\n")
    curve_block_lines.append("$#                a1                  o1\n")
    for x, y in points:
        curve_block_lines.append(f"{str(float(x)).rjust(20)}{str(float(y)).rjust(20)}\n")

    existing_curves = []
    i = 0
    while i < len(original_lines):
        line = original_lines[i].strip().upper()
        if line.startswith('*DEFINE_CURVE_TITLE'):
            block_start = i
            if i + 3 < len(original_lines):
                try:
                    current_lcid = int(original_lines[i+3][:10].strip())

                    block_end = len(original_lines)
                    for j in range(i + 1, len(original_lines)):
                        if original_lines[j].strip().startswith('*'):
                            block_end = j
                            break

                    existing_curves.append({'lcid': current_lcid, 'start': block_start, 'end': block_end})
                    i = block_end - 1
                except (ValueError, IndexError):
                    pass
        i += 1

    insertion_index = -1
    if existing_curves:
        sorted_curves = sorted(existing_curves, key=lambda x: x['lcid'])

        if lcid < sorted_curves[0]['lcid']:
            insertion_index = sorted_curves[0]['start']
        else:
            found_spot = False
            for k in range(len(sorted_curves) - 1):
                if sorted_curves[k]['lcid'] < lcid < sorted_curves[k+1]['lcid']:
                    insertion_index = sorted_curves[k]['end']
                    found_spot = True
                    break

            if not found_spot:
                insertion_index = sorted_curves[-1]['end']
        print(f"  {BLUE}Sorted by lcid={lcid}, inserting new curve at line {insertion_index + 1}.{RESET}")

    else:
        print(f"  {YELLOW}No existing curves found in file, attempting to insert after last {BOLD}*PART{RESET}{YELLOW}.{RESET}")
        last_part_line_index = -1
        for i in range(len(original_lines) - 1, -1, -1):
            if original_lines[i].strip().upper().startswith('*PART'):
                last_part_line_index = i
                break

        if last_part_line_index == -1:
            msg = f"{YELLOW}WARNING: Keyword '{BOLD}*PART{RESET}{YELLOW}' not found. Pulse curve will be added to end of file or before '{BOLD}*END{RESET}{YELLOW}'.{RESET}"
            print(msg)
            global_end_keyword_index = -1
            for k in range(len(original_lines) - 1, -1, -1):
                if original_lines[k].strip().upper() == '*END':
                    global_end_keyword_index = k
                    break

            if global_end_keyword_index != -1:
                insertion_index = global_end_keyword_index
            else:
                insertion_index = len(original_lines)
        else:
            insertion_index = len(original_lines)
            for i in range(last_part_line_index + 1, len(original_lines)):
                if original_lines[i].strip().startswith('*'):
                    insertion_index = i
                    break

    modified_lines = original_lines[:insertion_index] + curve_block_lines + original_lines[insertion_index:]

    try:
        output_dir = os.path.dirname(k_file_path_to_write)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(k_file_path_to_write, 'w', encoding='utf-8') as f:
            f.writelines(modified_lines)

        success_msg = f"{BLUE}Successfully added pulse curve and saved as {CYAN}'{k_file_path_to_write}'{RESET}{BLUE}.{RESET}"
        print(success_msg)
        return True, success_msg
    except Exception as e:
        error_msg = f"{RED}Error writing new file: {e}{RESET}"
        print(error_msg)
        return False, "write_error"


def add_load_node_set(k_file_path_to_read, k_file_path_to_write, nsid, dof, lcid):
    """
    Inserts *LOAD_NODE_SET block above the first *PART keyword in K-file.
    Automatically calculates sf value as 1/(number of nodes) based on nodes in the set corresponding to nsid.

    Args:
    k_file_path_to_read (str): K-file path to read.
    k_file_path_to_write (str): New K-file path to write.
    nsid (int): Node set ID to load.
    dof (int): Degrees of Freedom.
    lcid (int): ID of the pulse curve.
    """
    print(f"\n{BOLD}--- Adding *LOAD_NODE_SET to file {CYAN}'{k_file_path_to_read}'{RESET} ---{RESET}")

    try:
        print(f"  {BLUE}Parsing node count for node set SID {nsid} from K-file {CYAN}'{k_file_path_to_read}'{BLUE}...{RESET}")
        nodes_in_set = parse_existing_nodes_from_set_node_list(k_file_path_to_read, nsid)
        nodeset_number = len(nodes_in_set)

        if nodeset_number == 0:
            error_msg = f"{RED}ERROR: Node set SID {nsid} not found in K-file or contains no nodes. Cannot calculate sf value.{RESET}"
            print(error_msg)
            return False, error_msg

        sf_value = 1.0 / nodeset_number
        sf_val_str = f"{sf_value:.6f}"

        print(f"  {BLUE}Node set SID {nsid} contains {nodeset_number} nodes.{RESET}")
        print(f"  {BLUE}Calculated sf value is: {BOLD}{sf_val_str}{RESET}")

        data_line = f"{nsid:>10}{dof:>10}{lcid:>10}{sf_val_str:>10}{0:>10}{0:>10}{0:>10}{0:>10}\n"

        load_block_lines = [
            "*LOAD_NODE_SET\n",
            "$3rd pulse\n",
            "$#    nsid       dof      lcid        sf       cid        m1        m2        m3\n",
            data_line
        ]

        with open(k_file_path_to_read, 'r', encoding='utf-8', errors='ignore') as f:
            original_lines = f.readlines()
    except FileNotFoundError:
        msg = f"{RED}ERROR: Input file {CYAN}'{k_file_path_to_read}'{RESET} does not exist. Cannot apply pulse.{RESET}"
        print(msg)
        return False, msg
    except Exception as e:
        msg = f"{RED}Error reading file {CYAN}'{k_file_path_to_read}'{RESET} or calculating sf value: {e}{RESET}"
        print(msg)
        return False, msg

    insert_index = -1
    for i, line in enumerate(original_lines):
        if line.strip().upper().startswith('*PART'):
            insert_index = i
            break

    if insert_index == -1:
        msg = f"{RED}ERROR: First '{BOLD}*PART{RESET}{RED}' keyword not found in file. Unable to determine insertion position.{RESET}"
        print(msg)
        return False, msg

    modified_lines = original_lines[:insert_index] + load_block_lines + original_lines[insert_index:]

    try:
        output_dir = os.path.dirname(k_file_path_to_write)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(k_file_path_to_write, 'w', encoding='utf-8') as f:
            f.writelines(modified_lines)

        success_msg = f"{BLUE}Successfully added {BOLD}*LOAD_NODE_SET{RESET}{BLUE} (sf={sf_val_str}) and saved as {CYAN}'{k_file_path_to_write}'{RESET}{BLUE}.{RESET}"
        print(success_msg)
        return True, success_msg
    except Exception as e:
        error_msg = f"{RED}Error writing new file: {e}{RESET}"
        print(error_msg)
        return False, "write_error"


def extract_solid_element_nodes_and_save_node_data(k_filepath: str, output_txt_filepath: str) -> tuple[bool, str]:
    """
    Extract node IDs involved in all *ELEMENT_SOLID blocks from the K file,
    then filter the corresponding *NODE lines and save them to the specified TXT file.
    """
    print(f"\n{BOLD}--- Extracting solid element nodes from {CYAN}'{k_filepath}'{RESET}{BOLD} and saving to {CYAN}'{output_txt_filepath}'{RESET}{BOLD} ---{RESET}")

    solid_node_ids = set()
    node_data_to_save = []
    in_solid_element_section = False
    in_node_section = False

    try:
        with open(k_filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                line_stripped = line.strip()

                if line_stripped.startswith('*ELEMENT_SOLID'):
                    in_solid_element_section = True
                    continue
                elif line_stripped.startswith('*') and in_solid_element_section and not line_stripped.startswith('*ELEMENT_SOLID'):
                    in_solid_element_section = False

                if in_solid_element_section and not line_stripped.startswith('$') and line_stripped:
                    try:
                        parts = line_stripped.split()
                        if len(parts) >= 9:
                            for i in range(1, 9):
                                solid_node_ids.add(int(parts[i]))
                    except ValueError:
                        print(f"{YELLOW}WARNING: Unable to parse solid element node IDs at line {line_num}: {line_stripped}{RESET}")
                    except IndexError:
                        print(f"{YELLOW}WARNING: Incorrect solid element data format at line {line_num} in K file: {line_stripped}{RESET}")

        if not solid_node_ids:
            return False, f"{RED}No {BOLD}*ELEMENT_SOLID{RESET}{RED} elements found in K file or unable to extract node IDs.{RESET}"

        with open(k_filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                line_stripped = line.strip()

                if line_stripped.startswith('*NODE'):
                    node_data_to_save.append(line)
                    node_data_to_save.append('$#   nid               x               y               z      tc      rc  \n')
                    in_node_section = True
                    continue
                elif line_stripped.startswith('*') and in_node_section and not line_stripped.startswith('*NODE'):
                    in_node_section = False

                if in_node_section and not line_stripped.startswith('$') and line_stripped:
                    try:
                        parts = line_stripped.split()
                        if len(parts) >= 4:
                            node_id = int(parts[0])
                            if node_id in solid_node_ids:
                                node_data_to_save.append(line)
                    except ValueError:
                        print(f"{YELLOW}WARNING: Unable to parse node ID at line {line_num} in K file: {line_stripped}{RESET}")
                    except IndexError:
                        print(f"{YELLOW}WARNING: Incorrect node data format at line {line_num} in K file: {line_stripped}{RESET}")
                elif line_stripped.startswith('$') and in_node_section:
                    node_data_to_save.append(line)

        if not node_data_to_save:
            return False, f"{RED}No nodes matching {BOLD}*ELEMENT_SOLID{RESET}{RED} were found in the {BOLD}*NODE{RESET}{RED} section of the K file.{RESET}"

        output_dir = os.path.dirname(output_txt_filepath)
        os.makedirs(output_dir, exist_ok=True)

        with open(output_txt_filepath, 'w', encoding='utf-8') as outfile:
            outfile.writelines(node_data_to_save)

        return True, f"{BLUE}Successfully extracted and saved data for {len(solid_node_ids)} solid element nodes to {CYAN}'{output_txt_filepath}'{RESET}{BLUE}.{RESET}"

    except FileNotFoundError:
        return False, f"{RED}ERROR: K file not found: {CYAN}'{k_filepath}'{RESET}"
    except Exception as e:
        return False, f"{RED}Unknown error occurred while extracting solid element node data: {e}{RESET}"


def parse_node_data(filepath: str) -> list[dict]:
    """
    Parse node data from solid_nodes.txt or surface_node.txt files.
    Each node data is stored as a dictionary: {'nid': int, 'x': float, 'y': float, 'z': float}
    """
    nodes = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            in_node_section = False
            for line_num, line in enumerate(f, 1):
                line_stripped = line.strip()

                if line_stripped.startswith('*NODE'):
                    in_node_section = True
                    continue
                elif line_stripped.startswith('$#   nid'):
                    continue
                elif line_stripped.startswith('*') and in_node_section:
                    in_node_section = False
                    continue

                if in_node_section and not line_stripped.startswith('$') and line_stripped:
                    try:
                        parts = line_stripped.split()
                        if len(parts) >= 4:
                            nid = int(parts[0])
                            x = float(parts[1])
                            y = float(parts[2])
                            z = float(parts[3])
                            nodes.append({'nid': nid, 'x': x, 'y': y, 'z': z})
                    except (ValueError, IndexError) as e:
                        pass
    except FileNotFoundError:
        print(f"{RED}ERROR: File not found: {CYAN}'{filepath}'{RESET}")
    except Exception as e:
        print(f"{RED}Unknown error occurred while reading node data: {e}{RESET}")
    return nodes


def extract_3d_outer_surface_points_knn_pca_improved(
    all_nodes: list[dict],
    k_neighbors: int = 20,
    pca_ratio_threshold: float = 0.3,
) -> list[dict]:
    """
    Use KNN-PCA to identify points on local planes to extract 3D outer surface points.
    This method should capture all surfaces for L-shaped or non-axis-aligned structures.

    Parameters:
        all_nodes: List of all nodes.
        k_neighbors: Number of nearest neighbors for KNN.
        pca_ratio_threshold: Planarity threshold (ratio of min eigenvalue to max eigenvalue).
                             Larger values are more lenient on planarity, capturing more surface points.
    Returns:
        List of extracted 3D outer surface points.
    """
    if not all_nodes or len(all_nodes) < k_neighbors:
        print(f"{RED}Insufficient number of nodes ({len(all_nodes)}) for KNN analysis; at least {k_neighbors} are required.{RESET}")
        return []

    coords = np.array([[node['x'], node['y'], node['z']] for node in all_nodes])
    nids = np.array([node['nid'] for node in all_nodes])

    node_map = {node['nid']: node for node in all_nodes}

    neigh = NearestNeighbors(n_neighbors=k_neighbors + 1, algorithm='kd_tree', n_jobs=-1)
    neigh.fit(coords)
    distances, indices = neigh.kneighbors(coords)

    print(f"--- Identifying points on local planes using KNN-PCA ({BOLD}K={k_neighbors}{RESET}, {BOLD}PCA_THR={pca_ratio_threshold}{RESET}) ---")
    print(f"This step has been parallelized and will utilize all available CPU cores.")

    def _process_node_for_planarity(i_node, current_coords, current_indices, current_nids, threshold):
        """
        Helper function for single node planarity detection, used for parallelization.
        """
        neighbor_indices = current_indices[i_node, 1:]
        neighbor_coords = current_coords[neighbor_indices]

        if len(neighbor_coords) < 3:
            return None

        pca = PCA(n_components=3)
        pca.fit(neighbor_coords)
        eigenvalues = pca.explained_variance_
        eigenvalues.sort()

        if eigenvalues[2] > 1e-9:
            ratio = eigenvalues[0] / eigenvalues[2]
            if ratio < threshold:
                return current_nids[i_node]
        return None

    results = joblib.Parallel(n_jobs=-1, backend='loky')(
        joblib.delayed(_process_node_for_planarity)(i, coords, indices, nids, pca_ratio_threshold)
        for i in range(len(coords))
    )

    surface_candidates_nids_set = set(nid for nid in results if nid is not None)

    print(f"  {BLUE}Preliminarily identified {len(surface_candidates_nids_set)} local planar points.{RESET}")

    if not surface_candidates_nids_set:
        print(f"{RED}No local planar points identified. Please consider adjusting {HARDCODED_COLOR}k_neighbors{RESET} or {HARDCODED_COLOR}pca_ratio_threshold{RESET} parameters.{RESET}")
        return []

    extracted_surface_nodes_list = [node_map[nid] for nid in sorted(list(surface_candidates_nids_set))]

    return extracted_surface_nodes_list


def write_surface_nodes_to_file(filepath: str, nodes: list[dict]):
    """
    Save extracted surface nodes to the specified file in a format similar to solid_nodes.txt.
    """
    output_dir = os.path.dirname(filepath)
    os.makedirs(output_dir, exist_ok=True)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('*NODE\n')
            f.write('$#   nid               x               y               z\n')
            for node in nodes:
                f.write(f"{node['nid']:10d} {node['x']:15.6f} {node['y']:15.6f} {node['z']:15.6f}\n")
            f.write('*END\n')
        print(f"{BLUE}Successfully wrote {len(nodes)} surface nodes to: {CYAN}'{filepath}'{RESET}{BLUE}.{RESET}")
        return True
    except Exception as e:
        print(f"{RED}Failed to write surface node file: {e}{RESET}")
        return False


def extract_surface_nodes_workflow(input_node_filepath: str, output_surface_filepath: str):
    """
    Execute the complete workflow for surface node extraction.
    """
    print(f"\n{BOLD}--- Step 1: Read node data ({CYAN}'{input_node_filepath}'{RESET}{BOLD}) ---{RESET}")
    all_nodes = parse_node_data(input_node_filepath)
    if not all_nodes:
        print(f"{RED}ERROR: Unable to read node data, operation aborted.{RESET}")
        return False
    print(f"{BLUE}Successfully read {len(all_nodes)} nodes.{RESET}")

    K_NEIGHBORS = 20
    PCA_RATIO_THRESHOLD = 0.5

    print(f"\n{BOLD}--- Step 2: Extract 3D surface points (using KNN-PCA local planarity check) ---{RESET}")
    print(f"  {BOLD}KNN-PCA Parameters:{RESET} {HARDCODED_COLOR}k_neighbors={K_NEIGHBORS}, pca_ratio_threshold={PCA_RATIO_THRESHOLD}{RESET}")
    print(f"  {YELLOW}If the surface is still incomplete or contains internal points, please adjust these parameters.{RESET}")
    extracted_surface_nodes = extract_3d_outer_surface_points_knn_pca_improved(
        all_nodes,
        k_neighbors=K_NEIGHBORS,
        pca_ratio_threshold=PCA_RATIO_THRESHOLD
    )

    if not extracted_surface_nodes:
        print(f"{RED}ERROR: Unable to extract surface nodes. Please check parameters or data.{RESET}")
        return False
    print(f"{BLUE}Successfully extracted {len(extracted_surface_nodes)} surface nodes.{RESET}")

    print(f"\n{BOLD}--- Step 3: Save extracted surface points to file ({CYAN}'{output_surface_filepath}'{RESET}{BOLD}) ---{RESET}")
    return write_surface_nodes_to_file(output_surface_filepath, extracted_surface_nodes)


def find_nodes_by_criteria(k_file_path, criteria_type='coord_range', tolerance=GENERAL_COORD_TOLERANCE, x_range=(None, None), y_range=(None, None), z_range=(None, None), gui_log_func=None):
    """
    Find nodes based on coordinate range or minimum Y coordinate.
    
    Returns: (found_nodes_ids: list, info_message: str)
          found_nodes_ids is a list of integers containing found node IDs.
          info_message is a string describing the result or encountered errors.
    """
    # Helper log function; if gui_log_func is not provided, fall back to standard error output
    _log = gui_log_func if gui_log_func else (lambda msg, level="info": print(f"[{level.upper()}] {msg}", file=sys.stderr))

    # parse_k_file also needs log functionality, so pass it along
    nodes_data_raw = parse_k_file(k_file_path, gui_log_func=_log) 
    
    # Enhanced check for parse_k_file return value
    if not isinstance(nodes_data_raw, dict): 
        _log(f"{RED}ERROR: parse_k_file returned a non-dictionary result; cannot process K file '{CYAN}{k_file_path}{RESET}{RED}'.", level="error")
        return [], f"{RED}ERROR: parse_k_file returned a non-dictionary result; cannot process K file '{CYAN}{k_file_path}{RESET}{RED}'.{RESET}"
    
    nodes_data = nodes_data_raw
    
    if not nodes_data: 
        return [], f"{RED}ERROR: Unable to load or parse K file {CYAN}'{k_file_path}'{RESET}{RED}, or the file contains no nodes.{RESET}"

    found_nodes_ids = []
    info_message = "" # Initialize message

    # --- START MODIFICATION ---
    # Ensure all range parameters are tuples with two elements for safe unpacking.
    # If the original x_range, y_range, z_range has only 1 element or is non-iterable, handle as default.
    def ensure_two_elements(coord_range_val):
        if isinstance(coord_range_val, (list, tuple)):
            if len(coord_range_val) == 2:
                return tuple(coord_range_val)
            elif len(coord_range_val) == 1:
                # If only one value, default to min or max of the range.
                # Assuming single value might refer to a specific point or upper/lower bound.
                # Temporarily treating as (val, val), can be refined if needed.
                return (coord_range_val[0], coord_range_val[0]) if coord_range_val[0] is not None else (None, None)
            else: # More than 2 elements, take the first two
                return tuple(coord_range_val[:2])
        return (None, None) # If not list/tuple or empty, return default (None, None)

    x_range = ensure_two_elements(x_range)
    y_range_for_coord_range = ensure_two_elements(y_range) # For 'coord_range' type
    y_range_for_min_y = ensure_two_elements(y_range) # For 'min_y' type, specifically max_y_user

    min_x, max_x = x_range
    # Using different unpacked variables based on criteria_type, but underlying y_range is the same.
    # Avoiding immediate full unpacking of y_range to min_y_user, max_y_user here.
    # 'min_y' type uses max_y_user (upper bound).
    # 'coord_range' type uses min_y and max_y (range).
    
    min_z, max_z = ensure_two_elements(z_range)
    # --- END MODIFICATION ---

    # Re-declare min_y_user and max_y_user, assigning only when needed
    min_y_user = None
    max_y_user = None
    min_y = None
    max_y = None

    if criteria_type == 'min_y':
        # For min_y, we care about Y upper bound (max_y_user)
        # So take the second element from y_range_for_min_y as upper bound
        _, max_y_user = y_range_for_min_y 
        candidate_nodes_for_min_y = []
        overall_min_y_val = float('inf')

        for nid, (x, y, z) in nodes_data.items():
            match_xyz = True
            if min_x is not None and float(x) < min_x - tolerance: match_xyz = False
            if max_x is not None and float(x) > max_x + tolerance: match_xyz = False
            if max_y_user is not None and float(y) > max_y_user + tolerance: match_xyz = False
            if min_z is not None and float(z) < min_z - tolerance: match_xyz = False
            if max_z is not None and float(z) > max_z + tolerance: match_xyz = False

            if match_xyz:
                try:
                    x_f, y_f, z_f = float(x), float(y), float(z)
                except ValueError:
                    _log(f"{YELLOW}WARNING: Coordinates ({x},{y},{z}) for node {nid} cannot be converted to float; skipping.", level="warning")
                    continue
                candidate_nodes_for_min_y.append({'id': nid, 'x': x_f, 'y': y_f, 'z': z_f})
                if y_f < overall_min_y_val:
                    overall_min_y_val = y_f

        if not candidate_nodes_for_min_y:
            return [], f"{YELLOW}No nodes found within the specified X, Y upper limit, and Z coordinate ranges.{RESET}"

        for node_info in candidate_nodes_for_min_y:
            if abs(node_info['y'] - overall_min_y_val) <= tolerance:
                found_nodes_ids.append(node_info['id'])

        info_message = f"{BLUE}Successfully found {len(found_nodes_ids)} nodes within specified X, Z ranges and Y upper limit with minimum Y coordinate (Y ≈ {overall_min_y_val:.4f}).{RESET}"

    elif criteria_type == 'coord_range':
        min_y, max_y = y_range_for_coord_range # Unpack from new variable

        for nid, (x, y, z) in nodes_data.items():
            match = True
            try:
                x_f, y_f, z_f = float(x), float(y), float(z)
            except ValueError:
                _log(f"{YELLOW}WARNING: Coordinates ({x},{y},{z}) for node {nid} cannot be converted to float; skipping.", level="warning")
                continue

            if min_x is not None and x_f < min_x - tolerance: match = False
            if max_x is not None and x_f > max_x + tolerance: match = False
            if min_y is not None and y_f < min_y - tolerance: match = False
            if max_y is not None and y_f > max_y + tolerance: match = False
            if min_z is not None and z_f < min_z - tolerance: match = False
            if max_z is not None and z_f > max_z + tolerance: match = False

            if match:
                found_nodes_ids.append(nid)

        info_message = f"{BLUE}Successfully found {len(found_nodes_ids)} nodes within the specified coordinate range.{RESET}"
    else:
        info_message = f"{RED}ERROR: Unknown search criteria type '{criteria_type}'.{RESET}"

    return found_nodes_ids, info_message


def add_nodes_to_existing_nodeset_by_criteria(
    k_file_path: str,
    target_sid: int,
    title_string: str,
    input_kfile_path_for_read: str,
    output_kfile_path_for_write: str,
    criteria_type: str = 'coord_range',
    tolerance: float = GENERAL_COORD_TOLERANCE,
    x_range: tuple = (None, None),
    y_range: tuple = (None, None),
    z_range: tuple = (None, None)
) -> tuple[bool, str, int]:
    """
    Select new nodes based on given criteria and append them to an existing node set with the specified SID in the K file.
    If the target SID does not exist, a new node set will be created.

    Args:
        k_file_path (str): Full path to the K file or TXT file (e.g., solid_nodes.txt or surface_nodes.txt) containing node data.
                           This is the source file used by `find_nodes_by_criteria`.
        target_sid (int): SID of the target node set.
        title_string (str): Title of the node set.
        input_kfile_path_for_read (str): Full path to the original LS-DYNA K file to read existing node sets.
        output_kfile_path_for_write (str): Full path to save the modified LS-DYNA K file.
        criteria_type (str): Search type, 'min_y' or 'coord_range'.
        tolerance (float): Floating point tolerance for coordinate matching.
        x_range (tuple): X coordinate range.
        y_range (tuple): Y coordinate range.
        z_range (tuple): Z coordinate range.

    Returns:
        tuple[bool, str, int]: A tuple where the first element indicates success (True/False),
                               the second is the result message, and the third is the total node count in the final node set.
    """
    print(f"\n{BOLD}--- Appending nodes to existing node set (SID: {target_sid}) ---{RESET}")

    # 1. Find new nodes based on criteria
    new_found_nodes, info_msg = find_nodes_by_criteria(
        k_file_path=k_file_path,
        criteria_type=criteria_type,
        tolerance=tolerance,
        x_range=x_range,
        y_range=y_range,
        z_range=z_range
    )

    if not new_found_nodes:
        return False, f"{RED}No new nodes found matching the criteria; cannot append.{RESET} {info_msg}", 0

    print(f"  {BLUE}Found {len(new_found_nodes)} new nodes matching the criteria.{RESET}")

    # 2. Parse existing nodes in the target SID from the K file
    existing_node_ids = parse_existing_nodes_from_set_node_list(input_kfile_path_for_read, target_sid)

    if existing_node_ids:
        print(f"  {BLUE}{len(existing_node_ids)} nodes already exist in node set SID {target_sid}.{RESET}")
    else:
        print(f"  {YELLOW}Node set SID {target_sid} does not exist or is empty in the K file; a new node set will be created.{RESET}")

    # 3. Merge new and old nodes and remove duplicates
    combined_nodes = list(set(existing_node_ids + new_found_nodes))
    combined_nodes.sort()

    # 4. Write the merged node list to the K file (this replaces the original node set)
    process_success, process_msg = process_and_replace_nodeset_in_kfile(
        node_ids_to_write=combined_nodes,
        target_sid=target_sid,
        title_string=title_string,
        input_kfile_path_for_read=input_kfile_path_for_read,
        output_kfile_path_for_write=output_kfile_path_for_write
    )

    if process_success:
        final_count = len(combined_nodes)
        success_message = (
            f"{BLUE}Successfully appended {len(new_found_nodes)} new nodes to node set SID {target_sid}."
            f"The node set now contains {final_count} nodes.{RESET}"
        )
        print(success_message)
        return True, success_message, final_count
    else:
        error_message = f"{RED}Failed to append nodes to node set SID {target_sid}: {process_msg}{RESET}"
        print(error_message)
        return False, error_message, len(existing_node_ids)

# ==============================================================================
# ======================== Material==============================
# ==============================================================================

def _get_rebar_section_blocks(k_file_path_to_read):
    """
    Helper function: Parse information for all *SECTION_BEAM / *SECTION_BEAM_TITLE blocks from the K file.
    Returns a list containing dictionaries of these blocks.
    """
    section_beam_blocks = []
    try:
        with open(k_file_path_to_read, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"ERROR: Input file '{k_file_path_to_read}' does not exist.")
        return []
    except Exception as e:
        print(f"Error occurred while reading file '{k_file_path_to_read}': {e}")
        return []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        upper_line = line.upper()
        
        block_keyword = None
        current_title = ""
        data_line_1_str = ""
        data_line_2_str = ""
        
        if upper_line.startswith('*SECTION_BEAM_TITLE'):
            block_keyword = '*SECTION_BEAM_TITLE'
            if i + 5 < len(lines):
                current_title = lines[i+1].rstrip('\n')
                data_line_1_str = lines[i+3].rstrip('\n')
                data_line_2_str = lines[i+5].rstrip('\n')
                j = i + 1
                while j < len(lines):
                    check_line = lines[j].strip()
                    if check_line.startswith('*') and not check_line.upper().startswith('*COMMENT') and len(check_line) > 1:
                        break
                    j += 1
                block_end = j
                
                try:
                    current_secid = int(data_line_1_str[0:10].strip())
                    current_ts1 = float(data_line_2_str[0:10].strip())
                    current_ts2 = float(data_line_2_str[10:20].strip())
                    section_beam_blocks.append({
                        'keyword': block_keyword,
                        'title': current_title,
                        'secid': current_secid,
                        'ts1': current_ts1,
                        'ts2': current_ts2,
                        'start_line_idx': i,
                        'end_line_idx': block_end,
                        'original_lines': [line.rstrip('\n') for line in lines[i:block_end]],
                        'data_line_1_idx_in_block': 3,
                        'data_line_2_idx_in_block': 5
                    })
                    i = block_end
                    continue
                except (ValueError, IndexError) as e:
                    print(f"WARNING: Error occurred while parsing *SECTION_BEAM_TITLE block (line {i+1}): {e}. Skipping this block.")
        elif upper_line.startswith('*SECTION_BEAM'):
            block_keyword = '*SECTION_BEAM'
            if i + 4 < len(lines):
                current_title = ""
                data_line_1_str = lines[i+2].rstrip('\n')
                data_line_2_str = lines[i+4].rstrip('\n')
                j = i + 1
                while j < len(lines):
                    check_line = lines[j].strip()
                    if check_line.startswith('*') and not check_line.upper().startswith('*COMMENT') and len(check_line) > 1:
                        break
                    j += 1
                block_end = j
                
                try:
                    current_secid = int(data_line_1_str[0:10].strip())
                    current_ts1 = float(data_line_2_str[0:10].strip())
                    current_ts2 = float(data_line_2_str[10:20].strip())
                    section_beam_blocks.append({
                        'keyword': block_keyword,
                        'title': current_title,
                        'secid': current_secid,
                        'ts1': current_ts1,
                        'ts2': current_ts2,
                        'start_line_idx': i,
                        'end_line_idx': block_end,
                        'original_lines': [line.rstrip('\n') for line in lines[i:block_end]],
                        'data_line_1_idx_in_block': 2,
                        'data_line_2_idx_in_block': 4
                    })
                    i = block_end
                    continue
                except (ValueError, IndexError) as e:
                    print(f"WARNING: Error occurred while parsing *SECTION_BEAM block (line {i+1}): {e}. Skipping this block.")
        i += 1
    return section_beam_blocks

def llm_modify_rebar_section(k_file_path_to_read, k_file_path_to_write, secid: int, TITLE: str = None, ts1: float = None, ts2: float = None,
                             gui_output_func=None, gui_get_input_func=None, gui_ask_yes_no_func=None, gui_log_func=None): # <-- Added GUI callbacks
    """
    Modify size parameters of an existing rebar section (*SECTION_BEAM or *SECTION_BEAM_TITLE) in the K file.
    Only TITLE, ts1, and ts2 can be modified; secid remains unchanged.
    """
    # Initialize log and output functions
    _output = gui_output_func if gui_output_func else lambda msg, sender_tag="tool_output": print(msg)
    _log = gui_log_func if gui_log_func else lambda msg, level="info": print(f"[{level.upper()}] {msg}")

    _log(f"--- Modifying rebar section (secid: {secid}) ---", "info")
    _output(f"Modifying rebar section (secid: {secid})...", "tool_output")

    section_beam_blocks = _get_rebar_section_blocks(k_file_path_to_read)
    if not section_beam_blocks:
        _log("No rebar section blocks found in the current file to modify.", "warning")
        return False, "No rebar section blocks found in the current file to modify."

    selected_block_data = None
    for block in section_beam_blocks:
        if block['secid'] == secid:
            selected_block_data = block
            break

    if not selected_block_data:
        _log(f"Rebar section with secid {secid} not found; cannot modify.", "warning")
        return False, f"Rebar section with secid {secid} not found; cannot modify."

    # Get information from parsed data and original lines
    current_title = selected_block_data['title']
    current_secid = selected_block_data['secid']
    current_ts1 = selected_block_data['ts1']
    current_ts2 = selected_block_data['ts2']
    original_block_lines_no_newline = list(selected_block_data['original_lines'])

    # Use parameters provided by LLM; if not provided, keep existing values
    new_title = TITLE if TITLE is not None else current_title
    new_ts1 = ts1 if ts1 is not None else current_ts1
    new_ts2 = ts2 if ts2 is not None else current_ts2

    _log(f"Going to modify section {secid}: TITLE='{current_title}' -> '{new_title}', ts1={current_ts1} -> {new_ts1}, ts2={current_ts2} -> {new_ts2}", "info")

    # --- Rebuild block content, preserving original format ---
    modified_block_lines = []
    modified_block_lines.append("*SECTION_BEAM_TITLE") # Unify to keyword with TITLE
    modified_block_lines.append(new_title) # TITLE line

    # $# secid ... comment line
    if selected_block_data['keyword'] == '*SECTION_BEAM_TITLE':
        modified_block_lines.append(original_block_lines_no_newline[2])
    else: # *SECTION_BEAM originally has only 5 lines, index differs
        modified_block_lines.append(original_block_lines_no_newline[1])
    
    # secid data line
    original_data_line_1_content = original_block_lines_no_newline[selected_block_data['data_line_1_idx_in_block']]
    new_data_line_1_content = f"{current_secid:>10}{original_data_line_1_content[10:]}"
    modified_block_lines.append(new_data_line_1_content)

    # $# ts1 ... comment line
    if selected_block_data['keyword'] == '*SECTION_BEAM_TITLE':
        modified_block_lines.append(original_block_lines_no_newline[4])
    else: # *SECTION_BEAM
        modified_block_lines.append(original_block_lines_no_newline[3])
    
    # ts1, ts2 data line
    original_data_line_2_content = original_block_lines_no_newline[selected_block_data['data_line_2_idx_in_block']]
    new_data_line_2_content = f"{new_ts1:>10.3f}{new_ts2:>10.3f}{original_data_line_2_content[20:]}"
    modified_block_lines.append(new_data_line_2_content)

    # Add newline character back to each line
    modified_block_lines_with_newline = [line + '\n' for line in modified_block_lines]

    try:
        with open(k_file_path_to_read, 'r', encoding='utf-8', errors='ignore') as f:
            final_lines = f.readlines()
    except Exception as e:
        _log(f"Failed to read file: {e}", "error")
        return False, f"Failed to read file: {e}"

    # Replace or insert block
    start_mod_idx = selected_block_data['start_line_idx']
    end_mod_idx = selected_block_data['end_line_idx']
    
    # If original was *SECTION_BEAM, new block has one more TITLE line than old block; adjust end_mod_idx
    # Here we replace the slice directly; Python handles length differences
    final_lines[start_mod_idx:end_mod_idx] = modified_block_lines_with_newline

    success, msg = _write_k_file_from_lines(k_file_path_to_write, final_lines)
    if success:
        _output(f"Rebar section (secid: {secid}) successfully modified.", "tool_output")
        _log(f"Rebar section (secid: {secid}) successfully modified.", "info")
    else:
        _output(f"Failed to modify rebar section (secid: {secid}): {msg}", "tool_output")
        _log(f"Failed to modify rebar section (secid: {secid}): {msg}", "error")
    return success, msg

# Modify llm_add_rebar_section function
def llm_add_rebar_section(k_file_path_to_read, k_file_path_to_write, secid: int, TITLE: str, ts1: float, ts2: float,
                          gui_output_func=None, gui_get_input_func=None, gui_ask_yes_no_func=None, gui_log_func=None): # <-- Added GUI callbacks
    """
    Add a new rebar section to the K file. If secid already exists, replace it; otherwise, add a new one.
    """
    # Initialize log and output functions
    _output = gui_output_func if gui_output_func else lambda msg, sender_tag="tool_output": print(msg)
    _log = gui_log_func if gui_log_func else lambda msg, level="info": print(f"[{level.upper()}] {msg}")

    _log(f"--- Adding/Updating rebar section (secid: {secid}, TITLE: '{TITLE}') ---", "info")
    _output(f"Adding/Updating rebar section (secid: {secid})...", "tool_output")

    section_beam_blocks = _get_rebar_section_blocks(k_file_path_to_read)
    
    # Construct new block content
    new_block_lines = []
    new_block_lines.append(f"*SECTION_BEAM_TITLE\n")
    new_block_lines.append(f"{TITLE}\n")
    new_block_lines.append(f"$#   secid    elform      shrf   qr/irid       cst     scoor       nsm     naupd\n")
    new_block_lines.append(f"{secid:>10}         1       1.0         2         0       0.0       0.0         0\n") # Default values for other fields
    new_block_lines.append(f"$#     ts1       ts2       tt1       tt2     nsloc     ntloc\n")
    new_block_lines.append(f"{ts1:>10.3f}{ts2:>10.3f}{0.0:>10.1f}{0.0:>10.1f}{0.0:>10.1f}{0.0:>10.1f}\n") # Default values for other fields

    try:
        with open(k_file_path_to_read, 'r', encoding='utf-8', errors='ignore') as f:
            final_lines = f.readlines()
    except FileNotFoundError:
        final_lines = [] # Create empty list if file doesn't exist
        _log(f"WARNING: Input file '{k_file_path_to_read}' does not exist. A new file will be created.", "warning")
    except Exception as e:
        _log(f"Failed to read file: {e}", "error")
        return False, f"Failed to read file: {e}"

    existing_secid_block = None
    for block in section_beam_blocks:
        if block['secid'] == secid:
            existing_secid_block = block
            break

    if existing_secid_block:
        # Replace existing block
        _log(f"Detected that secid {secid} already exists. Content will be replaced.", "info")
        start_mod_idx = existing_secid_block['start_line_idx']
        end_mod_idx = existing_secid_block['end_line_idx']
        final_lines[start_mod_idx:end_mod_idx] = new_block_lines
        msg = f"Rebar section (secid: {secid}) updated."
    else:
        # Add new block
        insertion_idx = -1
        if section_beam_blocks:
            insertion_idx = section_beam_blocks[-1]['end_line_idx'] 
            _log(f"Inserting new rebar section (secid: {secid}) after the last existing section (approx line {insertion_idx+1}).", "info")
        else:
            global_end_keyword_index = -1
            for k in range(len(final_lines) - 1, -1, -1):
                if final_lines[k].strip().upper() == '*END':
                    global_end_keyword_index = k
                    break
            
            if global_end_keyword_index != -1:
                insertion_idx = global_end_keyword_index
                _log(f"Inserting new rebar section (secid: {secid}) before '*END' keyword (line {global_end_keyword_index+1}).", "info")
            else:
                insertion_idx = len(final_lines)
                _log(f"Appending new rebar section (secid: {secid}) to the end of the file.", "info")
        
        final_lines[insertion_idx:insertion_idx] = new_block_lines
        msg = f"New rebar section (secid: {secid}, TITLE: '{TITLE}') added to file."
    
    success, write_msg = _write_k_file_from_lines(k_file_path_to_write, final_lines)
    if success:
        _output(msg, "tool_output")
        _log(msg, "info")
    else:
        _output(f"Failed to add/update rebar section (secid: {secid}): {write_msg}", "tool_output")
        _log(f"Failed to add/update rebar section (secid: {secid}): {write_msg}", "error")
    return success, write_msg

def add_material_to_kfile(k_file_path_to_read, k_file_path_to_write, material_block_lines, material_id, material_keyword):
    """
    Insert or replace the generated material block into the K file.
    If a material block with the same keyword and ID exists, replace it; otherwise, append to the end of the file or before *END.

    Parameters:
    k_file_path_to_read (str): Path to original K file to read.
    k_file_path_to_write (str): Path to new K file to write.
    material_block_lines (list): List of strings for the material block (each line with newline).
    material_id (int): MID of the material.
    material_keyword (str): Top-level keyword for the material block (e.g., "*MAT_PLASTIC_KINEMATIC_TITLE").
    """
    print(f"\n--- Processing material block (Keyword: {material_keyword}, MID: {material_id}) ---")

    # --- Added sanitization step ---
    # Ensure all elements in material_block_lines are non-None strings
    cleaned_material_block_lines = []
    for line in material_block_lines:
        if line is not None:
            # Ensure it is a string; if not, try to convert, otherwise skip
            try:
                cleaned_material_block_lines.append(str(line))
            except Exception:
                print(f"WARNING: material_block_lines contains elements that cannot be converted to strings; skipped: {line}")
        else:
            print("WARNING: material_block_lines contains None values; skipped.")
    material_block_lines = cleaned_material_block_lines
    # --- End sanitization step ---

    try:
        with open(k_file_path_to_read, 'r', encoding='utf-8', errors='ignore') as f:
            original_lines = f.readlines()
    except FileNotFoundError:
        print(f"WARNING: Input file '{k_file_path_to_read}' does not exist. A new file will be created and content written.")
        original_lines = []
    except Exception as e:
        print(f"Error occurred while reading file '{k_file_path_to_read}': {e}")
        return False, "read_error"

    # Find existing block for target material and determine operation type
    target_block_start = -1
    target_block_end = -1
    operation_type = "append" # Default is append

    i = 0
    while i < len(original_lines):
        line = original_lines[i].strip().upper()
        # Compatible matching for keywords with and without _TITLE
        current_material_keyword_match = None
        
        # Match full keyword with _TITLE
        if line.startswith(material_keyword.upper()):
            current_material_keyword_match = material_keyword
        # If material_keyword itself has _TITLE, try matching without _TITLE (for old K files compatibility)
        elif material_keyword.upper().endswith('_TITLE') and line.startswith(material_keyword.upper().replace('_TITLE', '')):
            current_material_keyword_match = material_keyword.replace('_TITLE', '')
        # If material_keyword itself doesn't have _TITLE, try matching with _TITLE (for new K files or conversion)
        elif not material_keyword.upper().endswith('_TITLE') and line.startswith(material_keyword.upper() + '_TITLE'):
            current_material_keyword_match = material_keyword + '_TITLE'


        if current_material_keyword_match:
            current_block_start = i
            
            # Find data line containing MID (using robust logic suggested earlier)
            temp_j = i + 1
            while temp_j < len(original_lines):
                stripped_line = original_lines[temp_j].strip()
                if stripped_line.upper().startswith('$#') or not stripped_line: # Skip comment lines and empty lines
                    temp_j += 1
                else:
                    break # Found first non-empty non-comment line, assume it is MID data line
            
            # Check if temp_j points to a valid data line (not header), and contains MID
            if temp_j < len(original_lines):
                potential_mid_line = original_lines[temp_j]
                # Further ensure this is not another keyword line
                if not potential_mid_line.strip().upper().startswith('*') and len(potential_mid_line.strip()) > 0:
                    try:
                        current_mid_in_file = int(potential_mid_line[0:10].strip())
                        if current_mid_in_file == material_id:
                            target_block_start = current_block_start
                            # Find end position of this block: next keyword or end of file
                            j = i + 1 # Start searching after keyword
                            while j < len(original_lines):
                                check_line = original_lines[j].strip().upper()
                                if check_line.startswith('*') and not check_line.startswith('*COMMENT') and len(check_line) > 1:
                                    target_block_end = j
                                    break
                                j += 1
                            if target_block_end == -1: # If next keyword not found until end of file
                                target_block_end = len(original_lines)
                            
                            operation_type = "replace"
                            break # Found and marked for replacement, exit loop
                    except ValueError:
                        pass # Invalid MID format, skip
            
        i += 1
    
    final_lines = []

    if operation_type == "replace":
        print(f"Found '{material_keyword}' block with MID {material_id}. Content will be replaced.")
        final_lines = original_lines[:target_block_start] + material_block_lines + original_lines[target_block_end:]
    else:
        print(f"MID {material_id} for '{material_keyword}' block not found. New content will be appended.")
        # Insert after last *MAT_* block or before *END
        insert_idx = -1
        last_mat_block_end = -1

        # Search backwards for all *MAT_* keywords
        for k in range(len(original_lines) - 1, -1, -1):
            line = original_lines[k].strip().upper()
            if line.startswith('*MAT_') and not line.startswith('*MAT_TITLE'): # Usually material keyword is *MAT_XXX, not *MAT_TITLE 
                # Find end position of this material block
                j = k + 1
                while j < len(original_lines):
                    check_line = original_lines[j].strip().upper()
                    if check_line.startswith('*') and not check_line.startswith('*COMMENT') and len(check_line) > 1:
                        last_mat_block_end = j
                        break
                    j += 1
                if last_mat_block_end == -1:
                    last_mat_block_end = len(original_lines)
                break # Exit after finding last material block

        if last_mat_block_end != -1:
            insert_idx = last_mat_block_end
            print(f"Appending new material block after the last material block (line {insert_idx+1}).")
        else:
            # If no *MAT_* block exists, insert at end of file or before *END
            global_end_keyword_index = -1
            for k in range(len(original_lines) - 1, -1, -1):
                if original_lines[k].strip().upper() == '*END':
                    global_end_keyword_index = k
                    break

            if global_end_keyword_index != -1:
                insert_idx = global_end_keyword_index
                print(f"Inserting new material block before '*END' keyword (line {global_end_keyword_index+1}).")
            else:
                insert_idx = len(original_lines)
                print("Appending new material block to the end of the file.")

        final_lines = original_lines[:insert_idx] + material_block_lines + original_lines[insert_idx:]

    return _write_k_file_from_lines(k_file_path_to_write, final_lines)
    
def add_material_rebar_or_concrete(k_file_path_to_read, k_file_path_to_write, material_type: str, mid: int = None, material_title: str = None, parameters: dict = None,
                                     gui_output_func=None, gui_get_input_func=None, gui_ask_yes_no_func=None, gui_log_func=None):
    """
    Add or modify material definitions in the K file based on the selected material type (rebar or concrete).
    This function now accepts parameters provided by LLM, reducing interactive input.
    
    Parameters:
    k_file_path_to_read (str): Path to original LS-DYNA K file.
    k_file_path_to_write (str): Path to save modified LS-DYNA K file.
    material_type (str): Material type to add, 'rebar' or 'concrete'.
    mid (int, optional): Material ID. If not provided by LLM, will ask interactively via gui_get_input_func.
    material_title (str, optional): Material title. If not provided by LLM, will ask interactively via gui_get_input_func.
    parameters (dict, optional): Dictionary of material parameters. If not provided by LLM, will use defaults and ask for modification interactively.
    gui_output_func (callable, optional): Function to send output to GUI (e.g., gui.display_chat_message).
                                           Accepts (message, sender_tag) arguments.
    gui_get_input_func (callable, optional): Function to get string input from GUI (e.g., gui._get_user_input_gui).
                                              Accepts (title, prompt, default_val) arguments.
    gui_ask_yes_no_func (callable, optional): Function to get yes/no input from GUI (e.g., gui._ask_yes_no_gui).
                                               Accepts (title, prompt) arguments.
    """
    # Ensure callback functions exist; if not, fallback to standard print/input (mainly for testing or non-GUI environments)
    _output = gui_output_func if gui_output_func else lambda msg, sender_tag="tool_output": print(msg)
    _get_input = gui_get_input_func if gui_get_input_func else lambda title, prompt, default_val=None: input(f"{title}: {prompt} [{default_val}]: ") if default_val is not None else input(f"{title}: {prompt}")
    _ask_yes_no = gui_ask_yes_no_func if gui_ask_yes_no_func else lambda title, prompt: input(f"{title}: {prompt} (y/n)? ").lower() == 'y'

    material_block_lines = []
    material_keyword = ""
    
    # Define default parameters and format
    if material_type == 'rebar':
        material_keyword = "*MAT_PLASTIC_KINEMATIC_TITLE"
        material_title_default = "rebar-G40"
        
        default_params = {
            "ro": "17.83000E-9", 
            "e": "200000.0",
            "pr": "0.3",
            "sigy": "414.0",
            "etan": "600.0",
            "beta": "0.0",
            "src": "0.0",
            "srp": "0.0",
            "fs": "0.2",
            "vp": "0.0"
        }
        
        _output(f"\n--- Setting up rebar material ---", "tool_output")
        mid = mid if mid is not None else int(_get_input("Rebar Material ID", "Please enter Rebar Material ID (mid): "))
        material_title = material_title if material_title is not None else _get_input("Rebar Material Title", f"Please confirm Rebar Material Title", default_val=material_title_default)
        
        final_params = default_params.copy()


        if not parameters or _ask_yes_no("Manually Modify Parameters", "Do you need to manually modify other parameters?"):
            _output("\nCurrent rebar material parameters are as follows:", "tool_output")
            _output(f"$#     mid        ro         e        pr      sigy      etan      beta", "tool_output")
            _output(f"{mid:>10} {float(final_params['ro']):>10.4E} {float(final_params['e']):>10.1f} {float(final_params['pr']):>10.1f} {float(final_params['sigy']):>10.1f} {float(final_params['etan']):>10.1f} {float(final_params['beta']):>10.1f}", "tool_output")
            _output(f"$#     src       srp        fs        vp", "tool_output")
            _output(f"{float(final_params['src']):>10.1f} {float(final_params['srp']):>10.1f} {float(final_params['fs']):>10.1f} {float(final_params['vp']):>10.1f}", "tool_output")
            _output(f"  ----------------------Parameter Meanings------------------------")
            _output(f"  ro (Density): {float(final_params['ro']):>10.4E} - Mass per unit volume of the material.", "tool_output")
            _output(f"  e (Elastic Modulus): {float(final_params['e']):>10.1f} - Measure of the material's resistance to elastic deformation, representing stiffness.", "tool_output")
            _output(f"  pr (Poisson's Ratio): {float(final_params['pr']):>10.1f} - Ratio of transverse strain to axial strain when the material is stressed in one direction.", "tool_output")
            _output(f"  sigy (Yield Strength): {float(final_params['sigy']):>10.1f} - Stress value at which the material begins to deform plastically.", "tool_output")
            _output(f"  etan (Tangent Modulus): {float(final_params['etan']):>10.1f} - Slope of the stress-strain curve in the plastic region after yield, reflecting hardening effect.", "tool_output")

            while True:
                param_name = _get_input("Modify Parameter", "Please enter the name of the parameter you want to modify (e.g., 'e' or 'sigy'), enter 'done' to finish: ").strip().lower()
                if param_name == 'done':
                    break
                if param_name in final_params:
                    new_value_str = _get_input("New Value", f"Please enter new value for {param_name}", default_val=final_params[param_name]).strip()
                    new_value = try_float(new_value_str)
                    if new_value is not None:
                        final_params[param_name] = str(new_value)
                        _output(f"Parameter {param_name} updated to {new_value}.", "tool_output")
                    else:
                        _output(f"'{new_value_str}' is not a valid number. Please try again.", "tool_output")
                else:
                    _output("Invalid parameter name. Please check spelling.", "tool_output")
        
        material_block_lines.append(f"{material_keyword}\n")
        material_block_lines.append(f"{material_title}\n")
        material_block_lines.append(f"$#     mid        ro         e        pr      sigy      etan      beta\n")
        material_block_lines.append(
            f"{mid:>10}{float(final_params['ro']):>10.4E}{float(final_params['e']):>10.1f}{float(final_params['pr']):>10.1f}{float(final_params['sigy']):>10.1f}{float(final_params['etan']):>10.1f}{float(final_params['beta']):>10.1f}\n"
        )
        material_block_lines.append(f"$#     src       srp        fs        vp\n")
        material_block_lines.append(
            f"{float(final_params['src']):>10.1f}{float(final_params['srp']):>10.1f}{float(final_params['fs']):>10.1f}{float(final_params['vp']):>10.1f}\n"
        )

    elif material_type == "concrete":
        material_keyword = "*MAT_CSCM_CONCRETE_TITLE"
        # Modify start: remove interactive input for title and MID, use default or passed values
        material_title_default = "test lsprepost"
        mid_default = 10

        _output("\n--- Setting up concrete material ---", "tool_output")
        
        # Use default values, no interactive query
        material_title = material_title if material_title is not None else material_title_default
        mid = mid if mid is not None else mid_default

        # Modify end

        default_params = {
            "ro": "2.4E-6",
            "nplot": "1",
            "incre": "0",
            "irate": "0",
            "erode": "0",
            "recov": "0",
            "itretrc": "0",
            "pred": "0",
            "fpc": "30",
            "dagg": "20",
            "units": "0",
        }
        
        final_params = default_params.copy()

        if not parameters or _ask_yes_no("Manually Modify Parameters", "Do you need to manually modify other parameters?"):
            _output("\nCurrent concrete material default parameters are as follows:", "tool_output")
            _output(f"*MAT_CSCM_CONCRETE_TITLE", "tool_output")
            _output(f"{material_title}", "tool_output")
            _output(f"$#     mid        ro     nplot     incre     irate     erode     recov   itretrc", "tool_output")
            _output(f"{mid:>10}{float(final_params['ro']):>10.1f}{int(final_params['nplot']):>10}{float(final_params['incre']):>10.1f}{int(final_params['irate']):>10}{float(final_params['erode']):>10.1f}{float(final_params['recov']):>10.1f}{int(final_params['itretrc']):>10}", "tool_output")
            _output(f"$#    pred", "tool_output")
            _output(f"{float(final_params['pred']):>10.1f}", "tool_output")
            _output(f"$#     fpc      dagg     units", "tool_output")
            _output(f"{float(final_params['fpc']):>10.1f}{float(final_params['dagg']):>10.1f}{int(final_params['units']):>10}", "tool_output")
            _output(f"  ----------------------Parameter Meanings------------------------")
            _output(f"  fpc (Compressive Strength): {float(final_params['fpc']):>10.4E} - Maximum stress the material can withstand under compressive load, reflecting its compressive capability.", "tool_output")
            _output(f"  dagg (Max Aggregate Size): {float(final_params['dagg']):>10.4E} - Maximum diameter of aggregate particles in the concrete, affecting mechanical properties and workability.", "tool_output")

            while True:
                param_name = _get_input("Modify Parameter", "Please enter the parameter name to modify (e.g., 'ro', 'fpc', enter 'done' to finish): ").strip().lower()
                if param_name == 'done':
                    break
                if param_name in final_params:
                    new_value = _get_input("New Value", f"Please enter new value for {param_name}", default_val=final_params[param_name]).strip()
                    try:
                        if param_name in ['nplot', 'irate', 'itretrc', 'units']:
                            int(new_value)
                        else:
                            float(new_value)
                        final_params[param_name] = new_value
                        _output(f"Parameter {param_name} updated to {new_value}.", "tool_output")
                    except ValueError:
                        _output(f"'{new_value}' is not a valid value for {param_name}. Please try again.", "tool_output")
                else:
                    _output(f"'{param_name}' is not a recognized or modifiable concrete material parameter.", "tool_output")
        
        material_block_lines.append(f"{material_keyword}\n")
        material_block_lines.append(f"{material_title}\n")
        
        material_block_lines.append(f"$#     mid        ro     nplot     incre     irate     erode     recov   itretrc\n")
        material_block_lines.append(
            f"{mid:>10}{float(final_params['ro']):>10.1f}{int(final_params['nplot']):>10}{float(final_params['incre']):>10.1f}{int(final_params['irate']):>10}{float(final_params['erode']):>10.1f}{float(final_params['recov']):>10.1f}{int(final_params['itretrc']):>10}\n"
        )
        material_block_lines.append(f"$#    pred\n")
        material_block_lines.append(
            f"{float(final_params['pred']):>10.1f}\n"
        )
        material_block_lines.append(f"$#     fpc      dagg     units\n")
        material_block_lines.append(
            f"{float(final_params['fpc']):>10.1f}{float(final_params['dagg']):>10.1f}{int(final_params['units']):>10}\n"
        )

    else:
        _output("Unknown material type. Operation cancelled.", "tool_output")
        return False, "unknown_material_type"

    success, msg = add_material_to_kfile(k_file_path_to_read, k_file_path_to_write, material_block_lines, mid, material_keyword)
    
    if success:
        _output(f"Material definition operation successful. Message: {msg}", "tool_output")
    else:
        _output(f"Material definition operation failed. Message: {msg}", "tool_output")
        
    return success, msg


def extract_part_list_from_kfile(k_file_path):
    """
    Extracts the title and PID of each part from the LS-DYNA K file and outputs the results.
    
    Args:
        k_file_path (str): Path to the K file.
        
    Returns:
        list: A list of dictionaries containing part info, each dictionary contains 'title' and 'pid'.
    """
    part_list = []
    
    try:
        # Try multiple encodings to read the file
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        lines = None
        for encoding in encodings:
            try:
                with open(k_file_path, 'r', encoding=encoding) as file:
                    lines = file.readlines()
                break
            except UnicodeDecodeError:
                continue
        
        if lines is None:
            # If all encodings fail, try binary mode
            with open(k_file_path, 'rb') as file:
                content = file.read()
                lines = content.decode('utf-8', errors='ignore').splitlines(True)
        
    except Exception as e:
        print(f"Error processing file: {e}")
        return part_list
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Find *PART keyword
        if line.startswith('*PART'):
            part_info = {}
            
            # Find title line - search forward from current line
            title_line = "Untitled"
            j = i + 1
            while j < len(lines):
                candidate = lines[j].strip()
                # Stop searching if the next keyword starts
                if candidate.startswith('*'):
                    break
                # Skip empty lines and comment lines
                if candidate and not candidate.startswith('$'):
                    if not candidate.startswith('$#'):  # Not a parameter line
                        title_line = candidate
                        break
                j += 1
            
            part_info['title'] = title_line
            
            # Find data line containing PID - first find pid title line, then take the next line
            pid_found = False
            j = i + 1
            while j < len(lines):
                data_line = lines[j].strip()
                
                # Stop searching if the next keyword starts
                if data_line.startswith('*'):
                    break
                
                # Find title line containing "pid"
                if data_line.startswith('$#') and 'pid' in data_line.lower():
                    # After finding pid title line, take the next line as data line
                    if j + 1 < len(lines):
                        pid_data_line = lines[j + 1].strip()
                        # Skip empty lines and comment lines
                        if pid_data_line and not pid_data_line.startswith('$'):
                            # Extract PID (first number)
                            numbers = re.findall(r'-?\d+', pid_data_line)
                            if numbers:
                                part_info['pid'] = int(numbers[0])
                                pid_found = True
                                break
                
                j += 1
            
            # If PID is successfully extracted, add to list
            if pid_found:
                part_list.append(part_info)
            
        i += 1
    
    return part_list

# --- Modify Part Title ---
# Adjust modify_part_title_interactive to directly modify a specified part
def modify_part_title_for_selected_part(k_file_path, part_list, target_pid):
    """
    Interactively modify the title of a specified part.
    
    Args:
        k_file_path (str): Path to the K file.
        part_list (list): List of parts.
        target_pid (int): The PID of the part chosen by the user to modify.
        
    Returns:
        list: Updated list of parts.
    """
    print(f"\n=== Modifying title for Part PID: {target_pid} ===")
    
    # Verify if PID exists
    pid_exists = any(part['pid'] == target_pid for part in part_list)
    if not pid_exists:
        print(f"❌LLM-Assistant: PID {target_pid} does not exist in the current part list.")
        return part_list

    # Ask for new title
    new_title = input("LLM-Assistant: Please enter the new name (Current title: {}): ".format(
        next((p['title'] for p in part_list if p['pid'] == target_pid), "N/A")
    )).strip()

    if not new_title:
        print("❌LLM-Assistant: Title cannot be empty. Skipping modification.")
        return part_list

    # Execute modification
    success = modify_part_title_in_kfile(k_file_path, target_pid, new_title)
    if success:
        print("✅ LLM-Assistant: Part title modified successfully!")
        
        # Update part list in memory
        for part in part_list:
            if part['pid'] == target_pid:
                part['title'] = new_title
                break
    else:
        print("LLM-Assistant: ❌ Part title modification failed.")
    
    print("\nModified part list (Updated PID: {} title):".format(target_pid))
    # Re-output list to show changes, but do not re-parse from file
    for part in part_list:
        print(f"  Part ID: {part['pid']}, Name: {part['title']}")

    return part_list

def modify_part_title_in_kfile(k_file_path, part_pid, new_title):
    """
    Modify the title of a specified part in the K file.
    
    Args:
        k_file_path (str): Path to the K file.
        part_pid (int): PID of the part to modify.
        new_title (str): New part title.
        
    Returns:
        bool: True if modification successful, False otherwise.
    """
    try:
        # Try multiple encodings to read the file
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        lines = None
        for encoding in encodings:
            try:
                with open(k_file_path, 'r', encoding=encoding) as file:
                    lines = file.readlines()
                break
            except UnicodeDecodeError:
                continue
        
        if lines == None:
            print("❌ Unable to read K file, encoding not supported")
            return False
        
        modified = False
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Find *PART keyword
            if line.startswith('*PART'):
                # Find data line containing PID
                pid_found = False
                part_pid_line_idx = -1
                
                j = i + 1
                while j < len(lines):
                    data_line = lines[j].strip()
                    
                    # Stop searching if the next keyword starts
                    if data_line.startswith('*'):
                        break
                    
                    # Find title line containing "pid"
                    if data_line.startswith('$#') and 'pid' in data_line.lower():
                        # After finding pid title line, take the next line as data line
                        if j + 1 < len(lines):
                            pid_data_line = lines[j + 1].strip()
                            # Skip empty lines and comment lines
                            if pid_data_line and not pid_data_line.startswith('$'):
                                # Extract PID (first number)
                                numbers = re.findall(r'-?\d+', pid_data_line)
                                if numbers and int(numbers[0]) == part_pid:
                                    pid_found = True
                                    part_pid_line_idx = j + 1
                                    break
                    j += 1
                
                # If target PID is found, modify its title
                if pid_found:
                    # Find title line - search forward from *PART line
                    title_line_idx = -1
                    k = i + 1
                    while k < part_pid_line_idx:  # Only search until PID data line
                        candidate = lines[k].strip()
                        # Skip empty lines and comment lines
                        if candidate and not candidate.startswith('$'):
                            if not candidate.startswith('$#'):  # Not a parameter line
                                title_line_idx = k
                                break
                        k += 1
                    
                    # Modify title line
                    if title_line_idx != -1:
                        old_title = lines[title_line_idx].strip()
                        # New title length limit is 80 characters (LS-DYNA standard)
                        truncated_title = new_title[:80]
                        lines[title_line_idx] = truncated_title + '\n'
                        modified = True
                        print(f"✅ Successfully modified title for part {part_pid}:")
                        print(f"   Old title: {old_title}")
                        print(f"   New title: {truncated_title}")
                        break  # Exit loop after finding and modifying
            
            i += 1
        
        if modified:
            # Write modified content
            with open(k_file_path, 'w', encoding='utf-8') as file:
                file.writelines(lines)
            return True
        else:
            print(f"❌ Part with PID {part_pid} not found")
            return False
        
    except Exception as e:
        print(f"❌ Error modifying part title: {e}")
        return False

# --- Generate temporary visualization cfile ---    
def _generate_temp_cfile_for_visualization(template_cfile_path, part_id, k_file_path):
    """
    Generate a new cfile from the template cfile, update the K file path and part ID, and save it to the same directory as the K file.
    This file will be named "_temp_visualization_command.cfile", and old files will be overwritten each time.
    
    Args:
        template_cfile_path (str): Path to template cfile.
        part_id (int/str): Part ID.
        k_file_path (str): Path to K file.
        
    Returns:
        str: Path to the newly generated cfile, or None if failed.
    """
    try:
        # Read original cfile template
        with open(template_cfile_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        # Check if file has enough lines
        if len(lines) < 5:
            print(f"Warning: Visualization cfile template '{template_cfile_path}' has insufficient lines, might be incomplete.")
            return None
        
        # Modify line 3 (index 2) - Replace K file path inside quotes or placeholder
        if len(lines) >= 3:
            line3 = lines[2]
            # Prioritize replacing user specified placeholder "KEYWORD_FILE_PATH_PLACEHOLDER"
            if "KEYWORD_FILE_PATH_PLACEHOLDER" in line3:
                new_line3 = line3.replace("KEYWORD_FILE_PATH_PLACEHOLDER", k_file_path)
            else: # If no placeholder, try replacing any path inside quotes
                match = re.search(r'"(.*?)"', line3)
                if match:
                    old_path = match.group(1)
                    new_line3 = line3.replace(old_path, k_file_path)
                else:
                    print(f"Warning: K-file path quotes or placeholder not found in line 3 of visualization cfile template, skipping modification. Original line: {line3.strip()}")
                    new_line3 = line3 # Keep original
            lines[2] = new_line3
        
        # Modify line 5 (index 4) - Replace number after +M
        if len(lines) >= 5:
            line5 = lines[4]
            # Use regex to match "+M number" format
            match = re.search(r'(\+M\s+)(\d+)', line5)
            if match:
                prefix = match.group(1)
                new_line5 = prefix + str(part_id)
                lines[4] = new_line5 + '\n'
            else:
                # If not matched, try replacing number directly
                numbers = re.findall(r'\d+', line5)
                if numbers:
                    old_num = numbers[0]
                    new_line5 = line5.replace(old_num, str(part_id), 1)
                    lines[4] = new_line5
                else:
                    print(f"Warning: '+M number' pattern not found in line 5 of visualization cfile template, skipping modification. Original line: {line5.strip()}")
        
        # Get directory of K file
        k_file_dir = os.path.dirname(k_file_path)
        # Generate new cfile path, fixed name and overwrite
        temp_cfile_name = "_temp_visualization_command.cfile" # Fixed filename
        temp_cfile_full_path = os.path.join(k_file_dir, temp_cfile_name)

        # Write modified content to new file (using 'w' mode overwrites)
        with open(temp_cfile_full_path, 'w', encoding='utf-8') as file:
            file.writelines(lines)
        
        print(f"✅ Temporary visualization cfile generated: {temp_cfile_full_path} (Overwritten old file)")
        return temp_cfile_full_path
        
    except Exception as e:
        print(f"Error generating visualization cfile: {e}")
        return None


# --- Run visualization cfile in lsprepost (Overlaps with Code B's generate_and_run_lsprepost_script, simpler version from Code A kept here) --- 
# To avoid confusion and maintain consistency, we will use the more robust `generate_and_run_lsprepost_script` from Code B.
# And make it accept cfile path instead of K file path and SID.
# Here `run_lsprepost_with_cfile` is modified to call a special mode of Code B's `generate_and_run_lsprepost_script`.
def run_lsprepost_with_cfile_visual(cfile_path, lsprepost_path):
    command_string = f'c="{cfile_path}"'
    print(f"\nLS-PrePost has started in the background showing the selected part. Please check its window content.")
    print(f"You do not need to manually close the LS-PrePost window to continue.")
    return run_lsprepost_command(lsprepost_path, command_string)

# --- New: Parse SECTION_BEAM info from K file ---
def _parse_sections_from_kfile(k_file_path):
    """
    Parse all *SECTION_BEAM or *SECTION_BEAM_TITLE block information from the K file.
    
    Returns:
        list: List of dictionaries, each dictionary represents a section block,
              e.g.: [{'secid': 1, 'title': 'Rebar_Sec1', 'ts1': 10.0, 'ts2': 5.0}, ...]
    """
    sections = []
    try:
        with open(k_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            upper_line = line.upper()
            
            # Match *SECTION_BEAM_TITLE
            if upper_line.startswith('*SECTION_BEAM_TITLE'):
                # Structure: KEYWORD, TITLE, $#, DATA1, $#, DATA2
                if i + 5 < len(lines): 
                    title = lines[i+1].rstrip('\n')
                    try:
                        secid = int(lines[i+3][0:10].strip())
                        ts1 = float(lines[i+5][0:10].strip())
                        ts2 = float(lines[i+5][10:20].strip())
                        sections.append({'secid': secid, 'title': title, 'ts1': ts1, 'ts2': ts2})
                    except (ValueError, IndexError):
                        pass # Ignore malformed blocks
                
                # Find next keyword, ensure skipping whole block
                k = i + 1
                while k < len(lines):
                    check_line = lines[k].strip()
                    if check_line.startswith('*') and not check_line.upper().startswith('*COMMENT') and len(check_line) > 1:
                        i = k - 1 # i will increment to k in next loop
                        break
                    k += 1
                if k == len(lines): # If end of file
                    i = k - 1
                
                i += 1
                continue

            # Match *SECTION_BEAM (no title, giving a default title)
            elif upper_line.startswith('*SECTION_BEAM') and not upper_line.endswith('_TITLE'):
                # Structure: KEYWORD, $#, DATA1, $#, DATA2
                if i + 4 < len(lines): 
                    title = "[Untitled]" # Default title
                    try:
                        secid = int(lines[i+2][0:10].strip())
                        ts1 = float(lines[i+4][0:10].strip())
                        ts2 = float(lines[i+4][10:20].strip())
                        sections.append({'secid': secid, 'title': title, 'ts1': ts1, 'ts2': ts2})
                    except (ValueError, IndexError):
                        pass # Ignore malformed blocks
                
                # Find next keyword, ensure skipping whole block
                k = i + 1
                while k < len(lines):
                    check_line = lines[k].strip()
                    if check_line.startswith('*') and not check_line.upper().startswith('*COMMENT') and len(check_line) > 1:
                        i = k - 1 # i will increment to k in next loop
                        break
                    k += 1
                if k == len(lines): # If end of file
                    i = k - 1

                i += 1
                continue
            i += 1
            
    except FileNotFoundError:
        # print(f"Warning: File '{k_file_path}' does not exist. Cannot parse sections.") # Handled by caller
        pass
    except Exception as e:
        print(f"Error parsing sections from file '{k_file_path}': {e}")
        
    return sections

# [New Function] Get formatted section info
def get_formatted_sections_info(k_file_path: str) -> str:
    """
    Parse all available section information (*SECTION_BEAM) from the K file and format it as a user-friendly string table.
    This function is non-interactive, used for LLM to directly fetch and display info.

    Args:
        k_file_path (str): Path to LS-DYNA K file.

    Returns:
        str: String containing formatted section information.
    """
    sections_data = _parse_sections_from_kfile(k_file_path)
    
    output = "LLM-Assistant: All available section (SECTION_BEAM) information in the file is as follows:\n"
    if sections_data:
        output += "  SecID | TITLE            | ts1   | ts2\n"
        output += "  ------|------------------|-------|-------\n"
        for sec in sections_data:
            title_display = sec.get('title', '').replace('\n', ' ')[:14].ljust(14) # Truncate and left align
            output += f"  {sec['secid']:<6} | {title_display} | {sec['ts1']:<5.1f} | {sec['ts2']:<5.1f}\n"
    else:
        output += "  No SECTION_BEAM sections found.\n"
    
    return output

# --- Modify and Rename: Extract existing material parameter info from K file --- 
def _parse_materials_from_kfile(k_file_path):
    """
    Extract material ID, title, and simplified keyword for all materials in the K file.
    This function only parses, does not print output.
    
    Args:
        k_file_path: Path to K file.
    
    Returns:
        list: List of dictionaries containing material info, each dictionary contains 'mid', 'title', 'keyword'.
    """
    materials = []
    
    try:
        with open(k_file_path, 'r', encoding='utf-8', errors='ignore') as file:
            lines = file.readlines()
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            upper_line = line.upper()

            # Match all *MAT_ keywords, but exclude *MAT_TITLE (as it's not an actual material card)
            if upper_line.startswith('*MAT_') and not upper_line == '*MAT_TITLE': 
                current_keyword_full = ""
                match_kw = re.match(r"(\*MAT_[A-Z0-9_]+)", upper_line)
                if match_kw:
                    current_keyword_full = match_kw.group(1) 

                    # Extract simplified material type keyword
                    base_keyword = current_keyword_full.replace('*MAT_', '')
                    if base_keyword.endswith('_TITLE'):
                        material_type_keyword = base_keyword[:-6] # Remove _TITLE
                    else:
                        material_type_keyword = base_keyword
                    
                    title = "" 
                    mid = None 
                    
                    j = i + 1 # Start from the line after keyword

                    # 1. Try to extract TITLE (if keyword has _TITLE suffix)
                    if current_keyword_full.endswith('_TITLE'):
                        if j < len(lines):
                            potential_title_line = lines[j].strip()
                            # Title line cannot be comment, nor data line starting with number
                            if not potential_title_line.upper().startswith('$#') and potential_title_line and \
                               not re.match(r"^\s*[-+]?\d", potential_title_line): 
                                title = potential_title_line
                                j += 1 # Skip title line
                    
                    # 2. Skip all comment lines ($#)
                    while j < len(lines) and lines[j].strip().upper().startswith('$#'):
                        j += 1
                    
                    # 3. Extract MID (j should now point to data line containing MID)
                    if j < len(lines):
                        data_line = lines[j].rstrip('\n') 
                        
                        if len(data_line) >= 10:
                            mid_str = data_line[0:10].strip() 
                            try:
                                mid = int(mid_str) 
                            except ValueError:
                                mid = None 
                        else:
                            mid = None
                    
                    if mid is not None: 
                        materials.append({'mid': mid, 'title': title, 'keyword': material_type_keyword})
                    
                    # 4. Determine end of current material block, and set main loop `i` to start of next keyword
                    k = j # Start search for next keyword from MID data line (or after)
                    while k < len(lines):
                        check_line = lines[k].strip()
                        if check_line.startswith('*') and not check_line.upper().startswith('*COMMENT') and len(check_line) > 1:
                            i = k # Set i to line number of next keyword
                            break
                        k += 1
                    
                    if k == len(lines): # If loop to end of file without finding next keyword, this is the last material block
                        i = len(lines) # Set i to end of file to end main loop
                        
                    continue # After processing a material block, proceed directly to next main loop iteration, do not execute i += 1
                
            i += 1 # If current line is not a keyword, increment normally
            
    except FileNotFoundError:
        # print(f"Warning: File '{k_file_path}' does not exist. Cannot parse materials.") # Handled by caller
        pass
    except Exception as e:
        print(f"Error parsing materials from file '{k_file_path}': {e}")
        
    return materials

# [New Function] Get formatted material info
def get_formatted_materials_info(k_file_path: str) -> str:
    """
    Parse all available material (*MAT) information from the K file and format it as a user-friendly string table.
    This function is non-interactive, used for LLM to directly query and display info.

    Args:
        k_file_path (str): Path to LS-DYNA K file.

    Returns:
        str: String containing formatted material information.
    """
    materials_data = _parse_materials_from_kfile(k_file_path)
    
    output = "LLM-Assistant: All available material (MAT) information in the file is as follows:\n"
    if materials_data:
        # Print header line, ensure alignment
        output += f"{'  MID':<6} | {'TITLE':<18} | {'Keyword':<20}\n"
        output += f"{'------':<6} | {'------------------':<18} | {'--------------------':<20}\n"
        for mat in materials_data:
            # Format output, ensure title and keyword are truncated and aligned
            title_display = mat.get('title', '').replace('\n', ' ')[:16].ljust(16)
            keyword_display = mat.get('keyword', '').replace('\n', ' ')[:18].ljust(18)
            output += f"  {mat['mid']:<6} | {title_display} | {keyword_display}\n"
    else:
        output += "  No MAT materials found.\n"
    
    return output


# --- Generate temporary material assignment cfile (Updated to support assigning both material and section) --- 
def _generate_temp_cfile_for_assignment(template_cfile_path, k_file_path, part_id, material_id, section_id):
    """
    Generate a new cfile from the template cfile, update K-file path, part ID, material ID, section ID, and save to K-file directory.
    This file will be named "_temp_assignment_command.cfile", and old files will be overwritten each time.
    
    Args:
        template_cfile_path (str): Path to template cfile.
        k_file_path (str): Path to K file.
        part_id (int/str): Part ID.
        material_id (int/str): Material ID.
        section_id (int/str): Section ID.
        
    Returns:
        str: Path to newly generated cfile, or None if failed.
    """
    
    try:
        # Check if file exists
        if not os.path.exists(template_cfile_path):
            print(f"Error: Assignment cfile template '{template_cfile_path}' does not exist.")
            return None
        
        # Read original cfile template
        with open(template_cfile_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        # Check if file has enough lines
        if len(lines) < 10:
            print(f"Warning: Assignment cfile template '{template_cfile_path}' has insufficient lines, might be incomplete.")
        
        # Modify line 3 (index 2) - Replace K file path inside quotes or placeholder
        if len(lines) > 2:
            line3 = lines[2]
            # Prioritize replacing user specified placeholder "KEYWORD_FILE_PATH_PLACEHOLDER"
            if "KEYWORD_FILE_PATH_PLACEHOLDER" in line3:
                new_line3 = line3.replace("KEYWORD_FILE_PATH_PLACEHOLDER", k_file_path)
            else: # If no placeholder, try replacing any path inside quotes
                match = re.search(r'"(.*?)"', line3)
                if match:
                    old_path = match.group(1)
                    new_line3 = line3.replace(old_path, k_file_path)
                else:
                    print(f"Warning: K-file path quotes or placeholder not found in line 3 of assignment cfile template, skipping modification. Original line: {line3.strip()}")
                    new_line3 = line3 # Keep original
            lines[2] = new_line3
        
        # Modify line 5 (index 4) - Replace <PART_ID_PLACEHOLDER> or number after +M
        if len(lines) > 4:
            line5 = lines[4]
            if '<PART_ID_PLACEHOLDER>' in line5: # Prioritize replacing placeholder
                lines[4] = line5.replace('<PART_ID_PLACEHOLDER>', str(part_id))
            else: # If no placeholder, try replacing number
                match = re.search(r'(\+M\s+)(\d+)', line5)
                if match:
                    prefix = match.group(1)
                    lines[4] = prefix + str(part_id) + '\n'
                else:
                    print(f"Warning: '+M number' or '<PART_ID_PLACEHOLDER>' pattern not found in line 5 of assignment cfile template, skipping modification. Original line: {line5.strip()}")
        
        # Modify <PART_ID_PLACEHOLDER> or number in 'partdata readlist' command
        for idx, line in enumerate(lines):
            if 'partdata readlist' in line:
                if '<PART_ID_PLACEHOLDER>' in line: # Prioritize replacing placeholder
                    lines[idx] = line.replace('<PART_ID_PLACEHOLDER>', str(part_id))
                    break
                else: # If no placeholder, try replacing number
                    match = re.search(r'(partdata\s+readlist\s+)(\d+)', line)
                    if match:
                        prefix = match.group(1)
                        lines[idx] = prefix + str(part_id) + '\n'
                        break
                    else:
                        print(f"Warning: Number or '<PART_ID_PLACEHOLDER>' not found in 'partdata readlist' command in assignment cfile template, skipping modification. Original line: {line.strip()}")
                
        # Modify 'partdata assignapply' command
        assignapply_line_idx = -1
        for idx, line in enumerate(lines):
            if 'partdata assignapply' in line:
                assignapply_line_idx = idx
                break
        
        if assignapply_line_idx != -1:
            line_to_modify = lines[assignapply_line_idx]
            
            # Prioritize template with PLACEHOLDER
            if '<MATERIAL_ID_PLACEHOLDER>' in line_to_modify or \
               '<SECTION_ID_PLACEHOLDER>' in line_to_modify or \
               '<PART_ID_PLACEHOLDER>' in line_to_modify:
                
                if '<MATERIAL_ID_PLACEHOLDER>' in line_to_modify:
                    line_to_modify = line_to_modify.replace('<MATERIAL_ID_PLACEHOLDER>', str(material_id))
                else:
                    print(f"Warning: '<MATERIAL_ID_PLACEHOLDER>' not found in 'partdata assignapply' command.")

                if '<SECTION_ID_PLACEHOLDER>' in line_to_modify:
                    line_to_modify = line_to_modify.replace('<SECTION_ID_PLACEHOLDER>', str(section_id))
                else:
                    print(f"Warning: '<SECTION_ID_PLACEHOLDER>' not found in 'partdata assignapply' command.")
                
                if '<PART_ID_PLACEHOLDER>' in line_to_modify: # Last parameter is also part_id
                    line_to_modify = line_to_modify.replace('<PART_ID_PLACEHOLDER>', str(part_id))
                else:
                    print(f"Warning: Last '<PART_ID_PLACEHOLDER>' not found in 'partdata assignapply' command.")

                lines[assignapply_line_idx] = line_to_modify
                if not lines[assignapply_line_idx].endswith('\n'):
                    lines[assignapply_line_idx] += '\n'

            else: # If no PLACEHOLDER, use regex to replace numbers
                original_numbers_str = re.findall(r'(-?\d+)', line_to_modify)
                if len(original_numbers_str) >= 9:
                    modified_numbers = list(original_numbers_str)
                    modified_numbers[1] = str(part_id)
                    modified_numbers[2] = str(material_id)
                    modified_numbers[3] = str(section_id) 
                    modified_numbers[8] = str(part_id)
                    new_line = "partdata assignapply " + " ".join(modified_numbers) + '\n'
                    lines[assignapply_line_idx] = new_line
                else:
                    print(f"Warning: Insufficient parameters in 'partdata assignapply' command in assignment cfile template (at least 9 required), cannot modify. Original line: {line_to_modify.strip()}")
        else:
            print(f"Warning: 'partdata assignapply' command not found in assignment cfile template, skipping modification.")
            
        # Get directory of K file
        k_file_dir = os.path.dirname(k_file_path)
        # Generate new cfile path, fixed name and overwrite
        temp_cfile_name = "_temp_assignment_command.cfile" # Fixed filename
        temp_cfile_full_path = os.path.join(k_file_dir, temp_cfile_name)

        # Write modified content to new file (using 'w' mode overwrites)
        with open(temp_cfile_full_path, 'w', encoding='utf-8') as file:
            file.writelines(lines)
        
        print(f"✅ Temporary material assignment cfile generated: {temp_cfile_full_path} (Overwritten old file)")
        return temp_cfile_full_path
        
    except Exception as e:
        print(f"Error generating material assignment cfile: {e}")
        return None
    

# --- Run material assignment cfile in lsprepost (Overlaps with Code B's generate_and_run_lsprepost_script) --- 
# Here also modified to call Code B's `run_lsprepost_with_assignment_cfile` function to maintain consistency.
def run_lsprepost_with_assignment_cfile(assignment_cfile_path, lsprepost_path):
    command_string = f'"{assignment_cfile_path}"'
    print(f"\nLS-PrePost has started and executed the material/section assignment command stream. Please check its window content,")
    print(f"ensure the result is correct, manually save (File -> Save As... or Ctrl+S), then close the window to continue.")
    try:
        subprocess.run(f'"{lsprepost_path}" {command_string}', check=True, shell=True) # Use subprocess.run to block and wait for LS-PrePost to close
        print("✓ LS-PrePost execution completed~")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ LS-PrePost execution failed, please check path and cfile content. Error code: {e.returncode}")
        return False
    except FileNotFoundError:
        print(f"❌ Error: LS-PrePost executable not found. Please check path: {lsprepost_path}")
        return False


# The following are functions from the original tools.py, now modified to adapt to GUI output and interaction

def visualize_part_workflow(part_id, k_file_path, cfile_template_path_for_viz, lsprepost_path, 
                            gui_log_func, gui_display_chat_message_func, gui_ask_yes_no_func, gui_get_input_func):
    """
    Generate LS-PrePost command stream based on specified part ID and launch LS-PrePost to visualize the part.
    Args:
        part_id (int): Part ID to visualize.
        k_file_path (str): Full path to K file.
        cfile_template_path_for_viz (str): Path to visualization cfile template.
        lsprepost_path (str): Path to LS-PrePost executable.
        gui_log_func (function): Function to log info in GUI system log.
        gui_display_chat_message_func (function): Function to display messages in GUI chat terminal.
        gui_ask_yes_no_func (function): Function to show Yes/No dialog in GUI and get user input.
        gui_get_input_func (function): Function to show input dialog in GUI and get user input.
    Returns:
        tuple: (bool, str) Indicating success and related message.
    """
    gui_display_chat_message_func(f"\n=== LS-PrePost Part Visualization Workflow - Part PID: {part_id} ===\n", "system")
    gui_log_func(f"Start visualizing Part PID: {part_id}")

    # 1. Verify if part ID exists (optional, might be inefficient for large K files, but good for UX)
    part_list = extract_part_list_from_kfile(k_file_path) # Assuming this function returns part list
    if not any(p['pid'] == part_id for p in part_list):
        error_msg = f"❌ Part ID {part_id} does not exist in K file, cannot visualize."
        gui_display_chat_message_func(error_msg, "system")
        gui_log_func(error_msg, level="error")
        return False, error_msg
    
    # 2. Generate and use temporary visualization cfile
    temp_cfile_path_for_viz = _generate_temp_cfile_for_visualization(
        cfile_template_path_for_viz, part_id, k_file_path
    )
    if not temp_cfile_path_for_viz:
        error_msg = "❌ Failed to generate temporary visualization cfile."
        gui_display_chat_message_func(error_msg, "system")
        gui_log_func(error_msg, level="error")
        return False, error_msg

    gui_log_func(f"Temporary visualization cfile generated: {temp_cfile_path_for_viz} (Overwritten old file)")
    gui_display_chat_message_func("LS-PrePost has started in the background showing the selected part. Please check its window content.", "llm")
    gui_display_chat_message_func("You do not need to manually close the LS-PrePost window to continue.", "llm")
    gui_log_func("Calling LS-PrePost to execute command stream...")
    gui_log_func(f'"{lsprepost_path}" c="{temp_cfile_path_for_viz}"')

    run_lsprepost_with_cfile_visual(temp_cfile_path_for_viz, lsprepost_path)
    gui_log_func("✓ LS-PrePost started successfully.")
    gui_display_chat_message_func("LS-PrePost started successfully. Please confirm the part display in LS-PrePost, then click 'OK' to continue...", "llm")

    # Wait for user confirmation (LS-PrePost remains open)
    # Using gui_get_input_func to simulate input, but return value is not needed
    gui_get_input_func("LS-PrePost Confirmation", "Confirm part display in LS-PrePost is correct, then click OK to continue...")
    
    success_msg = f"✅ Successfully displayed Part PID {part_id} in LS-PrePost."
    gui_display_chat_message_func(success_msg, "llm")
    gui_log_func(success_msg)
    
    return True, success_msg


def assign_material_and_section_workflow(
    part_id, k_file_path, assignment_cfile_template_path, lsprepost_path, 
    gui_log_func, gui_display_chat_message_func, gui_ask_yes_no_func, gui_get_input_func, gui_show_message_func, modify_part_title_func,
    initial_material_id=0, initial_section_id=0
):
    """
    Start an interactive workflow allowing the user to modify the title of a specified part, and assign material and section to the part.
    The user will be guided step-by-step through title modification and material/section selection and assignment.
    This function will prompt the user for details via interactive command line.
    Args:
        part_id (int): Part ID to operate on.
        k_file_path (str): Full path to K file.
        assignment_cfile_template_path (str): Path to material assignment cfile template.
        lsprepost_path (str): Path to LS-PrePost executable.
        gui_log_func (function): Function to log info in GUI system log.
        gui_display_chat_message_func (function): Function to display messages in GUI chat terminal.
        gui_ask_yes_no_func (function): Function to show Yes/No dialog in GUI and get user input.
        gui_get_input_func (function): Function to show input dialog in GUI and get user input.
        gui_show_message_func (function): Function to show message dialog in GUI and wait for user confirmation.
        modify_part_title_func (function): Utility function to modify part title.
        initial_material_id (int): Initial material ID provided by LLM, prompts user if 0.
        initial_section_id (int): Initial section ID provided by LLM, prompts user if 0.
    Returns:
        tuple: (bool, str) Indicating success and related message.
    """
    gui_display_chat_message_func(f"\n=== LS-PrePost Part Material/Section Assignment Workflow - Part PID: {part_id} ===\n", "system")
    gui_log_func(f"Start material/section assignment workflow, Part PID: {part_id}")
    
    # Step 1: Extract part list to get current title
    part_list = extract_part_list_from_kfile(k_file_path)
    
    selected_part = next((p for p in part_list if p['pid'] == part_id), None)
    if not selected_part:
        error_msg = f"❌ Part ID {part_id} does not exist in K file, workflow terminated."
        gui_display_chat_message_func(error_msg, "system")
        gui_log_func(error_msg, level="error")
        return False, error_msg
    
    gui_display_chat_message_func(f"LLM-Assistant: Selected Part PID: {part_id}, Current Name: {selected_part['title']}", "llm")

    # 1. Ask whether to modify part title
    modify_title_choice = gui_ask_yes_no_func(f"Change Part Name", f"LLM-Assistant: Do you want to change the name (title) of Part PID {part_id}?")
    
    if modify_title_choice: # If user selects 'y'
        while True:
            new_title = gui_get_input_func("Enter New Name", f"Please enter the new name for Part PID {part_id}:")
            if new_title is None: # User cancelled input
                gui_display_chat_message_func("You have cancelled part name modification.", "system")
                gui_log_func("User cancelled part name modification.")
                # If user cancels title modification, can continue assignment or abort
                # Here we choose to abort the entire assignment workflow to avoid user misoperation without assigning material
                return False, "User cancelled modify part title operation."
            if new_title.strip() == "":
                gui_show_message_func("Input Error", "Part name cannot be empty, please re-enter.")
            else:
                success_modify = modify_part_title_func(k_file_path, part_list, part_id, new_title.strip())
                if success_modify:
                    # part_list updated in memory, and K file modified.
                    # Re-get updated selected_part to show latest title
                    selected_part = next((p for p in part_list if p['pid'] == part_id), None)
                    gui_display_chat_message_func(f"✅ Part title modified successfully! Modified title: {selected_part['title']}", "llm")
                    gui_log_func(f"Part PID {part_id} title modified successfully to: {selected_part['title']}")
                    break
                else:
                    gui_show_message_func("Modification Failed", f"Failed to modify title for Part PID {part_id}, please check K file permissions or content.")
                    gui_log_func(f"Failed to modify title for Part PID {part_id}.", level="error")
                    return False, f"Failed to modify title for Part PID {part_id}."
    else:
        gui_display_chat_message_func("LLM-Assistant: You chose not to change the part name.", "llm")
        gui_log_func("User chose not to change part name.")


    # 2. Perform material/section assignment operation
    gui_display_chat_message_func("\n--- Assign Material/Section Operation ---", "system")
    gui_log_func("Start material/section assignment operation.")

    # Display all available section and material info
    sections_info = get_formatted_sections_info(k_file_path)
    materials_info = get_formatted_materials_info(k_file_path)
    gui_display_chat_message_func(f"Defined section information in current K file:\n{sections_info}", "llm")
    gui_display_chat_message_func(f"Defined material information in current K file:\n{materials_info}", "llm")
    gui_log_func("Displayed existing section and material info to user.")

    # Ask user for section ID to assign
    section_id = initial_section_id
    current_sections = _parse_sections_from_kfile(k_file_path)

    if section_id == 0: # If LLM didn't provide or provided 0
        while True:
            section_id_input = gui_get_input_func(
                f"Select Section (PID {part_id})",
                f"LLM-Assistant: Please select the section to assign to Part PID {part_id}.\nEnter section ID (enter '0' if not modifying section):"
            )
            if section_id_input is None: # User cancelled
                gui_display_chat_message_func("You have cancelled section selection.", "system")
                gui_log_func("User cancelled section selection.")
                return False, "User cancelled operation."
            try:
                section_id = int(section_id_input)
                if section_id != 0 and not any(sec['secid'] == section_id for sec in current_sections):
                    gui_show_message_func("Input Error", f"Section ID {section_id} does not exist in K file, please re-enter.")
                    continue
                break
            except ValueError:
                gui_show_message_func("Input Error", "Please enter a valid numeric section ID or '0'.")
                continue
    else:
        # Verify if section_id provided by LLM is valid
        if not any(sec['secid'] == section_id for sec in current_sections):
            gui_display_chat_message_func(f"❌ LLM provided Section ID {section_id} does not exist in K file, will prompt you to re-enter.", "llm")
            gui_log_func(f"LLM provided Section ID {section_id} is invalid.", level="warning")
            section_id = 0 # Reset to 0, let user enter
            while True: # Re-prompt user
                section_id_input = gui_get_input_func(
                    f"Select Section (PID {part_id})",
                    f"LLM-Assistant: LLM provided Section ID {section_id} is invalid.\nPlease re-enter the section ID to assign to Part PID {part_id} (enter '0' if not modifying section):"
                )
                if section_id_input is None: # User cancelled
                    gui_display_chat_message_func("You have cancelled section selection.", "system")
                    gui_log_func("User cancelled section selection.")
                    return False, "User cancelled operation."
                try:
                    section_id = int(section_id_input)
                    if section_id != 0 and not any(sec['secid'] == section_id for sec in current_sections):
                        gui_show_message_func("Input Error", f"Section ID {section_id} does not exist in K file, please re-enter.")
                        continue
                    break
                except ValueError:
                    gui_show_message_func("Input Error", "Please enter a valid numeric section ID or '0'.")
                    continue
        else:
            gui_display_chat_message_func(f"LLM-Assistant: Selected Section ID: {section_id}", "llm")
            gui_log_func(f"Selected Section ID: {section_id}")


    # Ask user for material ID to assign
    material_id = initial_material_id
    current_materials = _parse_materials_from_kfile(k_file_path)

    if material_id == 0: # If LLM didn't provide or provided 0
        while True:
            material_id_input = gui_get_input_func(
                f"Select Material (PID {part_id})",
                f"LLM-Assistant: Please select the material to assign to Part PID {part_id}.\nEnter material ID (enter '0' if not modifying material):"
            )
            if material_id_input is None: # User cancelled
                gui_display_chat_message_func("You have cancelled material selection.", "system")
                gui_log_func("User cancelled material selection.")
                return False, "User cancelled operation."
            try:
                material_id = int(material_id_input)
                if material_id != 0 and not any(mat['mid'] == material_id for mat in current_materials):
                    gui_show_message_func("Input Error", f"Material ID {material_id} does not exist in K file, please re-enter.")
                    continue
                break
            except ValueError:
                gui_show_message_func("Input Error", "Please enter a valid numeric material ID or '0'.")
                continue
    else:
        # Verify if material_id provided by LLM is valid
        if not any(mat['mid'] == material_id for mat in current_materials):
            gui_display_chat_message_func(f"❌ LLM provided Material ID {material_id} does not exist in K file, will prompt you to re-enter.", "llm")
            gui_log_func(f"LLM provided Material ID {material_id} is invalid.", level="warning")
            material_id = 0 # Reset to 0, let user enter
            while True: # Re-prompt user
                material_id_input = gui_get_input_func(
                    f"Select Material (PID {part_id})",
                    f"LLM-Assistant: LLM provided Material ID {material_id} is invalid.\nPlease re-enter the material ID to assign to Part PID {part_id} (enter '0' if not modifying material):"
                )
                if material_id_input is None: # User cancelled
                    gui_display_chat_message_func("You have cancelled material selection.", "system")
                    gui_log_func("User cancelled material selection.")
                    return False, "User cancelled operation."
                try:
                    material_id = int(material_id_input)
                    if material_id != 0 and not any(mat['mid'] == material_id for mat in current_materials):
                        gui_show_message_func("Input Error", f"Material ID {material_id} does not exist in K file, please re-enter.")
                        continue
                    break
                except ValueError:
                    gui_show_message_func("Input Error", "Please enter a valid numeric material ID or '0'.")
                    continue
        else:
            gui_display_chat_message_func(f"LLM-Assistant: Selected Material ID: {material_id}", "llm")
            gui_log_func(f"Selected Material ID: {material_id}")

                
    # Generate temporary material assignment cfile
    temp_cfile_path_for_assign = _generate_temp_cfile_for_assignment(
        assignment_cfile_template_path, k_file_path, part_id, material_id, section_id
    )
    
    if not temp_cfile_path_for_assign:
        error_msg = "❌ Failed to generate temporary material assignment cfile."
        gui_display_chat_message_func(error_msg, "system")
        gui_log_func(error_msg, level="error")
        return False, error_msg
    
    gui_display_chat_message_func(f"✅ Temporary material assignment cfile generated: {temp_cfile_path_for_assign}", "llm")
    gui_log_func(f"Temporary material assignment cfile generated: {temp_cfile_path_for_assign}")

    # Call apply_cfile_with_lsprepost to execute CFILE and automatically save K file
    # Keep keep_open=True, so user can check results
    gui_display_chat_message_func(f"Starting LS-PrePost to execute material/section assignment command stream, and automatically saving the modified K file.", "llm")
    gui_log_func("Calling apply_cfile_with_lsprepost to execute assignment operation and save K file.")
    lsp_success, lsp_message = apply_cfile_with_lsprepost(
        lsprepost_exe_path=lsprepost_path,
        cfile_to_apply=temp_cfile_path_for_assign,
        final_save_k_path=k_file_path,  # Save to original K file path
        keep_open=True  # Keep LS-PrePost open for user to view
    )

    if lsp_success:
        success_msg = f"✅ Material/Section assignment for Part PID {part_id} successful! K file '{k_file_path}' has been automatically updated and saved. Please view results in LS-PrePost, then close LS-PrePost."
        gui_display_chat_message_func(success_msg, "llm")
        gui_log_func(f"Material/Section assignment operation successful. K file updated and saved. LS-PrePost is displaying the modified model.")
        
        # Wait for user confirmation (LS-PrePost remains open)
        gui_show_message_func("LS-PrePost Confirmation", "LS-PrePost has started and displays the updated model. Please check the results, then click OK and close the LS-PrePost window to continue.")

        return True, success_msg
    else:
        error_msg = f"❌ Failed to execute material/section assignment operation: {lsp_message}"
        gui_display_chat_message_func(error_msg, "system")
        gui_log_func(error_msg, level="error")
        return False, error_msg

