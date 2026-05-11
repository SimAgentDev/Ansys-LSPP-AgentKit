import tkinter as tk
import time
from tkinter import scrolledtext, messagebox, ttk, filedialog, simpledialog
import os
import json
import shutil
import threading
import sys
import re
import queue
from PIL import Image, ImageTk

# Import necessary components from other modules
from llm_interaction import LLMClientFactory, LLM_CONFIGS, call_llm
from description import TOOLS  # Import tools functionality from the first project
from tools import (
    extract_solid_element_nodes_and_save_node_data,
    find_specific_corner_node,
    normalize_model_direction,
    create_translation_cfile_from_corner_node,
    find_nodes_by_criteria,
    process_and_replace_nodeset_in_kfile,
    apply_cfile_with_lsprepost,
    generate_and_run_lsprepost_script,
    parse_k_file,
    add_boundary_spc_set_id,
    add_pulse_curve_to_kfile,
    add_load_node_set,
    extract_surface_nodes_workflow,
    add_nodes_to_existing_nodeset_by_criteria,
    parse_existing_nodes_from_set_node_list
)
# Import tools functionality from the second project
from tools import (
    llm_modify_rebar_section,
    llm_add_rebar_section,
    add_material_rebar_or_concrete,
    visualize_part_workflow,
    assign_material_and_section_workflow,
    get_formatted_sections_info,
    get_formatted_materials_info,
)
from utils import (
    try_float, RESET, BOLD, RED, YELLOW, BLUE, MAGENTA, CYAN, WHITE, HARDCODED_COLOR,
    prompt_yes_no, GENERAL_COORD_TOLERANCE
)

# The following are helper functions for material/section assignment and visualization from the original tools.py
# They need to be copied to GUI.py or ensured to be imported
# Here, to reduce external dependency modifications, we directly copy the function bodies
# This implementation is to ensure they can be imported here
def extract_part_list_from_kfile(k_file_path):
    """ Extract all PART information from K-file.
    Returns a list where each element is a dictionary containing 'pid' and 'title'.
    """
    parts = []
    current_part = {}
    with open(k_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        in_part_section = False
        for line in lines:
            if line.strip().startswith('*PART'):
                in_part_section = True
                current_part = {'pid': None, 'title': None}
            elif in_part_section and current_part['pid'] is None and line.strip() and not line.strip().startswith('$'):
                # This line should contain the PID (first 8 characters) and Title (after 8 characters)
                try:
                    current_part['pid'] = int(line[0:8])
                    current_part['title'] = line[8:].strip()
                    parts.append(current_part)
                    in_part_section = False  # Assumes one line per PART definition for simplicity
                except ValueError:
                    # Not a valid PART definition line, continue
                    pass
            elif in_part_section and line.strip().startswith('*SECTION_SHELL'):
                # If we hit another section, assume part section ended
                in_part_section = False
            elif in_part_section and line.strip().startswith('*MAT_ELASTIC'):
                in_part_section = False
            elif in_part_section and line.strip().startswith('*END'):
                in_part_section = False
    return parts

def _generate_temp_cfile_for_visualization(cfile_template_path, part_id, k_file_path):
    """ Generate a temporary cfile file based on template for displaying specified part in LS-PrePost.
    """
    output_dir = os.path.dirname(k_file_path)
    temp_cfile_path = os.path.join(output_dir, f"temp_viz_{part_id}.cfile")
    try:
        with open(cfile_template_path, 'r', encoding='utf-8') as f_template:
            template_content = f_template.read()
        modified_content = template_content.replace("{K_FILE_PATH}", k_file_path.replace("\\", "/"))
        modified_content = modified_content.replace("{PART_ID}", str(part_id))
        with open(temp_cfile_path, 'w', encoding='utf-8') as f_output:
            f_output.write(modified_content)
        return temp_cfile_path
    except Exception as e:
        print(f"Error generating temporary visualization cfile: {e}")
        return None

def _generate_temp_cfile_for_assignment(template_path, k_file_path, part_id, material_id, section_id):
    """ Generate a temporary cfile file based on template for assigning material and section in LS-PrePost.
    """
    output_dir = os.path.dirname(k_file_path)
    temp_cfile_path = os.path.join(output_dir, f"temp_assign_part_{part_id}.cfile")
    try:
        with open(template_path, 'r', encoding='utf-8') as f_template:
            template_content = f_template.read()
        modified_content = template_content.replace("{K_FILE_PATH}", k_file_path.replace("\\", "/"))
        modified_content = modified_content.replace("{PART_ID}", str(part_id))
        modified_content = modified_content.replace("{MATERIAL_ID}", str(material_id))
        modified_content = modified_content.replace("{SECTION_ID}", str(section_id))
        with open(temp_cfile_path, 'w', encoding='utf-8') as f_output:
            f_output.write(modified_content)
        return temp_cfile_path
    except Exception as e:
        print(f"Error generating temporary assignment cfile: {e}")
        return None

def run_lsprepost_with_cfile_visual(cfile_path, lsprepost_path):
    """ Launch LS-PrePost by running a CFILE script, keeping it open.
    This function only handles launching, does not wait for LS-PrePost to close.
    """
    command = f'"{lsprepost_path}" c="{cfile_path}"'
    try:
        # Use subprocess.Popen to launch LS-PrePost in background without blocking current program
        import subprocess
        subprocess.Popen(command, shell=True)
        return True
    except Exception as e:
        print(f"Failed to launch LS-PrePost: {e}")
        return False

def run_lsprepost_with_assignment_cfile(cfile_path, lsprepost_path):
    """ Launch LS-PrePost by running a CFILE script, keeping it open.
    This function only handles launching, does not wait for LS-PrePost to close.
    """
    command = f'"{lsprepost_path}" c="{cfile_path}"'
    try:
        import subprocess
        subprocess.Popen(command, shell=True)
        return True
    except Exception as e:
        print(f"Failed to launch LS-PrePost: {e}")
        return False

def modify_part_title_for_selected_part(k_file_path, part_list, target_part_id, new_title):
    """ Modify the title of specified part in K-file.
    Args:
        k_file_path (str): Full path to K-file.
        part_list (list): List of parts extracted from K-file.
        target_part_id (int): Part ID to modify title for.
        new_title (str): New part title.
    Returns:
        bool: Returns True if successfully modified and saved K-file, otherwise False.
    """
    lines = []
    with open(k_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    modified = False
    new_lines = []
    in_part_section = False
    for line in lines:
        if line.strip().startswith('*PART'):
            in_part_section = True
            new_lines.append(line)
        elif in_part_section and line.strip() and not line.strip().startswith('$'):
            try:
                current_pid = int(line[0:8])
                if current_pid == target_part_id:
                    new_part_line = f"{current_pid:<8}{new_title}\n"
                    new_lines.append(new_part_line)
                    modified = True
                    in_part_section = False
                else:
                    new_lines.append(line)
            except ValueError:
                new_lines.append(line)
        elif in_part_section and (line.strip().startswith('*SECTION_') or line.strip().startswith('*MAT_')):
            in_part_section = False
            new_lines.append(line)
        else:
            new_lines.append(line)
            in_part_section = False
    if modified:
        try:
            with open(k_file_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            for p in part_list:
                if p['pid'] == target_part_id:
                    p['title'] = new_title
                    break
            return True
        except Exception as e:
            print(f"Error saving modified K file: {e}")
            return False
    return False

def _parse_sections_from_kfile(k_file_path):
    """ Parse and return all section information from K-file.
    """
    sections = []
    current_section = {}
    with open(k_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        in_section = False
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith('*SECTION'):
                if current_section:
                    sections.append(current_section)
                current_section = {'type': stripped_line.replace('*SECTION_', ''), 'secid': None, 'title': ''}
                in_section = True
            elif in_section and not stripped_line.startswith('$'):
                if current_section['secid'] is None:
                    try:
                        current_section['secid'] = int(line[0:8].strip())
                        current_section['title'] = line[8:].strip()
                    except ValueError:
                        pass
            elif stripped_line.startswith('*END') or stripped_line.startswith('*PART') or stripped_line.startswith('*MAT_'):
                if in_section and current_section:
                    sections.append(current_section)
                    current_section = {}
                in_section = False
        if in_section and current_section:
            sections.append(current_section)
    return sections

def _parse_materials_from_kfile(k_file_path):
    """ Parse and return all material information from K-file.
    """
    materials = []
    current_material = {}
    with open(k_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        in_material = False
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith('*MAT_'):
                if current_material:
                    materials.append(current_material)
                current_material = {'type': stripped_line.replace('*MAT_', ''), 'mid': None, 'title': ''}
                in_material = True
            elif in_material and not stripped_line.startswith('$'):
                if current_material['mid'] is None:
                    try:
                        current_material['mid'] = int(line[0:8].strip())
                        current_material['title'] = line[8:].strip()
                    except ValueError:
                        pass
            elif stripped_line.startswith('*END') or stripped_line.startswith('*PART') or stripped_line.startswith('*SECTION_'):
                if in_material and current_material:
                    materials.append(current_material)
                    current_material = {}
                in_material = False
        if in_material and current_material:
            materials.append(current_material)
    return materials

# ------------------------------
# GUI Main Window Class
# ------------------------------
class APDLModelingGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("LS-DYNA K-File Modeling Assistant")
        self.root.geometry("1000x800")
        self.root.minsize(1000, 1000)
        self.default_font = ("Microsoft YaHei", 10)
        self.code_font = ("Consolas", 10)
        self.conversation_history = []
        self.llm_client = None
        self.available_llm_models = []
        self.available_llm_models_display = []
        self.selected_llm_model_name = None
        self.LSPREPOST_EXE_PATH = r"D:\LS-PrePost 4.6\lsprepost4.6_x64.exe"

        # 1. Dynamically get the folder path where the current script (e.g., GUI.py) is located
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 2. Set base path to current path
        self.base_cfile_dir = current_dir
        # 3. Keep filenames unchanged
        self.translation_cfile_template_name = "transit_modified_1.cfile"
        self.rotation_cfile_template_name = "rotate_modified_1.cfile"
        # 4. Use os.path.join to concatenate paths instead of hardcoded absolute paths
        self.cfile_template_for_viz_path = os.path.join(self.base_cfile_dir, "select_part.cfile")
        self.assignment_cfile_template_path = os.path.join(self.base_cfile_dir, "assignment_modified_1.cfile")

        self.translation_cfile_full_path = os.path.join(self.base_cfile_dir, self.translation_cfile_template_name)
        self.rotation_cfile_full_path = os.path.join(self.base_cfile_dir, self.rotation_cfile_template_name)

        self.current_k_file_path = ""
        self.original_k_file_path = ""
        self.solid_nodes_txt_filepath = ""
        self.surface_nodes_txt_filepath = ""

        self.node_sets_in_session = {}
        self.max_llm_iterations = 30
        self.iteration_count = 0
        self.llm_num_calls = 10
        self.llm_call_delay = 0.5
        self.is_initial_user_query = True

        self.initialization_steps = [
            {"num": 1.1, "name": "Initialize Model Direction", "id": "init_direction"},
            {"num": 1.2, "name": "Initialize Model Coordinates", "id": "init_coordinate"},
        ]
        self.initialization_step_codes = {
            step["id"]: False for step in self.initialization_steps
        }

        self.boundary_condition_steps = [
            {"num": 2.1, "name": "Fixed Boundary Conditions", "is_group": True, "id": None},
            {"num": 2.11, "name": "Select Nodes for Fixed Boundary", "id": "fix_boundary_step1"},
            {"num": 2.12, "name": "Add Boundary Nodes (Specific Y, Z=0)", "id": "add_specific_boundary_nodes"},
            {"num": 2.13, "name": "Apply Fixed Boundary to Selected Nodes", "id": "fix_boundary_step2"},
            {"num": 2.2, "name": "Pulse Load Setup", "is_group": True, "id": None},
            {"num": 2.21, "name": "Select Nodes for Pulse Load", "id": "pulse_load_step1"},
            {"num": 2.22, "name": "Set Pulse Curve (Y Direction)", "id": "pulse_load_step2"},
            {"num": 2.23, "name": "Apply Pulse Load with Nodes and Curve", "id": "pulse_load_step3"}
        ]
        self.boundary_task_completion_status = {
            step["id"]: False for step in self.boundary_condition_steps if step.get("id")
        }

        self.material_property_steps = [
            {"num": 3.1, "name": "Add or Modify Material Definition", "id": "material_step_1"},
            {"num": 3.2, "name": "Add or Modify Section Definition", "id": "material_step_2"},
            {"num": 3.3, "name": "Assign Material and Section to Part", "id": "material_step_3"},
        ]
        self.material_step_completion_status = {step["id"]: False for step in self.material_property_steps}

        self.last_selected_nodes_for_fixed_boundary_sid = None
        self.last_selected_nodes_for_pulse_load_sid = None
        self.last_created_pulse_curve_lcid = None

        self.available_functions_map = {
            "extract_solid_element_nodes_and_save_node_data": extract_solid_element_nodes_and_save_node_data,
            "find_specific_corner_node": find_specific_corner_node,
            "normalize_model_direction": normalize_model_direction,
            "create_translation_cfile_from_corner_node": create_translation_cfile_from_corner_node,
            "find_nodes_by_criteria": find_nodes_by_criteria,
            "process_and_replace_nodeset_in_kfile": process_and_replace_nodeset_in_kfile,
            "apply_cfile_with_lsprepost": apply_cfile_with_lsprepost,
            "generate_and_run_lsprepost_script": generate_and_run_lsprepost_script,
            "parse_k_file": parse_k_file,
            "add_boundary_spc_set_id": add_boundary_spc_set_id,
            "add_pulse_curve_to_kfile": add_pulse_curve_to_kfile,
            "add_load_node_set": add_load_node_set,
            "extract_surface_nodes_workflow": extract_surface_nodes_workflow,
            "add_nodes_to_existing_nodeset_by_criteria": add_nodes_to_existing_nodeset_by_criteria,
            "parse_existing_nodes_from_set_node_list": parse_existing_nodes_from_set_node_list,

            "llm_modify_rebar_section": llm_modify_rebar_section,
            "llm_add_rebar_section": llm_add_rebar_section,
            "add_material_rebar_or_concrete": add_material_rebar_or_concrete,
            "visualize_part_workflow": visualize_part_workflow,
            "assign_material_and_section_workflow": assign_material_and_section_workflow,
            "get_formatted_sections_info": get_formatted_sections_info,
            "get_formatted_materials_info": get_formatted_materials_info,
        }

        self.status_message_var = tk.StringVar(self.root, value="Ready")
        self.category_frames = {} 

        self.gif_configs = []

        self.init_ui()
        self._initialize_llm_model_list()
        self._check_template_paths()

        for gif_config in self.gif_configs:
            self._load_and_animate_gif_player(gif_config)

        self.update_initialization_steps_display()
        self.update_boundary_task_list_display()
        self.update_material_property_steps_display()

        self.log("Welcome to LS-DYNA K-File Modeling Assistant! Please first select an LLM model, then load a K-file to operate in the 'Chat Interaction' tab.", level="info")


    def _check_template_paths(self):
        """Check if necessary template files exist"""
        if not os.path.exists(self.translation_cfile_full_path):
            self.show_error("Configuration Error", f"Translation cfile template file does not exist: {self.translation_cfile_full_path}")
        if not os.path.exists(self.rotation_cfile_full_path):
            self.show_error("Configuration Error", f"Rotation cfile template file does not exist: {self.rotation_cfile_full_path}")
        if not os.path.exists(self.cfile_template_for_viz_path):
            self.show_error("Configuration Error", f"Visualization cfile template file does not exist: {self.cfile_template_for_viz_path}")
        if not os.path.exists(self.assignment_cfile_template_path):
            self.show_error("Configuration Error", f"Material assignment cfile template file does not exist: {self.assignment_cfile_template_path}")
        if not os.path.exists(self.LSPREPOST_EXE_PATH):
            self.show_warning("Configuration Warning", f"LS-PrePost executable path may be incorrect: {self.LSPREPOST_EXE_PATH}")
            self.show_error("Configuration Error", f"LS-PrePost executable path does not exist, unable to run LS-PrePost: {self.LSPREPOST_EXE_PATH}")

    def _load_and_animate_gif_player(self, gif_config):
        """Load all frames of a single GIF, scale to specified size, and start animation"""
        gif_path = gif_config["path"]
        target_size = gif_config["target_size"]
        gif_label = gif_config["label"]

        if not os.path.exists(gif_path):
            self.log(f"Error: GIF file does not exist: {gif_path}", level="error")
            if gif_label:
                gif_label.config(text="GIF file not found", image="")
            return

        try:
            gif_image = Image.open(gif_path)
            gif_config["frames"] = []
            gif_config["delays"] = []

            try:
                while True:
                    frame = gif_image.copy()
                    frame.thumbnail(target_size, Image.LANCZOS)
                    gif_config["frames"].append(ImageTk.PhotoImage(frame))
                    gif_config["delays"].append(gif_image.info.get('duration', 100))
                    gif_image.seek(len(gif_config["frames"]))
            except EOFError:
                pass

            if not gif_config["frames"]:
                raise ValueError(f"GIF file '{gif_path}' failed to extract any frames.")

            gif_config["current_frame_index"] = 0
            self._update_gif_frame_player(gif_config)
            self.log(f"GIF file '{gif_path}' loaded successfully, {len(gif_config['frames'])} frames total, scaled to {target_size[0]}x{target_size[1]}.", level="info")

        except Exception as e:
            self.log(f"Failed to load or process GIF file '{gif_path}': {e}", level="error")
            if gif_label:
                gif_label.config(text=f"GIF loading failed: {e}", image="")

    def _update_gif_frame_player(self, gif_config):
        """Update current frame of GIF"""
        if not gif_config["frames"]:
            return
        gif_label = gif_config["label"]
        if not gif_label:
            return

        gif_label.config(image=gif_config["frames"][gif_config["current_frame_index"]])

        gif_config["current_frame_index"] = (gif_config["current_frame_index"] + 1) % len(gif_config["frames"])

        delay = gif_config["delays"][gif_config["current_frame_index"]]
        gif_config["animation_id"] = self.root.after(delay, lambda: self._update_gif_frame_player(gif_config))
    
    def init_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.chat_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.chat_frame, text="Chat Interaction")

        llm_control_frame = ttk.Frame(self.chat_frame)
        llm_control_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(llm_control_frame, text="Select LLM Model:").pack(side=tk.LEFT, padx=5)
        self.llm_model_var = tk.StringVar(self.root)
        self.llm_model_dropdown = ttk.Combobox(
            llm_control_frame,
            textvariable=self.llm_model_var,
            values=[],
            state="readonly",
            font=self.default_font
        )
        self.llm_model_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.llm_model_dropdown.bind("<<ComboboxSelected>>", self.on_llm_model_selected)

        self.init_llm_btn = ttk.Button(llm_control_frame, text="Initialize LLM", command=self.init_llm_client)
        self.init_llm_btn.pack(side=tk.LEFT, padx=5)

        kfile_control_frame = ttk.Frame(self.chat_frame)
        kfile_control_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(kfile_control_frame, text="K-File Path:").pack(side=tk.LEFT, padx=5)
        self.k_file_path_entry = ttk.Entry(kfile_control_frame, font=self.default_font)
        self.k_file_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.browse_k_file_btn = ttk.Button(kfile_control_frame, text="Browse...", command=self.browse_k_file)
        self.browse_k_file_btn.pack(side=tk.LEFT, padx=5)

        self.set_k_file_btn = ttk.Button(kfile_control_frame, text="Confirm K-File", command=self.set_k_file_path_for_llm)
        self.set_k_file_btn.pack(side=tk.LEFT, padx=5)

        # ====================================================================================================
        # START OF MODIFICATION: Move task overview out of tabs and fix it at the top
        # ====================================================================================================

        self.tasks_overview_frame = ttk.LabelFrame(self.chat_frame, text="Model Setup Task Overview - Please complete tasks in order", padding=(10, 5))
        self.tasks_overview_frame.pack(fill=tk.X, padx=5, pady=(5,0))
        self.tasks_overview_frame.grid_columnconfigure(0, weight=1)
        self.tasks_overview_frame.grid_columnconfigure(1, weight=1)
        self.tasks_overview_frame.grid_columnconfigure(2, weight=1)

        init_overview_subframe = ttk.Frame(self.tasks_overview_frame)
        init_overview_subframe.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        ttk.Label(init_overview_subframe, text="1. Model Initialization Steps:", font=(self.default_font[0], self.default_font[1], "bold")).pack(fill=tk.X, anchor=tk.W)
        self.initialization_steps_listbox = scrolledtext.ScrolledText(
            init_overview_subframe, wrap=tk.WORD, font=self.default_font, height=6
        )
        self.initialization_steps_listbox.pack(fill=tk.BOTH, expand=True, pady=(0,5))
        self.initialization_steps_listbox.config(state=tk.DISABLED)

        boundary_overview_subframe = ttk.Frame(self.tasks_overview_frame)
        boundary_overview_subframe.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        ttk.Label(boundary_overview_subframe, text="2. Boundary Condition Tasks:", font=(self.default_font[0], self.default_font[1], "bold")).pack(fill=tk.X, anchor=tk.W)
        self.boundary_tasks_listbox = scrolledtext.ScrolledText(
            boundary_overview_subframe, wrap=tk.WORD, font=self.default_font, height=6
        )
        self.boundary_tasks_listbox.pack(fill=tk.BOTH, expand=True, pady=(0,5))
        self.boundary_tasks_listbox.config(state=tk.DISABLED)

        material_overview_subframe = ttk.Frame(self.tasks_overview_frame)
        material_overview_subframe.grid(row=0, column=2, padx=5, pady=5, sticky="nsew")
        ttk.Label(material_overview_subframe, text="3. Material Properties and Section Tasks:", font=(self.default_font[0], self.default_font[1], "bold")).pack(fill=tk.X, anchor=tk.W)
        self.material_steps_listbox = scrolledtext.ScrolledText(
            material_overview_subframe, wrap=tk.WORD, font=self.default_font, height=6
        )
        self.material_steps_listbox.pack(fill=tk.BOTH, expand=True, pady=(0,5))
        self.material_steps_listbox.config(state=tk.DISABLED)


        self.task_notebook = ttk.Notebook(self.chat_frame)
        self.task_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0,5)) 

        self.init_tab_frame = ttk.Frame(self.task_notebook)
        self.boundary_tab_frame = ttk.Frame(self.task_notebook)
        self.material_tab_frame = ttk.Frame(self.task_notebook)

        self.task_notebook.add(self.init_tab_frame, text="1. Model Initialization")
        self.task_notebook.add(self.boundary_tab_frame, text="2. Boundary Conditions and Loads")
        self.task_notebook.add(self.material_tab_frame, text="3. Material Properties and Sections")


        # --- 1. Model Initialization Tab Content (Function Button Group) ---
        init_frame = ttk.LabelFrame(self.init_tab_frame, text="Model Initialization Operations (Click button for operation tips)", padding=(10, 5))
        init_frame.pack(fill=tk.X, padx=5, pady=(5, 2), anchor=tk.NW, expand=True)
        self.category_frames["Model Initialization"] = init_frame
        
        # Add explanatory text
        # Note: This text will be displayed in the "Model Initialization" tab on the main interface, not in a popup dialog.
        # If you want it to display in a popup dialog, you need to modify the _show_template_dialog function.
        # Here we assume you want it displayed directly in the tab.
        ttk.Label(init_frame, wraplength=500, justify=tk.LEFT, font=self.default_font, foreground="gray40").grid(
            row=0, column=0, columnspan=2, padx=5, pady=(0, 5), sticky="ew"
        )
        
        # Uniform width and use sticky="ew" to make buttons fill space
        ttk.Button(init_frame, text="Step 1.1: Initialize Direction", command=self._show_direction_hint, width=25).grid(row=1, column=0, padx=5, pady=2, sticky="ew")
        ttk.Button(init_frame, text="Step 1.2: Initialize Coordinates", command=self._show_coordinate_hint, width=25).grid(row=1, column=1, padx=5, pady=2, sticky="ew")
        init_frame.grid_columnconfigure(0, weight=1)
        init_frame.grid_columnconfigure(1, weight=1)
        # Ensure rows can also expand, especially rows containing Labels and Buttons
        init_frame.grid_rowconfigure(0, weight=0) # Explanatory text doesn't need much vertical space, but ensure it exists
        init_frame.grid_rowconfigure(1, weight=1) # Button row can expand


        # --- 2. Boundary Conditions and Loads Tab Content (Function Button Group) ---
        boundary_frame = ttk.LabelFrame(self.boundary_tab_frame, text="Boundary Conditions and Load Operations", padding=(10, 5))
        boundary_frame.pack(fill=tk.X, padx=5, pady=(5, 2), anchor=tk.NW, expand=True)
        self.category_frames["Boundary Conditions and Loads"] = boundary_frame
        
        boundary_frame.grid_columnconfigure(0, weight=1) # Only one column, so subframe will fill horizontally

        # 2.1 Fixed Boundary Conditions - Sub LabelFrame
        fixed_boundary_group_frame = ttk.LabelFrame(boundary_frame, text="2.1 Fixed Boundary Conditions (Click button for operation tips)", padding=(10, 5))
        fixed_boundary_group_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.category_frames["Fixed Boundary Conditions"] = fixed_boundary_group_frame
        # Uniform width and use sticky="ew" to make buttons fill space
        ttk.Button(fixed_boundary_group_frame, text="Step 2.11: Select Boundary Nodes", command=self._show_select_nodes_hint, width=25).grid(row=0, column=0, padx=5, pady=2, sticky="ew")
        ttk.Button(fixed_boundary_group_frame, text="Step 2.12: Add Boundary Nodes", command=self._show_add_boundary_nodes_hint, width=25).grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        ttk.Button(fixed_boundary_group_frame, text="Step 2.13: Fix Boundary", command=self._show_fix_boundary_hint, width=25).grid(row=0, column=2, padx=5, pady=2, sticky="ew")
        fixed_boundary_group_frame.grid_columnconfigure(0, weight=1)
        fixed_boundary_group_frame.grid_columnconfigure(1, weight=1)
        fixed_boundary_group_frame.grid_columnconfigure(2, weight=1)

        # 2.2 Pulse Load Setup - Sub LabelFrame
        pulse_load_group_frame = ttk.LabelFrame(boundary_frame, text="2.2 Pulse Load Setup (Click button for operation tips)", padding=(10, 5))
        pulse_load_group_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.category_frames["Pulse Load Setup"] = pulse_load_group_frame
        # Uniform width and use sticky="ew" to make buttons fill space
        ttk.Button(pulse_load_group_frame, text="Step 2.21: Select Pulse Nodes", command=self._show_select_pulse_nodes_hint, width=25).grid(row=0, column=0, padx=5, pady=2, sticky="ew")
        ttk.Button(pulse_load_group_frame, text="Step 2.22: Set Pulse Curve", command=self._show_set_pulse_curve_hint, width=25).grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        ttk.Button(pulse_load_group_frame, text="Step 2.23: Apply Pulse Load", command=self._show_apply_pulse_load_hint, width=25).grid(row=0, column=2, padx=5, pady=2, sticky="ew")
        pulse_load_group_frame.grid_columnconfigure(0, weight=1)
        pulse_load_group_frame.grid_columnconfigure(1, weight=1)
        pulse_load_group_frame.grid_columnconfigure(2, weight=1)
        
        # Ensure boundary_frame correctly manages row weights
        boundary_frame.grid_rowconfigure(0, weight=1)
        boundary_frame.grid_rowconfigure(1, weight=1)


        # --- 3. Material Properties and Sections Tab Content (Function Button Group) ---
        material_section_combined_frame = ttk.LabelFrame(self.material_tab_frame, text="Material Properties and Section Operations (Click button for operation tips)", padding=(10, 5))
        material_section_combined_frame.pack(fill=tk.X, padx=5, pady=(5, 5), anchor=tk.NW, expand=True)
        # Ensure columns of material_section_combined_frame can expand, which is crucial for internal button enlargement
        material_section_combined_frame.grid_columnconfigure(0, weight=1) 

        # Query and Visualization
        query_visualize_group_frame = ttk.LabelFrame(material_section_combined_frame, text="Query and Visualization (Use A, B, C commands to view existing guardrail information)", padding=(5, 5))
        query_visualize_group_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.category_frames["Query and Visualization (Use A, B, C commands to view existing guardrail information)"] = query_visualize_group_frame
        # Uniform width and use sticky="ew" to make buttons fill space
        ttk.Button(query_visualize_group_frame, text="A: Query Material Info", command=self._show_query_materials_hint, width=25).grid(row=0, column=0, padx=5, pady=2, sticky="ew")
        ttk.Button(query_visualize_group_frame, text="B: Query Section Info", command=self._show_query_sections_hint, width=25).grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        ttk.Button(query_visualize_group_frame, text="C: Visualize Part", command=self._show_visualize_part_hint, width=25).grid(row=0, column=2, padx=5, pady=2, sticky="ew")
        query_visualize_group_frame.grid_columnconfigure(0, weight=1)
        query_visualize_group_frame.grid_columnconfigure(1, weight=1)
        query_visualize_group_frame.grid_columnconfigure(2, weight=1)


        # Add and Assign Operations
        add_assign_group_frame = ttk.LabelFrame(material_section_combined_frame, text="Add and Assign Operations", padding=(5, 5))
        add_assign_group_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.category_frames["Add and Assign Operations"] = add_assign_group_frame
        
        # Place add and assign buttons horizontally with uniform width
        ttk.Button(add_assign_group_frame, text="Step 3.1: Add Concrete Material", command=self._show_add_concrete_material_hint, width=25).grid(row=0, column=0, padx=5, pady=2, sticky="ew")
        ttk.Button(add_assign_group_frame, text="Step 3.2: Add Rebar Material", command=self._show_add_rebar_material_hint, width=25).grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        ttk.Button(add_assign_group_frame, text="Step 3.3: Add Section", command=self._show_section_hint, width=25).grid(row=1, column=0, padx=5, pady=2, sticky="ew")
        ttk.Button(add_assign_group_frame, text="Step 3.4: Assign Material & Section to Part", command=self._show_assign_hint, width=25).grid(row=1, column=1, padx=5, pady=2, sticky="ew")
        
        add_assign_group_frame.grid_columnconfigure(0, weight=1)
        add_assign_group_frame.grid_columnconfigure(1, weight=1)
        add_assign_group_frame.grid_rowconfigure(0, weight=1)
        add_assign_group_frame.grid_rowconfigure(1, weight=1)

        # Ensure material_section_combined_frame correctly manages row weights
        material_section_combined_frame.grid_rowconfigure(0, weight=1)
        material_section_combined_frame.grid_rowconfigure(1, weight=1)

        # ====================================================================================================
        # END OF MODIFICATION: Task overview and tab placement order adjusted
        # ====================================================================================================


        ttk.Label(self.chat_frame, text="Terminal (LLM Interaction and Tool Output)", font=self.default_font, anchor=tk.W).pack(fill=tk.X, padx=5, pady=(5,0))
        self.response_history_display = scrolledtext.ScrolledText(
            self.chat_frame, wrap=tk.WORD, font=self.default_font, height=10
        )
        self.response_history_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0,2))
        self.response_history_display.config(state=tk.DISABLED)

        chat_input_container_frame = ttk.Frame(self.chat_frame)
        chat_input_container_frame.pack(fill=tk.X, padx=5, pady=(5,5))
        ttk.Label(chat_input_container_frame, text="User Input:", font=self.default_font, anchor=tk.W).pack(fill=tk.X)

        chat_input_frame = ttk.Frame(chat_input_container_frame)
        chat_input_frame.pack(fill=tk.X, padx=0, pady=(2,0))
        self.chat_input_entry = ttk.Entry(chat_input_frame, font=self.default_font)
        self.chat_input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.chat_input_entry.bind("<Return>", lambda e: self.send_chat_message())

        self.chat_send_btn = ttk.Button(chat_input_frame, text="Send", command=self.send_chat_message)
        self.chat_send_btn.pack(side=tk.RIGHT, padx=5)


        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="System Log")
        self.log_display = scrolledtext.ScrolledText(
            self.log_frame, wrap=tk.WORD, font=self.default_font
        )
        self.log_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_display.config(state=tk.DISABLED)

        self.status_bar = ttk.Label(self.root, textvariable=self.status_message_var, relief=tk.SUNKEN, anchor=tk.W, font=self.default_font)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.log_display.tag_config("info", foreground="blue")
        self.log_display.tag_config("warning", foreground="orange")
        self.log_display.tag_config("error", foreground="red", font=(self.default_font[0], self.default_font[1], "bold"))

        self.response_history_display.tag_config("user_tag", foreground="blue")
        self.response_history_display.tag_config("llm_tag", foreground="darkgreen")
        self.response_history_display.tag_config("system_tag", foreground="gray")
        self.response_history_display.tag_config("tool_input_tag", foreground="purple")
        self.response_history_display.tag_config("tool_output_tag", foreground="darkred")

        self.boundary_tasks_listbox.tag_config("group", font=(self.default_font[0], self.default_font[1], "bold"))
        self.boundary_tasks_listbox.tag_config("sub_group", font=(self.default_font[0], self.default_font[1], "bold"), foreground="darkblue")

        self.initialization_steps_listbox.tag_config("completed_task", foreground="black")
        self.initialization_steps_listbox.tag_config("incomplete_task", foreground="gray50")
        self.boundary_tasks_listbox.tag_config("completed_task", foreground="black")
        self.boundary_tasks_listbox.tag_config("incomplete_task", foreground="gray50")
        self.material_steps_listbox.tag_config("completed_task", foreground="black")
        self.material_steps_listbox.tag_config("incomplete_task", foreground="gray50")


    def _show_template_dialog(self, title, template_text, explanation=None):
        """Display a dialog containing template text and optional explanation with copy button"""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        if explanation:
            ttk.Label(dialog, text=explanation, wraplength=400, justify=tk.LEFT, font=self.default_font, foreground="gray40").pack(
                padx=10, pady=(5, 0)
            )

        ttk.Label(dialog, text="Please copy the following template to the chat input box and modify as needed:", font=self.default_font).pack(padx=10, pady=(5,0))

        text_widget = scrolledtext.ScrolledText(dialog, wrap=tk.WORD, font=self.code_font, height=5, width=60)
        text_widget.insert(tk.END, template_text)
        text_widget.config(state=tk.DISABLED)
        text_widget.pack(padx=10, pady=5)

        def copy_to_clipboard():
            self.root.clipboard_clear()
            self.root.clipboard_append(template_text)
            self.root.update()
            messagebox.showinfo("Copy Successful", "Template text has been copied to clipboard!")

        copy_btn = ttk.Button(dialog, text="Copy Template", command=copy_to_clipboard)
        copy_btn.pack(pady=5)

        close_btn = ttk.Button(dialog, text="Close", command=dialog.destroy)
        close_btn.pack(pady=5)

        dialog.update_idletasks()
        root_geometry = self.root.geometry().split('+')
        root_width, root_height = map(int, root_geometry[0].split('x'))
        root_x = int(root_geometry[1])
        root_y = int(root_geometry[2])

        dialog_width = dialog.winfo_width()
        dialog_height = dialog.winfo_height()

        x = root_x + (root_width // 2) - (dialog_width // 2)
        y = root_y + (root_height // 2) - (dialog_height // 2)

        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")

        dialog.focus_set()
        self.root.wait_window(dialog)


    # New integrated dialog function for coordinate input and template
    def _show_coordinate_input_and_template_dialog(self, title, explanation, template_prefix,
                                            default_xmin="", default_xmax="",
                                            default_ymin="", default_ymax="",
                                            default_zmin="", default_zmax=""):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False) # Don't allow resizing to maintain stable layout

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        if explanation:
            ttk.Label(main_frame, text=explanation, wraplength=450, justify=tk.LEFT, font=self.default_font, foreground="gray40").pack(
                padx=5, pady=(0, 5), anchor=tk.W
            )

        # --- Input Node Coordinate Range Section ---
        input_coord_frame = ttk.LabelFrame(main_frame, text="Input Node Coordinate Range", padding="10")
        input_coord_frame.pack(fill=tk.X, pady=(5, 10), padx=5)
        input_coord_frame.grid_columnconfigure(1, weight=1)
        input_coord_frame.grid_columnconfigure(3, weight=1)
        # Coordinate input fields
        fields = [
            ("X", tk.StringVar(value=str(default_xmin)), tk.StringVar(value=str(default_xmax))),
            ("Y", tk.StringVar(value=str(default_ymin)), tk.StringVar(value=str(default_ymax))),
            ("Z", tk.StringVar(value=str(default_zmin)), tk.StringVar(value=str(default_zmax))),
        ]

        for i, (axis, min_var, max_var) in enumerate(fields):
            ttk.Label(input_coord_frame, text=f"{axis} Min:").grid(row=i, column=0, padx=5, pady=2, sticky="w")
            ttk.Entry(input_coord_frame, textvariable=min_var, width=15, font=self.default_font).grid(row=i, column=1, padx=5, pady=2, sticky="ew")
            ttk.Label(input_coord_frame, text=f"{axis} Max:").grid(row=i, column=2, padx=5, pady=2, sticky="w")
            ttk.Entry(input_coord_frame, textvariable=max_var, width=15, font=self.default_font).grid(row=i, column=3, padx=5, pady=2, sticky="ew")
            
        # --- Select Boundary Node Coordinates (Template Display) Section ---
        template_frame = ttk.LabelFrame(main_frame, text="Generated Node Selection Template (Please copy to chat input box)", padding="10")
        template_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 5), padx=5)

        self.generated_template_text_widget = scrolledtext.ScrolledText(template_frame, wrap=tk.WORD, font=self.code_font, height=4, width=60)
        self.generated_template_text_widget.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)
        self.generated_template_text_widget.config(state=tk.DISABLED) # Initially disabled

        # Helper to parse float and handle empty/invalid input
        def parse_float_or_none(s):
            try:
                return float(s.strip()) if s.strip() else None
            except ValueError:
                return None

        def update_template_display():
            criteria_parts = []
            has_valid_input = False

            for axis, min_var, max_var in fields:
                min_val_str = min_var.get()
                max_val_str = max_var.get()

                min_val = parse_float_or_none(min_val_str)
                max_val = parse_float_or_none(max_val_str)

                if min_val is None and max_val is None:
                    continue
                
                has_valid_input = True # At least one axis has input

                if min_val is not None and max_val is not None:
                    if min_val == max_val:
                        criteria_parts.append(f"{axis} coordinate={min_val}")
                    elif min_val < max_val:
                        criteria_parts.append(f"{min_val}<{axis}<{max_val}")
                    else: # min_val > max_val, error state
                        self.generated_template_text_widget.config(state=tk.NORMAL)
                        self.generated_template_text_widget.delete(1.0, tk.END)
                        self.generated_template_text_widget.insert(tk.END, f"Error: Minimum value for {axis} axis cannot be greater than maximum value. Please correct.")
                        self.generated_template_text_widget.config(state=tk.DISABLED)
                        return
                elif min_val is not None:
                    criteria_parts.append(f"{axis} coordinate>{min_val}")
                elif max_val is not None:
                    criteria_parts.append(f"{axis} coordinate<{max_val}")
            
            self.generated_template_text_widget.config(state=tk.NORMAL)
            self.generated_template_text_widget.delete(1.0, tk.END)
            
            if not has_valid_input:
                self.generated_template_text_widget.insert(tk.END, "Please input coordinate range or precise value for at least one of X, Y, Z axes to generate template.")
            else:
                generated_template_str = f"{template_prefix}" + " ".join(criteria_parts) + " nodes"
                self.generated_template_text_widget.insert(tk.END, generated_template_str)
            
            self.generated_template_text_widget.config(state=tk.DISABLED)

        # Update template display initially
        update_template_display()

        # Bind Entry modification events to update template in real time
        for _, min_var, max_var in fields:
            min_var.trace_add("write", lambda *args: update_template_display())
            max_var.trace_add("write", lambda *args: update_template_display())

        def copy_template_to_clipboard():
            template_content = self.generated_template_text_widget.get(1.0, tk.END).strip()
            if template_content and not template_content.startswith("Error:") and not template_content.startswith("Please input at least"):
                self.root.clipboard_clear()
                self.root.clipboard_append(template_content)
                self.root.update()
                messagebox.showinfo("Copy Successful", "Template text has been copied to clipboard!")
            else:
                messagebox.showwarning("Copy Failed", "Cannot copy empty or error template text. Please check input.")

        button_frame = ttk.Frame(main_frame, padding="5")
        button_frame.pack(fill=tk.X, pady=5, padx=5)
        ttk.Button(button_frame, text="Copy Template to Clipboard", command=copy_template_to_clipboard).pack(side=tk.LEFT, expand=True, padx=5)
        ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, expand=True, padx=5)

        dialog.update_idletasks()
        # Center dialog
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        dialog.focus_set()
        self.root.wait_window(dialog)

    # New SID input and template generation dialog
    def _show_sid_input_and_template_dialog(self, title, explanation, template_base_text, default_sid=""):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        if explanation:
            ttk.Label(main_frame, text=explanation, wraplength=450, justify=tk.LEFT, font=self.default_font, foreground="gray40").pack(
                padx=5, pady=(0, 5), anchor=tk.W
            )

        # --- Input Node Set ID (SID) Section ---
        input_sid_frame = ttk.LabelFrame(main_frame, text="Input Node Set ID (SID)", padding="10")
        input_sid_frame.pack(fill=tk.X, pady=(5, 10), padx=5)
        input_sid_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(input_sid_frame, text="Node Set SID:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        sid_var = tk.StringVar(value=str(default_sid))
        sid_entry = ttk.Entry(input_sid_frame, textvariable=sid_var, width=20, font=self.default_font)
        sid_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        # --- Generated Template Text (Real-time Display) Section ---
        template_frame = ttk.LabelFrame(main_frame, text="Generated Template Text (Please copy to chat input box)", padding="10")
        template_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 5), padx=5)

        generated_template_text_widget = scrolledtext.ScrolledText(template_frame, wrap=tk.WORD, font=self.code_font, height=4, width=60)
        generated_template_text_widget.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)
        generated_template_text_widget.config(state=tk.DISABLED) # Initially disabled

        def update_template_display():
            current_sid_str = sid_var.get().strip()
            
            generated_template_text_widget.config(state=tk.NORMAL)
            generated_template_text_widget.delete(1.0, tk.END)

            if not current_sid_str:
                generated_template_text_widget.insert(tk.END, "Please input Node Set ID (SID) above to generate template text.")
                generated_template_text_widget.config(state=tk.DISABLED)
                return

            try:
                sid_value = int(current_sid_str)
                generated_template_str = template_base_text.format(sid=sid_value)
                generated_template_text_widget.insert(tk.END, generated_template_str)
            except ValueError:
                generated_template_text_widget.insert(tk.END, "Error: SID must be a valid integer. Please correct.")
            
            generated_template_text_widget.config(state=tk.DISABLED)

        # Update template display initially
        update_template_display()

        # Bind Entry modification event to update template in real time
        sid_var.trace_add("write", lambda *args: update_template_display())

        def copy_template_to_clipboard():
            template_content = generated_template_text_widget.get(1.0, tk.END).strip()
            if template_content and not template_content.startswith("Error:") and not template_content.startswith("Please input above"):
                self.root.clipboard_clear()
                self.root.clipboard_append(template_content)
                self.root.update()
                messagebox.showinfo("Copy Successful", "Template text has been copied to clipboard!")
            else:
                messagebox.showwarning("Copy Failed", "Cannot copy empty or error template text. Please check input.")

        button_frame = ttk.Frame(main_frame, padding="5")
        button_frame.pack(fill=tk.X, pady=5, padx=5)
        ttk.Button(button_frame, text="Copy Template to Clipboard", command=copy_template_to_clipboard).pack(side=tk.LEFT, expand=True, padx=5)
        ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, expand=True, padx=5)

        dialog.update_idletasks()
        # Center dialog
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        dialog.focus_set()
        self.root.wait_window(dialog)

    # ==== New Pulse Curve Coordinate Point Input Dialog Function ====
    def _show_pulse_curve_input_dialog(self, title, explanation, default_points=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        if explanation:
            ttk.Label(main_frame, text=explanation, wraplength=450, justify=tk.LEFT, font=self.default_font, foreground="gray40").pack(
                padx=5, pady=(0, 5), anchor=tk.W
            )

        input_points_frame = ttk.LabelFrame(main_frame, text="Input Pulse Curve Coordinate Points (Time, Force)", padding="10")
        input_points_frame.pack(fill=tk.X, pady=(5, 10), padx=5)
        input_points_frame.grid_columnconfigure(1, weight=1)
        input_points_frame.grid_columnconfigure(3, weight=1)

        if default_points is None:
            default_points = [[0, 0], [0.001, 1], [0.002, 0]]
        
        # Store StringVar for points
        point_vars = []
        for i in range(max(3, len(default_points))): 
            time_val = str(default_points[i][0]) if i < len(default_points) else ""
            force_val = str(default_points[i][1]) if i < len(default_points) else ""
            
            time_var = tk.StringVar(value=time_val)
            force_var = tk.StringVar(value=force_val)
            point_vars.append((time_var, force_var))

            ttk.Label(input_points_frame, text=f"Point {i+1} Time:").grid(row=i, column=0, padx=5, pady=2, sticky="w")
            ttk.Entry(input_points_frame, textvariable=time_var, width=15, font=self.default_font).grid(row=i, column=1, padx=5, pady=2, sticky="ew")
            ttk.Label(input_points_frame, text=f"Point {i+1} Force:").grid(row=i, column=2, padx=5, pady=2, sticky="w")
            ttk.Entry(input_points_frame, textvariable=force_var, width=15, font=self.default_font).grid(row=i, column=3, padx=5, pady=2, sticky="ew")
            
        template_frame = ttk.LabelFrame(main_frame, text="Generated Pulse Curve Template Text (Please copy to chat input box)", padding="10")
        template_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 5), padx=5)

        generated_template_text_widget = scrolledtext.ScrolledText(template_frame, wrap=tk.WORD, font=self.code_font, height=4, width=60)
        generated_template_text_widget.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)
        generated_template_text_widget.config(state=tk.DISABLED) # Initially disabled

        def parse_float_safe(s):
            try:
                return float(s.strip())
            except ValueError:
                return None

        # Modify here: Pass point_vars as parameter to update_template_display
        def update_template_display(points_data): 
            points_str_list = []
            error_message = None
            has_valid_point = False
            last_time = -float('inf')

            for time_var, force_var in points_data: # <--- Use points_data parameter
                time_str = time_var.get().strip()
                force_str = force_var.get().strip()

                if not time_str and not force_str:
                    continue # Skip empty rows

                time_val = parse_float_safe(time_str)
                force_val = parse_float_safe(force_str)

                if time_val is None or force_val is None:
                    error_message = "Error: Both time and force must be valid numbers. Please check all inputs."
                    break
                
                if time_val < last_time:
                    error_message = "Error: Time points must be increasing. Please check time inputs."
                    break
                
                last_time = time_val
                has_valid_point = True
                points_str_list.append(f"[{time_val}, {force_val}]")
            
            generated_template_text_widget.config(state=tk.NORMAL)
            generated_template_text_widget.delete(1.0, tk.END)

            if error_message:
                generated_template_text_widget.insert(tk.END, error_message)
            elif not has_valid_point:
                generated_template_text_widget.insert(tk.END, "Please input at least one valid coordinate point to generate template.")
            else:
                generated_template_str = f"Apply a pulse-time curve, curve coordinate points are: {', '.join(points_str_list)}"
                generated_template_text_widget.insert(tk.END, generated_template_str)
            
            generated_template_text_widget.config(state=tk.DISABLED)

        # Initial update and binding
        update_template_display(point_vars) # <--- Pass point_vars on initial call
        for time_var, force_var in point_vars:
            # Modify here: Use lambda expression in event binding to pass point_vars
            time_var.trace_add("write", lambda *args: update_template_display(point_vars)) 
            force_var.trace_add("write", lambda *args: update_template_display(point_vars))

    def _show_input_and_template_dialog(self, title, explanation, input_fields_config, template_format_string):
        """
        Display a general dialog allowing user to input multiple fields and update template text in real time based on input.
        
        Args:
            title (str): Dialog title.
            explanation (str): Explanation text at top of dialog.
            input_fields_config (list): List containing configuration for each input field.
                                        Each configuration is a tuple (label_text, default_value, expected_type, placeholder_name).
                                        expected_type can be int, float, str.
                                        placeholder_name is the key used in format_string.
            template_format_string (str): Template string with {placeholder_name} placeholders.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        if explanation:
            ttk.Label(main_frame, text=explanation, wraplength=450, justify=tk.LEFT, font=self.default_font, foreground="gray40").pack(
                padx=5, pady=(0, 5), anchor=tk.W
            )

        input_frame = ttk.LabelFrame(main_frame, text="Input Parameters", padding="10")
        input_frame.pack(fill=tk.X, pady=(5, 10), padx=5)
        input_frame.grid_columnconfigure(1, weight=1)

        field_vars = {} # Store StringVar and related info {placeholder_name: (StringVar, expected_type)}
        for i, (label_text, default_value, expected_type, placeholder_name) in enumerate(input_fields_config):
            ttk.Label(input_frame, text=f"{label_text}:").grid(row=i, column=0, padx=5, pady=2, sticky="w")
            
            var = tk.StringVar(value=str(default_value) if default_value is not None else "")
            entry = ttk.Entry(input_frame, textvariable=var, width=20, font=self.default_font)
            entry.grid(row=i, column=1, padx=5, pady=2, sticky="ew")
            field_vars[placeholder_name] = (var, expected_type)
            
        template_frame = ttk.LabelFrame(main_frame, text="Generated Template Text (Please copy to chat input box)", padding="10")
        template_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 5), padx=5)

        generated_template_text_widget = scrolledtext.ScrolledText(template_frame, wrap=tk.WORD, font=self.code_font, height=4, width=60)
        generated_template_text_widget.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)
        generated_template_text_widget.config(state=tk.DISABLED)

        def update_template_display():
            current_values = {}
            errors = []
            
            for placeholder_name, (var, expected_type) in field_vars.items():
                value_str = var.get().strip()
                
                # For non-string types, if empty, add error
                if not value_str and expected_type != str:
                    errors.append(f"Error: {placeholder_name} cannot be empty.")
                    current_values[placeholder_name] = "" # Ensure template formatting doesn't error
                    continue
                
                try:
                    if expected_type == int:
                        current_values[placeholder_name] = int(value_str)
                    elif expected_type == float:
                        current_values[placeholder_name] = float(value_str)
                    else: # str
                        current_values[placeholder_name] = value_str
                except ValueError:
                    errors.append(f"Error: {placeholder_name} must be valid {expected_type.__name__} type. Input '{value_str}' is invalid.")
                    current_values[placeholder_name] = "" # Ensure template formatting doesn't error

            generated_template_text_widget.config(state=tk.NORMAL)
            generated_template_text_widget.delete(1.0, tk.END)

            if errors:
                for error_msg in errors:
                    generated_template_text_widget.insert(tk.END, error_msg + "\n")
            else:
                try:
                    generated_template_str = template_format_string.format(**current_values)
                    generated_template_text_widget.insert(tk.END, generated_template_str)
                except KeyError as e:
                    generated_template_text_widget.insert(tk.END, f"Template formatting error: Missing placeholder {e}. Please check configuration.")
                except Exception as e:
                    generated_template_text_widget.insert(tk.END, f"Unknown error occurred during template generation: {e}")
            
            generated_template_text_widget.config(state=tk.DISABLED)

        # Initial update
        update_template_display()

        # Bind Entry changes to update template
        for _, (var, _) in field_vars.items():
            var.trace_add("write", lambda *args: update_template_display())

        def copy_template_to_clipboard():
            template_content = generated_template_text_widget.get(1.0, tk.END).strip()
            if template_content and not template_content.startswith("Error:") and not template_content.startswith("Template formatting error"):
                self.root.clipboard_clear()
                self.root.clipboard_append(template_content)
                self.root.update()
                messagebox.showinfo("Copy Successful", "Template text has been copied to clipboard!")
            else:
                messagebox.showwarning("Copy Failed", "Cannot copy empty or error template text. Please check input.")

        button_frame = ttk.Frame(main_frame, padding="5")
        button_frame.pack(fill=tk.X, pady=5, padx=5)
        ttk.Button(button_frame, text="Copy Template to Clipboard", command=copy_template_to_clipboard).pack(side=tk.LEFT, expand=True, padx=5)
        ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, expand=True, padx=5)

        dialog.update_idletasks()
        # Centering dialog
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        dialog.focus_set()
        self.root.wait_window(dialog)


    # Modify _show_direction_hint function to pass explanatory text
    def _show_direction_hint(self):
        template = "Initialize model direction"
        explanation = "Hint: This step rotates the initial model to a preset direction, providing a unified reference frame for subsequent coordinate-based node selection."
        self._show_template_dialog("Initialize Direction", template, explanation=explanation)

    def _show_coordinate_hint(self):
        template = "Initialize model coordinates"
        explanation = "Hint: This step moves the initial model to the coordinate origin, providing a unified reference frame for subsequent coordinate-based node selection."
        self._show_template_dialog("Initialize Coordinates", template, explanation=explanation)

    # Modify _show_select_nodes_hint function to call new integrated dialog
    def _show_select_nodes_hint(self):
        explanation = "Hint: This step selects pier nodes for fixing. After inputting X, Y, Z coordinate ranges, the template will be created automatically."
        
        # Default values
        default_ymin = "-1000"
        default_ymax = "-700"
        default_zmin = "0"
        default_zmax = "0"

        # Call new integrated dialog
        self._show_coordinate_input_and_template_dialog(
            "Select Boundary Node Coordinates",
            explanation=explanation,
            template_prefix="Select",
            default_ymin=default_ymin, default_ymax=default_ymax,
            default_zmin=default_zmin, default_zmax=default_zmax
        )

    # Modify _show_add_boundary_nodes_hint function to call new SID input dialog
    def _show_add_boundary_nodes_hint(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Boundary Nodes")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Explanation text
        explanation = "Hint: This step includes pier nodes not covered by initial screening into the fixed range. Please fill in the node set SID to add below, or use coordinate range input."
        ttk.Label(main_frame, text=explanation, wraplength=450, justify=tk.LEFT, font=self.default_font, foreground="gray40").pack(
            padx=5, pady=(0, 5), anchor=tk.W
        )

        # --- Original SID Input Section (保留原来的功能) ---
        input_sid_frame_original = ttk.LabelFrame(main_frame, text="Select nodes at ymin", padding="10")
        input_sid_frame_original.pack(fill=tk.X, pady=(5, 10), padx=5)
        input_sid_frame_original.grid_columnconfigure(1, weight=1)

        ttk.Label(input_sid_frame_original, text="Node Set SID:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        sid_var_original = tk.StringVar(value="1001")
        sid_entry_original = ttk.Entry(input_sid_frame_original, textvariable=sid_var_original, width=20, font=self.default_font)
        sid_entry_original.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        # Original template display
        template_frame_original = ttk.LabelFrame(input_sid_frame_original, text="Generated Template", padding="5")
        template_frame_original.grid(row=1, column=0, columnspan=2, padx=5, pady=(5, 0), sticky="ew")

        template_text_original = scrolledtext.ScrolledText(template_frame_original, wrap=tk.WORD, font=self.code_font, height=2, width=50)
        template_text_original.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)
        template_text_original.config(state=tk.DISABLED)

        def update_original_template():
            sid_str = sid_var_original.get().strip()
            template_text_original.config(state=tk.NORMAL)
            template_text_original.delete(1.0, tk.END)
            if sid_str:
                try:
                    sid_value = int(sid_str)
                    template_text_original.insert(tk.END, f"Select nodes at ymin and add to node set SID {sid_value}")
                except ValueError:
                    template_text_original.insert(tk.END, "Error: SID must be a valid integer.")
            else:
                template_text_original.insert(tk.END, "Please input SID.")
            template_text_original.config(state=tk.DISABLED)

        update_original_template()
        sid_var_original.trace_add("write", lambda *args: update_original_template())

        def copy_original_template():
            content = template_text_original.get(1.0, tk.END).strip()
            if content and not content.startswith("Error:") and not content.startswith("Please input"):
                self.root.clipboard_clear()
                self.root.clipboard_append(content)
                self.root.update()
                messagebox.showinfo("Copy Successful", "Template copied to clipboard!")
            else:
                messagebox.showwarning("Copy Failed", "Cannot copy invalid template.")

        ttk.Button(input_sid_frame_original, text="Copy Template", command=copy_original_template).grid(row=2, column=0, columnspan=2, pady=(5, 0))

        # --- Separator ---
        ttk.Separator(main_frame, orient='horizontal').pack(fill=tk.X, pady=10, padx=5)

        # --- New Coordinate Range Input Section (新增的功能) ---
        input_coord_frame = ttk.LabelFrame(main_frame, text="Input Node Coordinate Range", padding="10")
        input_coord_frame.pack(fill=tk.X, pady=(5, 10), padx=5)
        input_coord_frame.grid_columnconfigure(1, weight=1)
        input_coord_frame.grid_columnconfigure(3, weight=1)

        # Coordinate input fields
        fields = [
            ("X", tk.StringVar(value=""), tk.StringVar(value="")),
            ("Y", tk.StringVar(value=""), tk.StringVar(value="")),
            ("Z", tk.StringVar(value="0"), tk.StringVar(value="0")),
        ]

        for i, (axis, min_var, max_var) in enumerate(fields):
            ttk.Label(input_coord_frame, text=f"{axis} Min:").grid(row=i, column=0, padx=5, pady=2, sticky="w")
            ttk.Entry(input_coord_frame, textvariable=min_var, width=15, font=self.default_font).grid(row=i, column=1, padx=5, pady=2, sticky="ew")
            ttk.Label(input_coord_frame, text=f"{axis} Max:").grid(row=i, column=2, padx=5, pady=2, sticky="w")
            ttk.Entry(input_coord_frame, textvariable=max_var, width=15, font=self.default_font).grid(row=i, column=3, padx=5, pady=2, sticky="ew")

        # SID for coordinate range
        ttk.Label(input_coord_frame, text="Node Set SID:").grid(row=3, column=0, padx=5, pady=2, sticky="w")
        sid_var_coord = tk.StringVar(value="1001")
        sid_entry_coord = ttk.Entry(input_coord_frame, textvariable=sid_var_coord, width=20, font=self.default_font)
        sid_entry_coord.grid(row=3, column=1, padx=5, pady=2, sticky="ew")

        # Generated Template Display for coordinate range
        template_frame_coord = ttk.LabelFrame(input_coord_frame, text="Generated Template", padding="5")
        template_frame_coord.grid(row=4, column=0, columnspan=4, padx=5, pady=(5, 0), sticky="ew")

        template_text_coord = scrolledtext.ScrolledText(template_frame_coord, wrap=tk.WORD, font=self.code_font, height=3, width=50)
        template_text_coord.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)
        template_text_coord.config(state=tk.DISABLED)

        def parse_float_or_none(s):
            try:
                return float(s.strip()) if s.strip() else None
            except ValueError:
                return None

        def update_coord_template():
            criteria_parts = []
            has_valid_input = False
            current_sid_str = sid_var_coord.get().strip()

            for axis, min_var, max_var in fields:
                min_val = parse_float_or_none(min_var.get())
                max_val = parse_float_or_none(max_var.get())

                if min_val is None and max_val is None:
                    continue
                
                has_valid_input = True

                if min_val is not None and max_val is not None:
                    if min_val == max_val:
                        criteria_parts.append(f"{axis} coordinate={min_val}")
                    elif min_val < max_val:
                        criteria_parts.append(f"{min_val}<{axis}<{max_val}")
                    else:
                        template_text_coord.config(state=tk.NORMAL)
                        template_text_coord.delete(1.0, tk.END)
                        template_text_coord.insert(tk.END, f"Error: Min {axis} cannot be greater than Max {axis}.")
                        template_text_coord.config(state=tk.DISABLED)
                        return
                elif min_val is not None:
                    criteria_parts.append(f"{axis} coordinate>{min_val}")
                elif max_val is not None:
                    criteria_parts.append(f"{axis} coordinate<{max_val}")

            template_text_coord.config(state=tk.NORMAL)
            template_text_coord.delete(1.0, tk.END)

            if not has_valid_input:
                template_text_coord.insert(tk.END, "Please input coordinate range for at least one axis.")
            elif not current_sid_str:
                template_text_coord.insert(tk.END, "Please input Node Set ID (SID).")
            else:
                try:
                    sid_value = int(current_sid_str)
                    generated_template_str = f"Select " + " ".join(criteria_parts) + f" nodes and add to node set SID {sid_value}"
                    template_text_coord.insert(tk.END, generated_template_str)
                except ValueError:
                    template_text_coord.insert(tk.END, "Error: SID must be a valid integer.")

            template_text_coord.config(state=tk.DISABLED)

        update_coord_template()

        for _, min_var, max_var in fields:
            min_var.trace_add("write", lambda *args: update_coord_template())
            max_var.trace_add("write", lambda *args: update_coord_template())
        sid_var_coord.trace_add("write", lambda *args: update_coord_template())

        def copy_coord_template():
            content = template_text_coord.get(1.0, tk.END).strip()
            if content and not content.startswith("Error:") and not content.startswith("Please input"):
                self.root.clipboard_clear()
                self.root.clipboard_append(content)
                self.root.update()
                messagebox.showinfo("Copy Successful", "Template copied to clipboard!")
            else:
                messagebox.showwarning("Copy Failed", "Cannot copy invalid template.")

        ttk.Button(input_coord_frame, text="Copy Template", command=copy_coord_template).grid(row=5, column=0, columnspan=4, pady=(5, 0))

        # Close button
        button_frame = ttk.Frame(main_frame, padding="5")
        button_frame.pack(fill=tk.X, pady=5, padx=5)
        ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, expand=True, padx=5)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        dialog.focus_set()
        self.root.wait_window(dialog)


    def _show_fix_boundary_hint(self):
        template = "Fix node SID 1001"
        explanation = "Hint: This step fixes all 6 degrees of freedom (X, Y, Z, Rx, Ry, Rz) of the nodes. The system has recorded the SID from the previous step, no need to re-enter."
        self._show_template_dialog("Fix Boundary", template, explanation=explanation)

    # Modify _show_select_pulse_nodes_hint function to call new integrated dialog
    def _show_select_pulse_nodes_hint(self):
        explanation = "Hint: This step selects nodes for applying pulse load. Please input X, Y, Z coordinate ranges below, the template will be generated automatically."

        # Default values
        default_xmin = "3987.8"
        default_xmax = "4241.8"
        default_ymin = "" # Less than -100, so only maximum value
        default_ymax = "-100" 
        default_zmin = "508"
        default_zmax = "635"

        # Call new integrated dialog
        self._show_coordinate_input_and_template_dialog(
            "Select Pulse Load Node Coordinate Range",
            explanation=explanation,
            template_prefix="Select",
            default_xmin=default_xmin, default_xmax=default_xmax,
            default_ymin=default_ymin, default_ymax=default_ymax,
            default_zmin=default_zmin, default_zmax=default_zmax
        )

    # ==== Modify _show_set_pulse_curve_hint function to call new pulse curve input dialog ====
    def _show_set_pulse_curve_hint(self):
        explanation = "Hint: This step defines pulse curve load. The curve is formed by connecting discrete time-force (t-F) points (horizontal axis: time; vertical axis: force). Please enter coordinate points below, the system will generate template automatically."

        default_points = [[0, 0], [1, 240204], [5, 240204]]

        self._show_pulse_curve_input_dialog(
            "Set Pulse Curve",
            explanation=explanation,
            default_points=default_points
        )
    # ====================================================================

    def _show_apply_pulse_load_hint(self):
        template = "Apply recently selected nodes and recently created curve to pulse load in Y direction"
        explanation = "Hint: This step associates the pulse curve with selected nodes to form a pulse load case. Since LLM has memory function, you can directly describe requirements, or manually specify nodes and pulse number."
        self._show_template_dialog("Apply Pulse Load", template, explanation=explanation)

    def _show_material_hint(self):
        template = "Add or modify material definition (Please select specific material type)"
        self._show_template_dialog("Add/Modify Material Definition", template)

    def _show_add_concrete_material_hint(self):
        explanation = "Hint: This step adds a concrete material. Please fill in material ID and title then copy template. The system will create concrete material, then Agent will ask questions item by item to confirm parameters"
        input_fields_config = [
            ("Material Name", "CONCRETE", str, "material_name"),
            ("MAT_ID", "10", int, "mat_id"),
        ]
        template_format_string = "Add a concrete material named '{material_name}', MAT_ID is {mat_id}"
        self._show_input_and_template_dialog(
            "Add Concrete Material",
            explanation,
            input_fields_config,
            template_format_string
        )

    def _show_add_rebar_material_hint(self):
        explanation = "Hint: This step adds a rebar material. Please fill in material ID and title then copy template. The system will create rebar material, then Agent will ask questions item by item to confirm parameters."
        input_fields_config = [
            ("Material Name", "REBAR", str, "material_name"),
            ("MAT_ID", "20", int, "mat_id"),
        ]
        template_format_string = "Add a rebar material named '{material_name}', MAT_ID is {mat_id}"
        self._show_input_and_template_dialog(
            "Add Rebar Material",
            explanation,
            input_fields_config,
            template_format_string
        )

    def _show_section_hint(self):
        explanation = "Hint: This step adds a section. Please input section ID, name and thickness, Agent will create template based on this information."
        input_fields_config = [
            ("Section ID", "16", int, "SEC_ID"),
            ("Section Name", "rebar", str, "TITLE"),
            ("Thickness", "16.0", float, "thickness"),
        ]
        template_format_string = "Add a Section, SEC_ID is {SEC_ID}, TITLE is {TITLE}, thickness is {thickness}"
        self._show_input_and_template_dialog(
            "Add Section",
            explanation,
            input_fields_config,
            template_format_string
        )

    def _show_assign_hint(self):
        explanation = "Hint: Please select target PART_ID and specify MAT_ID and SEC_ID, the system will complete binding."
        input_fields_config = [
            ("MAT_ID", "20", int, "MAT_ID"),
            ("SEC_ID", "3", int, "SEC_ID"),
            ("PART_ID", "6", int, "PART_ID"),
        ]
        template_format_string = "Assign MAT_ID {MAT_ID} and SEC_ID {SEC_ID} to part with PART_ID {PART_ID}"
        self._show_input_and_template_dialog(
            "Assign Material and Section to Part",
            explanation,
            input_fields_config,
            template_format_string
        )

    def _show_query_materials_hint(self):
        template = "Query all defined materials"
        explanation = "Hint: This step queries all defined material information in the model."
        self._show_template_dialog("Query Material Information", template, explanation=explanation)

    def _show_query_sections_hint(self):
        template = "Display all section information"
        explanation = "Hint: This step queries all defined section information in the model."
        self._show_template_dialog("Query Section Information", template, explanation=explanation)

    def _show_visualize_part_hint(self):
        template = "Visualize part with PART_ID 5"
        explanation = "Hint: This step visualizes specified part in LS-PrePost."
        self._show_template_dialog("Visualize Part", template, explanation=explanation)

    def _initialize_llm_model_list(self):
        """Initialize LLM model list for dropdown selection"""
        self.available_llm_models = list(LLM_CONFIGS.keys())
        self.available_llm_models_display = [
            LLM_CONFIGS[model].get("display_name", model) for model in self.available_llm_models
        ]

        if self.available_llm_models_display:
            self.llm_model_dropdown['values'] = self.available_llm_models_display
            self.llm_model_var.set(self.available_llm_models_display[0])
            self.selected_llm_model_name = self.available_llm_models[0]
            self.log(f"LLM models selected: {', '.join(self.available_llm_models_display)}", level="info")
        else:
            self.llm_model_dropdown['values'] = ["(No available models)"]
            self.llm_model_var.set("(No available models)")
            self.selected_llm_model_name = None
            self.log("Warning: No LLM model configuration found in LLM_CONFIGS. Please check llm_interaction.py.", level="warning")

    def _remove_ansi_escape_codes(self, text):
        """Remove ANSI escape sequences from string."""
        if not isinstance(text, str):
            return text
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def log(self, message, level="info"):
        """Print log in system log panel and bottom status bar, and clean ANSI codes"""
        cleaned_message = self._remove_ansi_escape_codes(message)
        timestamp = time.strftime('%H:%M:%S')
        full_message = f"[{timestamp}] {cleaned_message}\n"
        self.log_display.config(state=tk.NORMAL)
        self.log_display.insert(tk.END, full_message, level)
        self.log_display.see(tk.END)
        self.log_display.config(state=tk.DISABLED)
        self.status_message_var.set(f"[{timestamp}] {cleaned_message}")
        self.root.update_idletasks()

    def display_chat_message(self, message, sender="system"):
        """Add message to chat history display and clean ANSI codes"""
        cleaned_message = self._remove_ansi_escape_codes(message)
        self.response_history_display.config(state=tk.NORMAL)
        if sender == "user":
            self.response_history_display.insert(tk.END, f"You: {cleaned_message}\n", "user_tag")
        elif sender == "llm":
            self.response_history_display.insert(tk.END, f"LLM Assistant: {cleaned_message}\n", "llm_tag")
        elif sender == "tool_input":
            self.response_history_display.insert(tk.END, f"LLM Assistant (Tool Call): {cleaned_message}\n", "tool_input_tag")
        elif sender == "tool_output":
            # --- START MODIFICATION ---
            # If message contains specific multiline output prefix, display complete message directly
            if cleaned_message.startswith("--- Setting Concrete Material ---") or \
               cleaned_message.startswith("--- Setting Rebar Material ---") or \
               "Current default parameters for concrete material:" in cleaned_message or \
               "Current parameters for rebar material:" in cleaned_message:
                self.response_history_display.insert(tk.END, f"Tool Result:\n{cleaned_message}\n", "tool_output_tag")
            else:
                # Otherwise, try parsing JSON or display regular message
                try:
                    json_data = json.loads(cleaned_message)
                    if isinstance(json_data, dict) and 'message' in json_data:
                        display_msg = f"Tool Result: {json_data['message']}\n"
                    else:
                        display_msg = f"Tool Result: {cleaned_message}\n"
                except json.JSONDecodeError:
                    display_msg = f"Tool Result: {cleaned_message}\n"
                self.response_history_display.insert(tk.END, display_msg, "tool_output_tag")
            # --- END MODIFICATION ---
        else:
            self.response_history_display.insert(tk.END, f"[System] {cleaned_message}\n", "system_tag")
        self.response_history_display.see(tk.END)
        self.response_history_display.config(state=tk.DISABLED)


    def show_info(self, title, message):
        """Display info dialog and clean ANSI codes"""
        cleaned_message = self._remove_ansi_escape_codes(message)
        messagebox.showinfo(title, cleaned_message)
        self.log(f"Info: {title} - {cleaned_message}")

    def show_warning(self, title, message):
        """Display warning dialog and clean ANSI codes"""
        cleaned_message = self._remove_ansi_escape_codes(message)
        messagebox.showwarning(title, cleaned_message)
        self.log(f"Warning: {title} - {cleaned_message}", level="warning")

    def show_error(self, title, message):
        """Display error dialog and clean ANSI codes"""
        cleaned_message = self._remove_ansi_escape_codes(message)
        messagebox.showerror(title, cleaned_message)
        self.log(f"Error: {title} - {cleaned_message}", level="error")

    def _get_user_input_gui(self, title, prompt, default_val=None):
        """
        Display an input dialog in GUI main thread and get user input.
        This function will block the calling thread (i.e., background tool thread) until user inputs or cancels in dialog.
        """
        q = queue.Queue()
        self.root.after(0, lambda: q.put(simpledialog.askstring(title, self._remove_ansi_escape_codes(prompt), initialvalue=self._remove_ansi_escape_codes(str(default_val)) if default_val is not None else "")))
        result = q.get()
        return result if result is not None else default_val

    def _ask_yes_no_gui(self, title, prompt):
        """
        Display a yes/no dialog in GUI main thread and get user choice.
        """
        q = queue.Queue()
        self.root.after(0, lambda: q.put(messagebox.askyesno(title, self._remove_ansi_escape_codes(prompt))))
        return q.get()

    def _show_message_gui_sync(self, title, message):
        """
        Display an info dialog in GUI main thread and wait for user confirmation.
        This is blocking and will pause the calling thread until user clicks "OK".
        """
        q = queue.Queue()
        self.root.after(0, lambda: q.put(messagebox.showinfo(title, self._remove_ansi_escape_codes(message))))
        q.get()

    def set_ui_state(self, enabled):
        """Enable or disable main UI controls based on enabled state."""
        state_str = tk.NORMAL if enabled else tk.DISABLED
        dropdown_state = "readonly" if enabled else tk.DISABLED

        self.llm_model_dropdown.config(state=dropdown_state)
        self.init_llm_btn.config(state=state_str)
        self.k_file_path_entry.config(state=state_str)
        self.browse_k_file_btn.config(state=state_str)
        self.set_k_file_btn.config(state=state_str)
        self.chat_input_entry.config(state=state_str)
        self.chat_send_btn.config(state=state_str)

        for category_frame_name, category_frame in self.category_frames.items():
            def _set_children_state(widget):
                for child in widget.winfo_children():
                    if isinstance(child, (ttk.Button, ttk.Entry, ttk.Combobox, scrolledtext.ScrolledText, tk.Listbox)):
                        if isinstance(child, ttk.Combobox):
                            child_state = "readonly" if enabled else tk.DISABLED
                        elif isinstance(child, tk.Listbox):
                            child_state = tk.NORMAL if enabled else tk.DISABLED
                        else:
                            child_state = state_str
                        try:
                            child.config(state=child_state)
                        except tk.TclError:
                            pass
                    _set_children_state(child)
            _set_children_state(category_frame)

        if hasattr(self, 'initialization_steps_listbox') and self.initialization_steps_listbox:
            self.initialization_steps_listbox.config(state=tk.NORMAL if enabled else tk.DISABLED)
        if hasattr(self, 'boundary_tasks_listbox') and self.boundary_tasks_listbox:
            self.boundary_tasks_listbox.config(state=tk.NORMAL if enabled else tk.DISABLED)
        if hasattr(self, 'material_steps_listbox') and self.material_steps_listbox:
            self.material_steps_listbox.config(state=tk.NORMAL if enabled else tk.DISABLED)


    def update_initialization_steps_display(self):
        """Update model initialization step list and mark completed steps with color support"""
        if not hasattr(self, 'initialization_steps_listbox') or self.initialization_steps_listbox is None:
            return
        self.initialization_steps_listbox.config(state=tk.NORMAL)
        self.initialization_steps_listbox.delete(1.0, tk.END)
        for step in self.initialization_steps:
            is_completed = self.initialization_step_codes.get(step["id"], False)
            status_char = "✓" if is_completed else " "
            display_text = f"[{status_char}] Step {step['num']}: {step['name']}\n"
            tag = "completed_task" if is_completed else "incomplete_task"
            self.initialization_steps_listbox.insert(tk.END, display_text, tag)
        self.initialization_steps_listbox.config(state=tk.DISABLED)

    def update_boundary_task_list_display(self):
        """Update boundary condition task list with hierarchical display and color support"""
        if not hasattr(self, 'boundary_tasks_listbox') or self.boundary_tasks_listbox is None:
            return
        self.boundary_tasks_listbox.config(state=tk.NORMAL)
        self.boundary_tasks_listbox.delete(1.0, tk.END)
        for step in self.boundary_condition_steps:
            num_str = str(step["num"])
            name = step["name"]
            if step.get("is_group"):
                if int(step["num"]) == step["num"]:
                    display_text = f"Step {num_str.split('.')[0]}: {name}\n"
                    self.boundary_tasks_listbox.insert(tk.END, display_text, "group")
                else:
                    display_text = f"  Step {num_str}: {name}\n"

    def update_boundary_task_list_display(self):
        """Update boundary condition task list with hierarchical display and color support"""
        if not hasattr(self, 'boundary_tasks_listbox') or self.boundary_tasks_listbox is None:
            return
        self.boundary_tasks_listbox.config(state=tk.NORMAL)
        self.boundary_tasks_listbox.delete(1.0, tk.END)
        for step in self.boundary_condition_steps:
            num_str = str(step["num"])
            name = step["name"]
            if step.get("is_group"):
                if int(step["num"]) == step["num"]:
                    display_text = f"Step {num_str.split('.')[0]}: {name}\n"
                    self.boundary_tasks_listbox.insert(tk.END, display_text, "group")
                else:
                    display_text = f"  Step {num_str}: {name}\n"
                    self.boundary_tasks_listbox.insert(tk.END, display_text, "sub_group")
            else:
                is_completed = self.boundary_task_completion_status.get(step["id"], False)
                status_char = "✓" if is_completed else " "
                display_text = f"  [{status_char}] Step {num_str}: {name}\n"
                tag = "completed_task" if is_completed else "incomplete_task"
                self.boundary_tasks_listbox.insert(tk.END, display_text, tag)
        self.boundary_tasks_listbox.config(state=tk.DISABLED)
    
    def update_material_property_steps_display(self):
        """Update material properties and section steps list and mark completed steps with color support"""
        if not hasattr(self, 'material_steps_listbox') or self.material_steps_listbox is None:
            return
        self.material_steps_listbox.config(state=tk.NORMAL)
        self.material_steps_listbox.delete(1.0, tk.END)
        for step in self.material_property_steps:
            is_completed = self.material_step_completion_status.get(step["id"], False)
            status_char = "✓" if is_completed else " "
            display_text = f"[{status_char}] Step {step['num']}: {step['name']}\n"
            tag = "completed_task" if is_completed else "incomplete_task"
            self.material_steps_listbox.insert(tk.END, display_text, tag)
        self.material_steps_listbox.config(state=tk.DISABLED)
    
    
    def on_llm_model_selected(self, event=None):
        """Update variable when user selects LLM model from dropdown"""
        selected_display_name = self.llm_model_var.get()
        try:
            index = self.available_llm_models_display.index(selected_display_name)
            self.selected_llm_model_name = self.available_llm_models[index]
            self.log(f"Selected LLM model: {self._remove_ansi_escape_codes(self.selected_llm_model_name)}")
        except ValueError:
            self.selected_llm_model_name = None
            self.log("Error: Unknown LLM model selection.", level="error")
    
    def init_llm_client(self):
        """Initialize LLM client"""
        if self.llm_client:
            if not messagebox.askyesno("LLM Already Initialized", "LLM client is already initialized. Are you sure you want to reinitialize?"):
                self.log("LLM reinitialization cancelled.")
                return
    
        if not self.selected_llm_model_name:
            self.show_warning("LLM Initialization", "Please select an LLM model from the dropdown menu first!")
            self.log("LLM initialization failed: No LLM model selected.", level="error")
            return
    
        llm_config = LLM_CONFIGS.get(self.selected_llm_model_name)
        if not llm_config:
            cleaned_model_name = self._remove_ansi_escape_codes(self.selected_llm_model_name)
            self.log(f"Error: Model '{cleaned_model_name}' not found in LLM configuration. Please check LLM_CONFIGS.", level="error")
            self.show_error("LLM Initialization", f"Configuration for model '{cleaned_model_name}' does not exist.")
            return
    
        api_token = llm_config.get("api_token", "")
        api_token_clean = self._remove_ansi_escape_codes(api_token)
        if "your-openai-api-key" in api_token_clean.lower() or \
           "your-together-api-key" in api_token_clean.lower() or \
           "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" in api_token_clean.lower() or \
           "EMPTY" in api_token_clean:
            # 已删除包含真实密钥的检查行
            cleaned_model_name = self._remove_ansi_escape_codes(self.selected_llm_model_name)
            warning_msg = f"Warning: The API key for the selected model '{cleaned_model_name}' may not have been replaced with your actual key, or is a default placeholder.\n\nPlease check the 'api_token' setting in LLM_CONFIGS. Continue anyway?"
            if not messagebox.askyesno("API Key Warning", warning_msg):
                self.log("LLM initialization cancelled.", level="warning")
                return
    
        try:
            clean_llm_config = {k: self._remove_ansi_escape_codes(v) if isinstance(v, str) else v for k, v in llm_config.items()}
            cleaned_model_name = self._remove_ansi_escape_codes(self.selected_llm_model_name)
            self.llm_client = LLMClientFactory.create_client(cleaned_model_name, clean_llm_config)
            self.log(f"Successfully initialized LLM client, using model: {cleaned_model_name}")
            self.display_chat_message(f"LLM assistant is ready, using model: {cleaned_model_name}", "llm")
            if self.current_k_file_path and os.path.exists(self.current_k_file_path):
                self._reenable_chat_controls()
            else:
                self.log("LLM assistant is ready. Please load K-file to start interaction.")
        except ValueError as e:
            self.llm_client = None
            self.log(f"LLM client initialization failed: {e}", level="error")
            self.show_error("LLM Initialization", f"LLM client initialization failed: {e}\nPlease check API key, network connection, or model name correctness.")
    
    
    def browse_k_file(self):
        """Browse K-file"""
        filepath = filedialog.askopenfilename(
            title="Select K-file",
            filetypes=[("K-files", "*.k"), ("All files", "*.*")]
        )
        if filepath:
            self.k_file_path_entry.delete(0, tk.END)
            self.k_file_path_entry.insert(0, filepath)
            self.log(f"K-file path selected: {filepath}")
    
    def set_k_file_path_for_llm(self):
        """Set K-file path for LLM operations and create backup"""
        k_path_input = self.k_file_path_entry.get().strip().strip('"')
        if not k_path_input:
            self.show_warning("K-file Setup", "K-file path cannot be empty!")
            self.log("K-file setup failed: Path is empty.", level="warning")
            return
    
        if not os.path.exists(k_path_input):
            self.log("Error: K-file does not exist, please check path and try again.", level="error")
            self.show_error("K-file Setup", "K-file does not exist, please check path and try again.")
            return
    
        self.current_k_file_path = k_path_input
        self.original_k_file_path = k_path_input
    
        output_dir_for_nodes = os.path.dirname(self.current_k_file_path)
        self.solid_nodes_txt_filepath = os.path.join(output_dir_for_nodes, "solid_nodes.txt")
        self.surface_nodes_txt_filepath = os.path.join(output_dir_for_nodes, "surface_nodes.txt")
        
        try:
            os.makedirs(output_dir_for_nodes, exist_ok=True)
            self.log(f"Ensured output directory '{output_dir_for_nodes}' exists.", level="info")
        except OSError as e:
            self.log(f"Failed to create output directory '{output_dir_for_nodes}': {e}", level="error")
            self.show_error("Directory Creation Failed", f"Unable to create or access output directory: {output_dir_for_nodes}\nPlease check permissions or if path is valid.")
            return  # Abort subsequent operations if directory creation fails
        
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = f"{os.path.splitext(self.current_k_file_path)[0]}.{timestamp}{os.path.splitext(self.current_k_file_path)[1]}"
            shutil.copy2(self.current_k_file_path, backup_path)
            self.log(f"Successfully backed up original file to: {backup_path}")
            self.display_chat_message(f"LLM assistant: K-file path set to '{self.current_k_file_path}' and backup created.", "llm")
    
            base_system_content_template = (
                f"You are a professional LS-DYNA K-file modeling assistant, capable of helping users with model initialization, boundary condition setup, and material property definition. You have the ability to call tools to select nodes, operate on K-files, add/modify materials and sections, and assign materials/sections to parts.\n\n"
                f"Your primary responsibility is to understand user requirements and convert them into one-time, end-to-end tool call sequences for the following functions until tasks are fully completed or you cannot continue:\n"
                f"find_nodes_by_criteria, find_specific_corner_node, create_translation_cfile_from_corner_node, normalize_model_direction, extract_solid_element_nodes_and_save_node_data, extract_surface_nodes_workflow, process_and_replace_nodeset_in_kfile, add_boundary_spc_set_id, add_pulse_curve_to_kfile, add_load_node_set, generate_and_run_lsprepost_script, add_nodes_to_existing_nodeset_by_criteria, parse_k_file,\n"
                f"llm_modify_rebar_section, llm_add_rebar_section, add_material_rebar_or_concrete, visualize_part_workflow, assign_material_and_section_workflow, get_formatted_sections_info, get_formatted_materials_info.\n\n"
                f"Please note that users may describe search conditions using ** natural language (e.g., 'find points where X is between 10 and 20'), mathematical expressions (e.g., '10<X<20', 'Y>50', 'Z<=30'), concise numeric lists (e.g., 'X,10,20' or 'Y 50 100'), and combined English keyword expressions (e.g., 'X from 10 to 20', 'Y between 5 and 15')**. Always communicate in .\n\n"
                f"If the user request involves appending, modifying, or updating existing models, you must first review the corresponding functional descriptions in description.py based on the user's requirements, and then call the appropriate tool in tools.py for execution. During invocation, ensure that all key parameters (such as IDs, titles, or paths) accurately reflect the user's final intent.\n"
                f"**Important Notes:**\n"
                f"* If user requests to select nodes based on criteria and **create a new node set**, or **replace an existing node set**, call find_nodes_by_criteria.\n"
                f"* If user requests to select nodes based on criteria and **append them (add without deleting existing nodes) to an existing node set**, call add_nodes_to_existing_nodeset_by_criteria. Ensure that target_sid and title_string reflect user's intent when calling add_nodes_to_existing_nodeset_by_criteria. If user only provides one SID, you can try to get an appropriate title from conversation or by parsing K-file.\n\n"
                f"When processing user requests, prioritize using {HARDCODED_COLOR}solid_nodes.txt{RESET} or {HARDCODED_COLOR}surface_nodes.txt{RESET} as source files for node lookup.\n\n"
                f"Current K-file path is: {self.current_k_file_path}.\n"
                f"If you need to extract nodes from solid elements, specify output file path as: {self.solid_nodes_txt_filepath}.\n"
                f"If you need to extract surface nodes from {self.solid_nodes_txt_filepath}, specify output file path as: {self.surface_nodes_txt_filepath}.\n"
                f"All subsequent node lookup operations (including find_nodes_by_criteria and add_nodes_to_existing_nodeset_by_criteria) will automatically read data from {self.solid_nodes_txt_filepath} or {self.surface_nodes_txt_filepath}, depending on user intent.\n"
                f"Visualization C-file template path: {self.cfile_template_for_viz_path}.\n"
                f"Assignment C-file template path: {self.assignment_cfile_template_path}.\n"
                f"Translation C-file template path: {self.translation_cfile_full_path}.\n"
                f"Rotation C-file template path: {self.rotation_cfile_full_path}.\n"
                f"LS-PrePost executable path: {self.LSPREPOST_EXE_PATH}.\n"
                f"Please automatically populate these paths as parameters when calling tools, no need to confirm with user again.\n"
                f"Your task is: Based on user's one-time input, **intelligently determine how many subtasks it contains, then plan and output all tool calls needed to complete these subtasks at once (if multiple tool calls are needed, provide all calls in a list format in one response)**. This plan will go through internal majority voting and DeepSeek-V3 confirmation mechanisms, so please ensure your plan is complete and correct. After completing a set of tool calls, you will receive tool execution results, at which point please reason again to determine if the task is completed, whether to give a final reply, or continue planning subsequent tool calls. If user instruction doesn't require tools, reply with final answer directly."
            )
    
            self.conversation_history = [{"role": "system", "content": self._remove_ansi_escape_codes(base_system_content_template)}]
    
            self.log("K-file setup successful, you can start interacting with LLM assistant.", "info")
            self.display_chat_message("LLM assistant: K-file setup successful, backup created and LLM context updated. What operation would you like to perform?", "llm")
            
            self.log("LLM-assistant: K-file setup successful, attempting to automatically extract solid element nodes...")
            extract_success, extract_message = extract_solid_element_nodes_and_save_node_data(
                k_filepath=self.current_k_file_path,
                output_txt_filepath=self.solid_nodes_txt_filepath
            )
    
            if extract_success:
                cleaned_extract_message = self._remove_ansi_escape_codes(extract_message)
                self.display_chat_message(f"LLM assistant: Solid element node extraction successful: {cleaned_extract_message}", "llm")
                self.log(f"Solid element nodes extracted to: {self.solid_nodes_txt_filepath}", level="info")
    
                self.log("LLM-assistant: Solid element node extraction successful, attempting to automatically extract surface nodes...")
                surface_extract_success = extract_surface_nodes_workflow(
                    input_node_filepath=self.solid_nodes_txt_filepath,
                    output_surface_filepath=self.surface_nodes_txt_filepath
                )
                if surface_extract_success:
                    surface_extract_message = f"Successfully extracted surface nodes from '{self.solid_nodes_txt_filepath}' and saved to '{self.surface_nodes_txt_filepath}'."
                    self.display_chat_message(f"LLM assistant: Surface node extraction successful: {self._remove_ansi_escape_codes(surface_extract_message)}", "llm")
                    self.log(f"Surface nodes extracted to: {self.surface_nodes_txt_filepath}", level="info")
                else:
                    surface_extract_message = "Surface node extraction failed, please check log."
                    self.display_chat_message(f"LLM assistant: Warning: Automatic surface node extraction failed: {self._remove_ansi_escape_codes(surface_extract_message)}. You may need to ask LLM to manually perform this operation in chat.", "llm")
                    self.log(f"Automatic surface node extraction failed: {self._remove_ansi_escape_codes(surface_extract_message)}", level="warning")
    
                if self.llm_client:
                    self._reenable_chat_controls()
            else:
                cleaned_extract_message = self._remove_ansi_escape_codes(extract_message)
                self.display_chat_message(f"LLM assistant: Warning: Automatic solid element node extraction failed: {cleaned_extract_message}. You may need to ask LLM to manually perform this operation in chat.", "llm")
                self.log(f"Automatic solid element node extraction failed: {cleaned_extract_message}", level="warning")
                if self.llm_client:
                    self._reenable_chat_controls()
        except Exception as e:
            self.log(f"Failed to create backup file or set K-file path: {e}", level="error")
            self.show_error("K-file Setup", f"Failed to create backup file or set K-file path: {e}")
            return
    
    
    def send_chat_message(self):
        """Processes user input in the chat interface (starting point of the Agent loop)"""
        user_input_text = self.chat_input_entry.get().strip()
        self.chat_input_entry.delete(0, tk.END)
    
        if not user_input_text:
            return
    
        self.display_chat_message(user_input_text, "user")
        self.log(f"User entered chat: {user_input_text}")
    
        if not self.llm_client:
            self.show_warning("LLM Not Initialized", "Please initialize the LLM client first!")
            self.display_chat_message("LLM not initialized, cannot process your request.", "system")
            return
    
        if not self.current_k_file_path or not os.path.exists(self.current_k_file_path):
            self.show_warning("K-File Not Set", "Please set a valid K-file path first!")
            self.display_chat_message("K-file path not set or file does not exist, cannot process LLM request.", "system")
            return
    
        if user_input_text.lower() == 'exit':
            self.display_chat_message("LLM Assistant: Thank you for using, goodbye!", "llm")
            self.log("LLM Assistant session ended.")
            self.set_ui_state(True)
            return
    
        self.conversation_history.append({"role": "user", "content": user_input_text})
        self.iteration_count = 0
        self.is_initial_user_query = True
        self.set_ui_state(False)
        self.chat_input_entry.config(state=tk.DISABLED)
        self.chat_send_btn.config(state=tk.DISABLED)
    
        llm_thread = threading.Thread(target=self._process_llm_response_in_thread)
        llm_thread.daemon = True
        llm_thread.start()
    
    
    def _process_llm_response_in_thread(self):
        """Processes LLM responses and tool calls in a separate thread."""
        self.root.after(0, lambda: self.display_chat_message("LLM Assistant: Thinking and planning...", "llm"))
        self.root.update_idletasks()
    
        self.iteration_count += 1
        if self.iteration_count > self.max_llm_iterations:
            self.log("LLM Assistant: Maximum interaction count reached, forcing exit.", level="warning")
            self.root.after(0, lambda: self.display_chat_message("LLM Assistant: Maximum interaction count reached, please try asking again.", "llm"))
            if self.conversation_history and self.conversation_history[-1]["role"] == "user":
                self.conversation_history.pop()
            self._reenable_chat_controls()
            self.is_initial_user_query = True
            return
    
        try:
            self.log(f"LLM Assistant: Making LLM call, current iteration: {self.iteration_count}, is_initial_user_query: {self.is_initial_user_query}...")
            
            llm_response_dict, input_tokens_consumed, output_tokens_consumed = call_llm(
                self.llm_client,
                self.conversation_history,
                TOOLS,
                num_calls=self.llm_num_calls,
                call_delay=self.llm_call_delay,
                is_initial_user_query=self.is_initial_user_query
            )
    
            self.is_initial_user_query = False 
    
            self.log(f"Total token consumption for this LLM call: Input Tokens: {input_tokens_consumed}, Output Tokens: {output_tokens_consumed}, Total: {input_tokens_consumed + output_tokens_consumed}", level="info")
    
            if not llm_response_dict or 'choices' not in llm_response_dict or not llm_response_dict['choices']:
                self.log("LLM Assistant: LLM call failed or returned empty/invalid response, please check network or API configuration.", level="error")
                self.root.after(0, lambda: self.display_chat_message("LLM Assistant: LLM call failed or returned empty/invalid response, please check network or API configuration.", "llm"))
                if self.conversation_history and self.conversation_history[-1]["role"] == "user":
                    self.conversation_history.pop()
                self._reenable_chat_controls()
                self.is_initial_user_query = True
                return
    
            message = llm_response_dict['choices'][0].get('message')
            if not message:
                self.log("LLM Assistant: No valid 'message' content found in LLM response.", level="warning")
                self.root.after(0, lambda: self.display_chat_message("LLM Assistant: Received empty or unparseable LLM response.", "llm"))
                if self.conversation_history and self.conversation_history[-1]["role"] == "user":
                    self.conversation_history.pop()
                self._reenable_chat_controls()
                self.is_initial_user_query = True
                return
    
            if message.get("tool_calls"):
                tool_calls = message["tool_calls"]
                self.conversation_history.append({"role": "assistant", "tool_calls": tool_calls})
                self.root.after(0, lambda: self.display_chat_message(f"LLM Assistant: Detected tool call plan ({len(tool_calls)} steps), executing...", "llm"))
                
                tool_results_for_feedback = []
                for i, tool_call in enumerate(tool_calls):
                    function_name = tool_call["function"]["name"]
                    arguments_str = tool_call["function"]["arguments"]
                    
                    self.root.after(0, lambda fn=function_name, args=arguments_str: self.display_chat_message(f"LLM Assistant: Calling tool '{fn}', arguments: {self._remove_ansi_escape_codes(args)}", "tool_input"))
                    self.log(f"LLM Assistant requests tool execution: {function_name}, arguments: {arguments_str}")
                    
                    function_response = self._execute_single_tool_call(tool_call, function_name, arguments_str)
                    
                    display_message = function_response.get("message", "Tool execution completed.")
                    self.root.after(0, lambda msg=self._remove_ansi_escape_codes(str(display_message)): self.display_chat_message(msg, "tool_output"))
    
                    if function_response.get("status") == "failed" or function_response.get("status") == "error":
                        self.log(f"LLM Assistant: Tool '{function_name}' execution failed, multi-step task interrupted.", level="error")
                        self.root.after(0, lambda: self.display_chat_message(f"LLM Assistant: Tool '{function_name}' execution failed, multi-step task interrupted. Please check log.", "llm"))
                        self._reenable_chat_controls()
                        self.is_initial_user_query = True
                        return
    
                    cleaned_function_response_content = json.dumps({
                        k: self._remove_ansi_escape_codes(v) if isinstance(v, str) else v
                        for k, v in function_response.items()
                    }, ensure_ascii=False)
                    tool_results_for_feedback.append({
                        "tool_call_id": tool_call.get("id", f"{function_name}_response_{self.iteration_count}"),
                        "name": function_name,
                        "content": cleaned_function_response_content
                    })
    
                    if i < len(tool_calls) - 1:
                        confirmation_message = f"Tool '{function_name}' has completed execution.\n\nContinue executing next command?"
                        should_continue = self._ask_yes_no_gui("Confirm Next Operation", confirmation_message)
                        if not should_continue:
                            self.log("LLM Assistant: User cancelled subsequent tool execution.", level="info")
                            self.root.after(0, lambda: self.display_chat_message("LLM Assistant: User cancelled subsequent tool execution, task aborted.", "llm"))
                            self._reenable_chat_controls()
                            self.is_initial_user_query = True
                            for tool_res in tool_results_for_feedback:
                                self.conversation_history.append({"role": "tool", **tool_res})
                            return
    
                self.root.after(0, lambda: self.display_chat_message("LLM Assistant: All tool calls completed, feeding results back to LLM...", "llm"))
                for tool_res in tool_results_for_feedback:
                     self.conversation_history.append({"role": "tool", **tool_res})
    
                self.root.after(0, self._process_llm_response_in_thread)
    
            elif message.get("content"):
                llm_text_response = message['content']
                cleaned_llm_text_response = self._remove_ansi_escape_codes(llm_text_response)
                self.log(f"LLM Assistant Reply: {cleaned_llm_text_response}")
                self.root.after(0, lambda msg=cleaned_llm_text_response: self.display_chat_message(msg, "llm"))
                self.conversation_history.append({"role": "assistant", "content": cleaned_llm_text_response})
                self._reenable_chat_controls()
                self.is_initial_user_query = True
            else:
                self.log("LLM Assistant: Received empty or unparseable LLM response content (neither tool call nor text).", level="warning")
                self.root.after(0, lambda: self.display_chat_message("LLM Assistant: Received empty or unparseable LLM response.", "llm"))
                if self.conversation_history and self.conversation_history[-1]["role"] == "user":
                    self.conversation_history.pop()
                self._reenable_chat_controls()
                self.is_initial_user_query = True
                return
    
        except Exception as e:
            self.log(f"LLM Assistant: Error occurred while processing LLM response: {e}", level="error")
            self.root.after(0, lambda err_msg=str(e): self.display_chat_message(f"LLM Assistant: Error occurred while processing request: {err_msg}", "llm"))
            if self.conversation_history and self.conversation_history[-1]["role"] == "user":
                self.conversation_history.pop()
            self._reenable_chat_controls()
            self.is_initial_user_query = True
            return
    
    
    def _reenable_chat_controls(self):
        """Re-enable chat control elements in GUI main thread"""
        self.root.after(0, lambda: self.set_ui_state(True))
        self.root.after(0, lambda: self.chat_input_entry.focus_set())
    
    def _execute_single_tool_call(self, tool_call, function_name, arguments_str):
        """
        Execute a single tool call suggested by LLM and return its result.
        This method encapsulates all logic from parsing parameters to calling actual tool functions, and handles status updates.
        """
        function_response = {"status": "error", "message": "Unknown error or uninitialized"}
        try:
            arguments = json.loads(arguments_str)
    
            nodes_source_filepath = ""
            if function_name in ["find_nodes_by_criteria", "add_nodes_to_existing_nodeset_by_criteria", "find_specific_corner_node", "extract_solid_element_nodes_and_save_node_data", "extract_surface_nodes_workflow"]:
                if os.path.exists(self.surface_nodes_txt_filepath):
                    nodes_source_filepath = self.surface_nodes_txt_filepath
                    self.log(f"LLM-Assistant: Node lookup tool '{function_name}' attempting to use surface node source file: {nodes_source_filepath}", "info")
                elif os.path.exists(self.solid_nodes_txt_filepath):
                    nodes_source_filepath = self.solid_nodes_txt_filepath
                    self.log(f"LLM-Assistant: Node lookup tool '{function_name}' attempting to use solid node source file: {nodes_source_filepath}", "info")
                else:
                    info_msg = f"Error: Node lookup source file '{self.solid_nodes_txt_filepath}' or '{self.surface_nodes_txt_filepath}' does not exist. Please perform the corresponding node extraction operation first."
                    return {"status": "failed", "message": info_msg}
    
                if nodes_source_filepath:
                    if 'nodes_source_filepath' in arguments:
                        arguments['nodes_source_filepath'] = nodes_source_filepath
                    elif 'k_file_path' in arguments:
                        arguments['k_file_path'] = nodes_source_filepath
                    elif function_name == "extract_solid_element_nodes_and_save_node_data":
                        pass
                    elif function_name == "extract_surface_nodes_workflow":
                        arguments['input_node_filepath'] = self.solid_nodes_txt_filepath
                    else:
                        self.log(f"Warning: Neither 'nodes_source_filepath' nor 'k_file_path' found in parameters for node lookup tool '{function_name}', may not correctly pass node source file. Attempting to add 'nodes_source_filepath'.", level="warning")
                        arguments['nodes_source_filepath'] = nodes_source_filepath
    
                llm_provided_tolerance_raw = arguments.get('tolerance')
                llm_provided_tolerance_float = try_float(llm_provided_tolerance_raw)
                if llm_provided_tolerance_float is not None and llm_provided_tolerance_float > 0:
                    arguments['tolerance'] = llm_provided_tolerance_float
                    self.log(f"LLM-Assistant: Note: LLM provided tolerance for '{function_name}': {llm_provided_tolerance_float}. This value will be used.", level="info")
                else:
                    arguments['tolerance'] = GENERAL_COORD_TOLERANCE
                    self.log(f"LLM-Assistant: Note: LLM provided invalid or zero tolerance ('{llm_provided_tolerance_raw}') for '{function_name}'. Forcibly set to default tolerance: {GENERAL_COORD_TOLERANCE}", level="warning")
    
                for coord_range_key in ['x_range', 'y_range', 'z_range']:
                    if coord_range_key in arguments and isinstance(arguments[coord_range_key], list):
                        arguments[coord_range_key] = tuple( (try_float(val) if val is not None else None) for val in arguments[coord_range_key] )
    
            if 'k_file_path' in arguments and function_name not in ["find_nodes_by_criteria", "add_nodes_to_existing_nodeset_by_criteria", "find_specific_corner_node", "extract_solid_element_nodes_and_save_node_data", "extract_surface_nodes_workflow"]:
                arguments['k_file_path'] = self.current_k_file_path
                self.log(f"LLM-Assistant: k_file_path parameter for tool '{function_name}' has been set to: {self.current_k_file_path}", "info")
            if 'k_filepath_to_open' in arguments:
                arguments['k_filepath_to_open'] = self.current_k_file_path
            if 'k_filepath_to_read' in arguments:
                arguments['k_filepath_to_read'] = self.current_k_file_path
            if 'k_filepath_to_write' in arguments:
                arguments['k_filepath_to_write'] = self.current_k_file_path
            if 'k_filepath' in arguments:
                arguments['k_filepath'] = self.current_k_file_path
    
            if function_name in self.available_functions_map:
                tool_func = self.available_functions_map[function_name]
    
                if function_name in ["apply_cfile_with_lsprepost", "run_lsprepost_with_cfile_visual", "run_lsprepost_with_assignment_cfile", "assign_material_and_section_workflow", "generate_and_run_lsprepost_script"]:
                    arguments['lsprepost_path'] = self.LSPREPOST_EXE_PATH
    
                if function_name == "normalize_model_direction":
                    arguments['cfile_template_path'] = self.rotation_cfile_full_path
                elif function_name == "create_translation_cfile_from_corner_node":
                    arguments['cfile_template_path'] = self.translation_cfile_full_path
                    # Explicitly specify nodes_source_filepath as the full path to solid_nodes.txt
                    # to avoid LLM mistakenly passing directory path causing extract_solid_element_nodes_and_save_node_data internal calculation errors
                    arguments['nodes_source_filepath'] = self.solid_nodes_txt_filepath # <--- Fix point
                    success, result = tool_func(**arguments)
                    if success:
                        generated_cfile_path = result
                        lsp_success, lsp_message = apply_cfile_with_lsprepost(
                            lsprepost_exe_path=self.LSPREPOST_EXE_PATH,
                            cfile_to_apply=generated_cfile_path,
                            final_save_k_path=self.current_k_file_path,
                            keep_open=True
                        )
                        if lsp_success: function_response = {"status": "success", "message": f"Model coordinates normalized successfully. CFILE applied. New K-file: {self.current_k_file_path}", "updated_k_file": self.current_k_file_path}; self.initialization_step_codes["init_coordinate"] = True; self.root.after(0, self.update_initialization_steps_display)
                        else: function_response = {"status": "failed", "message": f"CFILE application failed: {self._remove_ansi_escape_codes(lsp_message)}"}
                    else: function_response = {"status": "failed", "message": self._remove_ansi_escape_codes(result)}
    
                if function_name in ["visualize_part_workflow", "assign_material_and_section_workflow", "llm_modify_rebar_section", "llm_add_rebar_section"]:
                    arguments['gui_log_func'] = self.log
                    arguments['gui_display_chat_message_func'] = self.display_chat_message
                    arguments['gui_ask_yes_no_func'] = self._ask_yes_no_gui
                    arguments['gui_get_input_func'] = self._get_user_input_gui
                    if function_name == "assign_material_and_section_workflow":
                        arguments['gui_show_message_func'] = self._show_message_gui_sync
                        arguments['modify_part_title_func'] = lambda k_path, p_list, target_pid, new_title: modify_part_title_for_selected_part(k_path, p_list, target_pid, new_title)
    
                self.log(f"LLM-Assistant: Preparing to call '{function_name}', arguments: {arguments}", "info")
                
                
                if function_name == "extract_solid_element_nodes_and_save_node_data":
                    success, response_message = tool_func(**arguments)
                    function_response = {"status": "success" if success else "failed", "message": self._remove_ansi_escape_codes(response_message), "output_file": arguments['output_txt_filepath'] if success else None}
                elif function_name == "extract_surface_nodes_workflow":
                    success = tool_func(**arguments)
                    if success:
                        response_message = f"Successfully extracted surface nodes from '{self.solid_nodes_txt_filepath}' and saved to '{self.surface_nodes_txt_filepath}'."
                        function_response = {"status": "success", "message": response_message, "output_file": self.surface_nodes_txt_filepath}
                    else:
                        response_message = f"Surface node extraction failed, please check the log."
                        function_response = {"status": "failed", "message": response_message}
                elif function_name == "find_specific_corner_node":
                    corner_node, global_extremums, info_msg = tool_func(**arguments)
                    if global_extremums:
                        function_response = {"status": "success", "message": self._remove_ansi_escape_codes(info_msg), "corner_node": corner_node, "global_extremums": global_extremums}
                    else:
                        function_response = {"status": "failed", "message": self._remove_ansi_escape_codes(info_msg)}
                elif function_name == "normalize_model_direction":
                    success, response_message = tool_func(**arguments)
                    function_response = {"status": "success" if success else "failed", "message": self._remove_ansi_escape_codes(response_message), "updated_k_file": self.current_k_file_path if success else None}
                    if success: self.initialization_step_codes["init_direction"] = True; self.root.after(0, self.update_initialization_steps_display)
                elif function_name == "create_translation_cfile_from_corner_node":
                    success, result = tool_func(**arguments)
                    if success:
                        generated_cfile_path = result
                        lsp_success, lsp_message = apply_cfile_with_lsprepost(
                            lsprepost_exe_path=self.LSPREPOST_EXE_PATH,
                            cfile_to_apply=generated_cfile_path,
                            final_save_k_path=self.current_k_file_path,
                            keep_open=True
                        )
                        if lsp_success: function_response = {"status": "success", "message": f"Model coordinates normalized successfully. CFILE applied. New K-file: {self.current_k_file_path}", "updated_k_file": self.current_k_file_path}; self.initialization_step_codes["init_coordinate"] = True; self.root.after(0, self.update_initialization_steps_display)
                        else: function_response = {"status": "failed", "message": f"CFILE application failed: {self._remove_ansi_escape_codes(lsp_message)}"}
                    else: function_response = {"status": "failed", "message": self._remove_ansi_escape_codes(result)}
                
                elif function_name == "add_material_rebar_or_concrete":
                    # Ensure all numeric parameters are converted to correct types (LLM may provide strings)
                    # No longer need to convert individually here because add_material_rebar_or_concrete in tools.py handles final_params type conversion internally
                    # However, mid and material_type may still be directly provided by LLM, need to ensure correct type
                    if 'mid' in arguments:
                        try: arguments['mid'] = int(try_float(arguments['mid']))
                        except (ValueError, TypeError): self.log(f"Warning: Cannot convert parameter mid value '{arguments['mid']}' to integer. Skipping conversion.", level="warning")
                    
                    self.log(f"LLM-assistant: Preparing to call '{function_name}', arguments: {arguments}", "info")
                    
                    # >>>>>> Modification start <<<<<<
                    # Correctly pass all LLM-provided parameters to add_material_rebar_or_concrete function in tools.py
                    success, response_message = tool_func(
                        k_file_path_to_read=self.current_k_file_path,
                        k_file_path_to_write=self.current_k_file_path,
                        material_type=arguments.get('material_type'),
                        # mid=arguments.get('mid'), # mid and material_title can be obtained directly from arguments
                        # material_title=arguments.get('material_title'),
                        parameters=arguments, # <--- Key modification: Pass entire arguments dict as parameters
                        gui_output_func=lambda msg, sender="tool_output": self.root.after(0, lambda m=msg, s=sender: self.display_chat_message(m, s)),
                        gui_get_input_func=self._get_user_input_gui,
                        gui_ask_yes_no_func=self._ask_yes_no_gui,
                        gui_log_func=self.log # <--- Recommended addition: Pass logging function
                    )
                    # >>>>>> Modification end <<<<<<
    
                    function_response = {"status": "success" if success else "failed", "message": self._remove_ansi_escape_codes(response_message)}
                    if success:
                        self.material_step_completion_status["material_step_1"] = True
                        self.root.after(0, self.update_material_property_steps_display)
                        self.log(f"K-file '{self.current_k_file_path}' has been modified. Automatically opening LS-PrePost for display...", "info")
                        self.root.after(0, lambda: generate_and_run_lsprepost_script(
                            k_file_path_to_open=self.current_k_file_path,
                            sid_to_show=None # Usually don't need to show specific node set here, just open file
                        ))
                        self.root.after(0, lambda: self.show_info("LS-PrePost Launched", "LS-PrePost has been launched, please manually view modified K-file and close LS-PrePost."))
                    else:
                        self.log(f"Tool '{function_name}' failed: {response_message}", level="error")
    
                elif function_name == "find_nodes_by_criteria":
                    raw_result = tool_func(**arguments)
                    found_nodes = []
                    info_msg = ""
                    
                    if isinstance(raw_result, tuple) and len(raw_result) == 2:
                        found_nodes, info_msg = raw_result
                    elif isinstance(raw_result, list):
                        found_nodes = raw_result
                        info_msg = f"Found {len(found_nodes)} nodes."
                    else:
                        info_msg = f"find_nodes_by_criteria returned unknown format result: {raw_result}"
                        found_nodes = []
                    
                    if found_nodes:
                        next_sid = max(list(self.node_sets_in_session.keys()) + [1000]) + 1 if self.node_sets_in_session else 1001
                        target_sid_from_llm = arguments.get('target_sid')
                        if target_sid_from_llm and target_sid_from_llm not in self.node_sets_in_session: next_sid = target_sid_from_llm
                        next_sid = int(next_sid)
                        title = arguments.get('title_string', f"LLM_Selected_Nodes_SID_{next_sid}")
                        process_success, process_msg = process_and_replace_nodeset_in_kfile(node_ids_to_write=found_nodes, target_sid=next_sid, title_string=title, input_kfile_path_for_read=self.current_k_file_path, output_kfile_path_for_write=self.current_k_file_path)
                        if process_success:
                            self.node_sets_in_session[next_sid] = {'nodes': found_nodes, 'title': title, 'used_for_boundary': False}
                            function_response = {"status": "success", "message": f"{self._remove_ansi_escape_codes(info_msg)} Node set SID {next_sid} (Title: {title}) created, containing {len(found_nodes)} nodes.", "node_set_id": next_sid}
                            self.root.after(0, lambda sid_val=next_sid: generate_and_run_lsprepost_script(k_file_path_to_open=self.current_k_file_path, sid_to_show=sid_val))
                            if self.last_selected_nodes_for_fixed_boundary_sid is None:
                                self.boundary_task_completion_status["fix_boundary_step1"] = True
                                y_criteria_match = "y_range" in arguments and arguments["y_range"] == (-0, -700)
                                z_criteria_match = "z_range" in arguments and arguments["z_range"] == (0, 0)
                                if y_criteria_match and z_criteria_match: self.boundary_task_completion_status["add_specific_boundary_nodes"] = True
                                self.last_selected_nodes_for_fixed_boundary_sid = next_sid
                                self.root.after(0, self.update_boundary_task_list_display)
                            elif self.last_selected_nodes_for_pulse_load_sid is None:
                                self.boundary_task_completion_status["pulse_load_step1"] = True
                                self.last_selected_nodes_for_pulse_load_sid = next_sid
                                self.root.after(0, self.update_boundary_task_list_display)
                        else: function_response = {"status": "failed", "message": f"{self._remove_ansi_escape_codes(info_msg)} But node set creation failed: {self._remove_ansi_escape_codes(process_msg)}"}
                    else: function_response = {"status": "failed", "message": self._remove_ansi_escape_codes(info_msg)}
                elif function_name == "add_nodes_to_existing_nodeset_by_criteria":
                    arguments['input_kfile_path_for_read'] = self.current_k_file_path
                    arguments['output_kfile_path_for_write'] = self.current_k_file_path
                    arguments['target_sid'] = int(arguments['target_sid'])
                    self.log(f"LLM-Assistant: Preparing to call '{function_name}', nodes_source_filepath={arguments.get('nodes_source_filepath', arguments.get('k_file_path'))}, target_sid={arguments.get('target_sid')}, criteria={arguments.get('criteria')}", "info")
                    success, response_message, final_node_count = tool_func(**arguments)
                    target_sid = arguments['target_sid']
                    title_string = arguments.get('title_string', f"LLM_Nodeset_SID_{target_sid}")
                    if success:
                        updated_nodes = parse_existing_nodes_from_set_node_list(self.current_k_file_path, target_sid)
                        self.node_sets_in_session[target_sid] = {'nodes': updated_nodes, 'title': title_string, 'used_for_boundary': False}
                        function_response = {"status": "success", "message": self._remove_ansi_escape_codes(response_message), "node_set_id": target_sid, "final_node_count": final_node_count}
                        self.root.after(0, lambda sid=target_sid: generate_and_run_lsprepost_script(k_file_path_to_open=self.current_k_file_path, sid_to_show=sid))
                    else: function_response = {"status": "failed", "message": self._remove_ansi_escape_codes(response_message)}
                elif function_name == "add_boundary_spc_set_id":
                    target_sid = int(arguments['nodeset_id_to_fix'])
                    
                    if self.last_selected_nodes_for_fixed_boundary_sid is not None and target_sid == 1 and self.last_selected_nodes_for_fixed_boundary_sid == 1001:
                        self.log(f"Warning: LLM specified nodeset_id_to_fix={target_sid}, but last created fixed boundary nodeset was {self.last_selected_nodes_for_fixed_boundary_sid}. Attempting to use {self.last_selected_nodes_for_fixed_boundary_sid}.", level="warning")
                        target_sid = self.last_selected_nodes_for_fixed_boundary_sid
                    elif target_sid not in self.node_sets_in_session and self.last_selected_nodes_for_fixed_boundary_sid is not None:
                        prompt_msg = f"LLM specified node set SID {target_sid} does not exist. Use most recently created fixed boundary node set SID {self.last_selected_nodes_for_fixed_boundary_sid}?"
                        if self._ask_yes_no_gui("Node Set ID Confirmation", prompt_msg):
                            target_sid = self.last_selected_nodes_for_fixed_boundary_sid
                        else:
                            parsed_nodes = parse_existing_nodes_from_set_node_list(self.current_k_file_path, target_sid)
                            if parsed_nodes: self.node_sets_in_session[target_sid] = {'nodes': parsed_nodes, 'title': f"Kfile_Parsed_SID_{target_sid}", 'used_for_boundary': False}
                            else: return {"status": "failed", "message": f"Error: Node set SID {target_sid} not found in current session and could not be parsed from K-file. Please create or select a node set first."}
    
                    if target_sid not in self.node_sets_in_session:
                        parsed_nodes = parse_existing_nodes_from_set_node_list(self.current_k_file_path, target_sid)
                        if parsed_nodes: self.node_sets_in_session[target_sid] = {'nodes': parsed_nodes, 'title': f"Kfile_Parsed_SID_{target_sid}", 'used_for_boundary': False}
                        else: return {"status": "failed", "message": f"Error: Node set SID {target_sid} not found in current session and could not be parsed from K-file. Please create or select a node set first."}
                    
                    self.log(f"LLM-Assistant: Preparing to call '{function_name}', k_file_path_to_read={self.current_k_file_path}, k_file_path_to_write={self.current_k_file_path}, nodeset_id_to_fix={target_sid}, boundary_id={arguments.get('boundary_id', 1)}, heading={arguments.get('heading', f'LLM_Selected_Nodes_SID_{target_sid}')}", "info")
                    success, response_message = tool_func(k_file_path_to_read=self.current_k_file_path, k_file_path_to_write=self.current_k_file_path, nodeset_id_to_fix=target_sid, boundary_id=arguments.get('boundary_id', 1), heading=arguments.get('heading', f"LLM_Selected_Nodes_SID_{target_sid}"))
                    if success:
                        function_response = {"status": "success", "message": self._remove_ansi_escape_codes(response_message)}
                        self.node_sets_in_session[target_sid]['used_for_boundary'] = True
                        self.root.after(0, lambda sid=target_sid: generate_and_run_lsprepost_script(k_file_path_to_open=self.current_k_file_path, sid_to_show=sid))
                        self.boundary_task_completion_status["fix_boundary_step2"] = True
                        self.root.after(0, self.update_boundary_task_list_display)
                    else: function_response = {"status": "failed", "message": self._remove_ansi_escape_codes(response_message)}
    
                elif function_name == "add_pulse_curve_to_kfile":
                    if 'lcid' in arguments: arguments['lcid'] = int(try_float(arguments['lcid']))
                    if 'points' in arguments and isinstance(arguments['points'], list): arguments['points'] = [[(try_float(val) or 0.0) for val in pair] for pair in arguments['points']]
                    self.log(f"LLM-Assistant: Preparing to call '{function_name}', k_file_path={arguments.get('k_file_path')}, lcid={arguments.get('lcid')}, points={arguments.get('points')}", "info")
                    success, response_message = tool_func(**arguments)
                    new_lcid = arguments.get('lcid')
                    if success:
                        function_response = {"status": "success", "message": self._remove_ansi_escape_codes(response_message), "lcid": new_lcid}
                        self.boundary_task_completion_status["pulse_load_step2"] = True
                        self.last_created_pulse_curve_lcid = new_lcid
                        self.root.after(0, self.update_boundary_task_list_display)
                    else:
                        function_response = {"status": "error", "message": self._remove_ansi_escape_codes(response_message), "lcid": new_lcid}
                        self.boundary_task_completion_status["pulse_load_step2"] = False
                elif function_name == "add_load_node_set":
                    target_nsid = int(arguments['nsid'])
                    if target_nsid not in self.node_sets_in_session:
                        return {"status": "failed", "message": f"Error: Node set SID {target_nsid} not found in current session. Please create or select a node set first."}
                    llm_provided_lc_id = arguments.get('lc_id') or arguments.get('lcid')
                    if llm_provided_lc_id is not None: llm_provided_lc_id = int(llm_provided_lc_id)
                    if llm_provided_lc_id is not None and self.last_created_pulse_curve_lcid and llm_provided_lc_id != self.last_created_pulse_curve_lcid:
                        self.log(f"Warning: The LCID specified for pulse load ({llm_provided_lc_id}) is inconsistent with the recently created curve LCID ({self.last_created_pulse_curve_lcid}), forcing use of the recently created curve.", level="warning")
                        llm_provided_lc_id = self.last_created_pulse_curve_lcid
                    elif self.last_created_pulse_curve_lcid and llm_provided_lc_id is None:
                        self.log(f"Info: LLM did not specify LCID, automatically using recently created LCID: {self.last_created_pulse_curve_lcid}", "info")
                        llm_provided_lc_id = self.last_created_pulse_curve_lcid
                    elif llm_provided_lc_id is None:
                        return {"status": "failed", "message": "Error: Load curve LCID not specified, and no recently created pulse curve found in session."}
                    node_ids_to_write = self.node_sets_in_session[target_nsid]['nodes']
                    title_for_nodeset = self.node_sets_in_session[target_nsid]['title']
                    process_success, process_msg = process_and_replace_nodeset_in_kfile(node_ids_to_write=node_ids_to_write, target_sid=target_nsid, title_string=title_for_nodeset, input_kfile_path_for_read=self.current_k_file_path, output_kfile_path_for_write=self.current_k_file_path)
                    if not process_success:
                        function_response = {"status": "failed", "message": f"Failed to write node set {target_nsid}, unable to assign pulse: {self._remove_ansi_escape_codes(process_msg)}"}
                    else:
                        load_dof = arguments.get('dof')
                        if load_dof is not None:
                            try: load_dof = int(load_dof)
                            except ValueError: load_dof = 2
                        else: load_dof = 2
                        self.log(f"LLM-Assistant: Preparing to call '{function_name}', k_file_path_to_read={self.current_k_file_path}, k_file_path_to_write={self.current_k_file_path}, nsid={target_nsid}, lcid={llm_provided_lc_id}, dof={load_dof}", "info")
                        success, response_message = tool_func(k_file_path_to_read=self.current_k_file_path, k_file_path_to_write=self.current_k_file_path, nsid=target_nsid, lcid=llm_provided_lc_id, dof=load_dof)
                        if success:
                            function_response = {"status": "success", "message": self._remove_ansi_escape_codes(response_message)}
                            self.node_sets_in_session[target_nsid]['used_for_boundary'] = True
                            self.root.after(0, lambda sid=target_nsid: generate_and_run_lsprepost_script(k_file_path_to_open=self.current_k_file_path, sid_to_show=sid))
                            self.boundary_task_completion_status["pulse_load_step3"] = True
                            self.root.after(0, self.update_boundary_task_list_display)
                        else: function_response = {"status": "failed", "message": self._remove_ansi_escape_codes(response_message)}
                elif function_name == "generate_and_run_lsprepost_script":
                    if 'sid_to_show' in arguments: arguments['sid_to_show'] = int(arguments['sid_to_show']) if arguments['sid_to_show'] is not None else None
                    self.log(f"LLM-Assistant: Preparing to call '{function_name}', k_file_path_to_open={arguments.get('k_file_path_to_open')}, sid_to_show={arguments.get('sid_to_show')}", "info")
                    success = tool_func(k_file_path_to_open=self.current_k_file_path, sid_to_show=arguments.get('sid_to_show'))
                    if success: function_response = {"status": "success", "message": "Attempted to open K-file in LS-PrePost. Please view manually."}
                    else: function_response = {"status": "failed", "message": "Failed to launch LS-PrePost for viewing. Please check LS-PrePost path or K-file existence."}
                elif function_name in ["llm_modify_rebar_section", "llm_add_rebar_section"]:
                    for key in arguments:
                        if key.endswith(('_id', '_sid', '_lcid', 'id')):
                            try: arguments[key] = int(try_float(arguments[key]))
                            except (ValueError, TypeError): self.log(f"Warning: Could not convert value of parameter {key} '{arguments[key]}' to integer. Skipping conversion.", level="warning")
                        elif key in ['thickness', 'diameter', 'elastic_modulus', 'poisson_ratio', 'density', 'ts1', 'ts2']:
                            try: arguments[key] = try_float(arguments[key])
                            except (ValueError, TypeError): self.log(f"Warning: Could not convert value of parameter {key} '{arguments[key]}' to float. Skipping conversion.", level="warning")
                    self.log(f"LLM-Assistant: Preparing to call '{function_name}', arguments: {arguments}", "info")
                    success, response_message = tool_func(k_file_path_to_read=self.current_k_file_path, k_file_path_to_write=self.current_k_file_path, secid=arguments.get('secid'), TITLE=arguments.get('TITLE'), ts1=arguments.get('ts1'), ts2=arguments.get('ts2'), gui_output_func=lambda msg, sender="tool_output": self.root.after(0, lambda m=msg, s=sender: self.display_chat_message(m, s)), gui_get_input_func=self._get_user_input_gui, gui_ask_yes_no_func=self._ask_yes_no_gui, gui_log_func=self.log)
                    if success:
                        function_response = {"status": "success", "message": self._remove_ansi_escape_codes(response_message)}
                        self.material_step_completion_status["material_step_2"] = True
                        self.root.after(0, self.update_material_property_steps_display)
                        self.log(f"K-file '{self.current_k_file_path}' has been modified. Automatically opening LS-PrePost for display...", "info")
                        self.root.after(0, lambda: generate_and_run_lsprepost_script(k_file_path_to_open=self.current_k_file_path, sid_to_show=None))
                        self.root.after(0, lambda: self.show_info("LS-PrePost Launched", "LS-PrePost has been launched. Please manually close the LS-PrePost window after viewing, then return to the application to continue operations."))
                    else: function_response = {"status": "failed", "message": self._remove_ansi_escape_codes(response_message)}
                elif function_name == "get_formatted_sections_info":
                    self.log(f"LLM-Assistant: Preparing to call '{function_name}', k_file_path={arguments.get('k_file_path')}", "info")
                    response_message = tool_func(**arguments)
                    is_success = not (isinstance(response_message, str) and (response_message.lower().startswith("error:") or "failed" in response_message))
                    function_response = {"status": "success" if is_success else "failed", "message": self._remove_ansi_escape_codes(response_message)}
                elif function_name == "get_formatted_materials_info":
                    self.log(f"LLM-Assistant: Preparing to call '{function_name}', k_file_path={arguments.get('k_file_path')}", "info")
                    response_message = tool_func(**arguments)
                    is_success = not (isinstance(response_message, str) and (response_message.lower().startswith("error:") or "failed" in response_message))
                    function_response = {"status": "success" if is_success else "failed", "message": self._remove_ansi_escape_codes(response_message)}
                elif function_name == "parse_k_file":
                    self.log(f"LLM-Assistant: Preparing to call '{function_name}', k_file_path={arguments.get('k_file_path')}", "info")
                    parsed_data = tool_func(**arguments)
                    if parsed_data: function_response = {"status": "success", "message": "K-file parsed successfully." , "data": parsed_data}
                    else: function_response = {"status": "failed", "message": "K-file parsing failed or returned empty data."}
                else:
                    self.log(f"LLM-Assistant: Preparing to call generic tool '{function_name}', arguments: {arguments}", "info")
                    for key, value in arguments.items():
                        if isinstance(value, str):
                            float_val = try_float(value)
                            if float_val is not None: arguments[key] = float_val
                    success, response_message = tool_func(**arguments)
                    function_response = {"status": "success" if success else "failed", "message": self._remove_ansi_escape_codes(response_message)}
                
            else:
                response_message = f"LLM requested an unknown tool: {function_name}"
                function_response = {"status": "error", "message": response_message}
                self.log(f"Error: {response_message}", level="error")
    
        except json.JSONDecodeError as jde:
            response_message = f"Tool arguments provided by LLM are not valid JSON format: {jde}. Arguments: {self._remove_ansi_escape_codes(arguments_str)}"
            function_response = {"status": "error", "message": response_message}
            self.log(f"Error: {response_message}", level="error")
        except TypeError as te:
            response_message = f"Parameter error (TypeError) occurred when executing tool '{function_name}': {te}. Please check if the parameters generated by LLM match the tool function signature. Arguments: {self._remove_ansi_escape_codes(arguments_str)}"
            function_response = {"status": "error", "message": response_message}
            self.log(f"Error: {response_message}", level="error")
        except Exception as e:
            response_message = f"An unexpected error occurred when executing tool '{function_name}': {e}"
            function_response = {"status": "error", "message": response_message}
            self.log(f"Error: {response_message}", level="error")
        
        return function_response
    
    def _feedback_tool_result_to_llm(self, tool_call, function_name, function_response):
        """Feed tool execution results back to LLM and display in GUI"""
        cleaned_function_response_content = json.dumps({
            k: self._remove_ansi_escape_codes(v) if isinstance(v, str) else v
            for k, v in function_response.items()
        }, ensure_ascii=False)
    
        self.conversation_history.append({
            "role": "tool",
            "tool_call_id": tool_call.get("id", f"{function_name}_response_{self.iteration_count}"),
            "name": function_name,
            "content": cleaned_function_response_content
        })
    
        display_message = function_response.get("message", "Tool execution completed.")
        self.root.after(0, lambda msg=self._remove_ansi_escape_codes(str(display_message)): self.display_chat_message(msg, "tool_output"))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    root = tk.Tk()
    app = APDLModelingGUI(root)
    root.mainloop()
