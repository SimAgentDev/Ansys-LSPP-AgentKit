# description.py
# Defines the JSON Schema for tools available to the LLM.

TOOLS = [
    # --- Initialization Related Tools ---
    {
        "type": "function",
        "function": {
            "name": "create_translation_cfile_from_corner_node",
            "description": "Called when the user explicitly requests to **initialize model coordinates**, **translate the model to the origin**, or **adjust coordinates based on a specific corner**. This function **first extracts all solid element nodes from the original K file and saves them to `solid_nodes.txt` (overwriting existing file)**. It then searches this latest `solid_nodes.txt` for a specific corner node of the model (e.g., the node with min X, max Y, min Z), calculates the translation vector required to move that corner to the global origin (0,0,0), and generates a CFILE containing the 'translate_model' command. This tool launches LS-PrePost by default and keeps it open so the user can observe and confirm the translation effect.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lsprepost_exe_path": {"type": "string", "description": "Path to the LS-PrePost executable."},
                    "k_filepath": {"type": "string", "description": "Path to the original LS-DYNA K file for the translation operation. This file is used to extract solid element nodes and serves as the target file opened and modified by LS-PrePost."},
                    "cfile_template_path": {"type": "string", "description": "Path to the CFILE template used for the translation operation. The template should contain 'KEYWORD_FILE_PATH_PLACEHOLDER', a command for translation (e.g., 'translate_model X Y Z'), and a 'save keyword' placeholder."},
                    "output_cfile_path": {"type": "string", "description": "Path to the generated CFILE used to execute the translation."},
                    "final_save_k_path": {"type": "string", "description": "Path where the final K file will be saved after model translation."},
                    "tolerance": {"type": "number", "description": "Coordinate tolerance when searching for the corner node."},
                    "nodes_source_filepath": {"type": "string", "description": "**The `solid_nodes.txt` file at this path will be overwritten with fresh solid node data extracted from `k_filepath` every time this tool is called.** The node search operation will be performed on this file."}
                },
                "required": ["lsprepost_exe_path", "k_filepath", "cfile_template_path", "output_cfile_path", "final_save_k_path", "tolerance", "nodes_source_filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "normalize_model_direction",
            "description": "Called when the user explicitly requests to **initialize model orientation**, **adjust model facing**, **Initialize model direction**, or **normalize positive directions**. This function applies a **fixed rotation operation** contained in a **preset CFILE template** to align the model to a standard orientation (e.g., converting Y-up to Z-up). It uses the model's global extremes (min X, max Y, min Z) as a reference to assist the LLM in determining when to apply this preset orientation normalization. The tool directly uses the provided CFILE template to generate and execute a CFILE containing 'rotate_model' commands. This tool launches LS-PrePost by default and keeps it open so the user can observe and confirm the orientation adjustment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lsprepost_exe_path": {"type": "string", "description": "Path to the LS-PrePost executable."},
                    "k_filepath_to_open": {"type": "string", "description": "Path to the LS-DYNA K file to be normalized."},
                    "cfile_template_path": {"type": "string", "description": "Path to the CFILE template for the **preset rotation** operation. This template should **already contain** fixed 'rotate_model' commands (e.g., 'rotate_model 0 0 0 x 90'), as well as 'KEYWORD_FILE_PATH_PLACEHOLDER' and 'save keyword' placeholders. The tool will use this template directly to execute the preset rotation."},
                    "output_cfile_path": {"type": "string", "description": "Path to the generated CFILE used to execute the normalization."},
                    "final_save_k_path": {"type": "string", "description": "Path where the final K file will be saved after model normalization."},
                    "min_x": {"type": "number", "description": "Global minimum X coordinate of the model. Used to assist the LLM in deciding when to apply this preset orientation normalization."},
                    "max_y": {"type": "number", "description": "Global maximum Y coordinate of the model. Used to assist the LLM in deciding when to apply this preset orientation normalization."},
                    "min_z": {"type": "number", "description": "Global minimum Z coordinate of the model. Used to assist the LLM in deciding when to apply this preset orientation normalization."}
                },
                "required": ["lsprepost_exe_path", "k_filepath_to_open", "cfile_template_path", "output_cfile_path", "final_save_k_path", "min_x", "max_y", "min_z"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_specific_corner_node",
            "description": "Finds a single node from the *extracted node data file* (e.g., solid_nodes.txt) that simultaneously satisfies the following conditions: global minimum Z, minimum X, and maximum Y coordinates of the model. This function also returns the global extreme coordinates of the model. Ensure that `extract_solid_element_nodes_and_save_node_data` has been run on this file previously.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_filepath": {
                        "type": "string",
                        "description": "Full path to the *extracted node data file* (e.g., solid_nodes.txt) to be read.",
                    },
                    "tolerance": {
                        "type": "number",
                        "description": "Tolerance value for floating-point coordinate comparison. Defaults to 0.1.",
                        "default": 0.1
                    }
                },
                "required": ["k_filepath"]
            }
        }
    },
    # --- Boundary Condition Related Tools ---
    {
        "type": "function",
        "function": {
            "name": "add_boundary_spc_set_id",
            "description": "Creates a *BOUNDARY_SPC_SET_ID block in the LS-DYNA K file. This function fixes the six degrees of freedom (xyzrxryrz) for the given node set ID (nsid). The block will be inserted **after** the last *SET_NODE_LIST_TITLE keyword in the K file. If *SET_NODE_LIST_TITLE does not exist, it will be appended to the end of the file or before the *END keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path_to_read": {"type": "string", "description": "Path to the original LS-DYNA K file to read."},
                    "k_file_path_to_write": {"type": "string", "description": "Path to the new LS-DYNA K file to save after modification."},
                    "boundary_id": {"type": "integer", "description": "Unique identifier for the *BOUNDARY_SPC_SET_ID to be created."},
                    "heading": {"type": "string", "description": "Title or description string for the *BOUNDARY_SPC_SET_ID."},
                    "nodeset_id_to_fix": {"type": "integer", "description": "The Node Set ID (nsid) that needs to be fixed."}
                },
                "required": ["k_file_path_to_read", "k_file_path_to_write", "boundary_id", "heading", "nodeset_id_to_fix"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_nodes_by_criteria",
            "description": (
                "Selects nodes from an *extracted node data file* (e.g., solid_nodes.txt or surface_nodes.txt) based on coordinate ranges (X, Y, Z) or by finding the global minimum Y coordinate. **This tool creates a brand new node set** "
                "and writes it to the K file, or replaces an existing node set with the same SID in the K file. If the user's intent is to find nodes and add them to an **existing** node set, "
                "the `add_nodes_to_existing_nodeset_by_criteria` tool should be called instead.\n\n"
                "This tool flexibly understands various user input formats, "
                "including **English descriptions (e.g., 'find points where X is between 10 and 20'), English descriptions (e.g., 'X from 10 to 20', 'Y between 5 and 15'), "
                "mathematical inequalities (e.g., '10<x<20', 'Y>50', 'Z<=30', 'x=-500'), concise number lists (e.g., 'x,10,20' or 'y 50 100'), "
                "and any combination thereof.**\n\n"
                "**Core Parsing Rules:**\n"
                "1. **Mandatory Range Parameter Format**: Regardless of how the user describes it, `x_range`, `y_range`, and `z_range` parameters **must ultimately** be provided in the form `[min_value, max_value]`. If a single value is provided (e.g., 'X=100'), it is parsed as `[value, value]` (e.g., `[100, 100]`).\n"
                "2. **Intelligent Range Correction**: If the range entered by the user is logically 'reversed' (e.g., negative numbers like `\"-700<y<-1000\"`, which logically means `y` should be between `-1000` and `-700`), the model **must intelligently identify and automatically reorder the range to the correct `[min, max]` order**. For example, parse `-700<y<-1000` as `y_range=[-1000, -700]`; parse `Y from 100 to 50` as `y_range=[50, 100]`.\n"
                "3. **Interval Understanding**: By default, all ranges are closed intervals (including boundary values)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path": {
                        "type": "string",
                        "description": "Full path to the K file or TXT file containing node data (e.g., solid_nodes.txt or surface_nodes.txt)."
                    },
                    "criteria_type": {
                        "type": "string",
                        "enum": ["coord_range", "min_y"],
                        "description": "Search type, 'min_y' or 'coord_range'. Default is 'coord_range'."
                    },
                    "tolerance": { # <--- This is key!
                        "type": "number",
                        "description": "Tolerance value for floating-point comparisons. Default is 0.1. Should not be set to 0, as floating-point comparisons require tolerance.",
                        "default": 0.1 # Explicitly set default value
                    },
                    "x_range": {
                        "type": "array",
                        "items": {"type": ["number", "null"]},
                        "description": "X coordinate range [min, max], e.g., [10.0, 20.0]. None indicates no boundary. Default is [null, null]."
                    },
                    "y_range": {
                        "type": "array",
                        "items": {"type": ["number", "null"]},
                        "description": "Y coordinate range [min, max], e.g., [10.0, 20.0]. None indicates no boundary. Default is [null, null]."
                    },
                    "z_range": {
                        "type": "array",
                        "items": {"type": ["number", "null"]},
                        "description": "Z coordinate range [min, max], e.g., [10.0, 20.0]. None indicates no boundary. Default is [null, null]."
                    }
                },
                "required": ["k_file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_nodes_to_existing_nodeset_by_criteria",
            "description": (
                "Selects nodes from an *extracted node data file* (e.g., solid_nodes.txt or surface_nodes.txt) based on coordinate ranges (X, Y, Z) or by finding the global minimum Y coordinate, and **appends** these newly found nodes to an existing node set with a specified SID in the K file. If the target SID does not exist, this tool creates a new node set. This function is suitable when the user wants to add more nodes to a node set without deleting existing nodes. The node selection logic is exactly the same as `find_nodes_by_criteria`.\n\n"
                "This tool flexibly understands various user input formats, "
                "including **English descriptions (e.g., 'find points where X is between 10 and 20'), English descriptions (e.g., 'X from 10 to 20', 'Y between 5 and 15'), "
                "mathematical inequalities (e.g., '10<x<20', 'Y>50', 'Z<=30', 'x=-500'), concise number lists (e.g., 'x,10,20' or 'y 50 100'), "
                "and any combination thereof.**\n\n"
                "**Core Parsing Rules:**\n"
                "1. **Mandatory Range Parameter Format**: Regardless of how the user describes it, `x_range`, `y_range`, and `z_range` parameters **must ultimately** be provided in the form `[min_value, max_value]`. If a single value is provided (e.g., 'X=100'), it is parsed as `[value, value]` (e.g., `[100, 100]`).\n"
                "2. **Intelligent Range Correction**: If the range entered by the user is logically 'reversed' (e.g., negative numbers like `\"-700<y<-1000\"`, which logically means `y` should be between `-1000` and `-700`), the model **must intelligently identify and automatically reorder the range to the correct `[min, max]` order**. For example, parse `-700<y<-1000` as `y_range=[-1000, -700]`; parse `Y from 100 to 50` as `y_range=[50, 100]`.\n"
                "3. **Interval Understanding**: By default, all ranges are closed intervals (including boundary values)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path": {
                        "type": "string",
                        "description": "Full path to the K file or TXT file containing node data (e.g., solid_nodes.txt or surface_nodes.txt). This parameter should be automatically provided by the system based on the current operation state, typically `solid_nodes.txt` or `surface_nodes.txt`.",
                    },
                    "target_sid": {
                        "type": "integer",
                        "description": "The SID (Set ID) of the target node set to append new nodes to."
                    },
                    "title_string": {
                        "type": "string",
                        "description": "Title or description for the node set. If the target SID does not exist, a new node set will be created using this title."
                    },
                    "input_kfile_path_for_read": {
                        "type": "string",
                        "description": "Full path to the original K file for reading (and writing). This parameter should be automatically provided by the system, typically the path of the K file currently being operated on."
                    },
                    "output_kfile_path_for_write": {
                        "type": "string",
                        "description": "Full path where the modified K file will be saved. This parameter should be automatically provided by the system, typically the path of the K file currently being operated on."
                    },
                    "criteria_type": {
                        "type": "string",
                        "description": "Search type, 'min_y' to find nodes with global minimum Y coordinate, 'coord_range' to find by coordinate range. Defaults to 'coord_range'.",
                        "enum": ["min_y", "coord_range"],
                        "default": "coord_range"
                    },
                    "tolerance": {
                        "type": "number",
                        "description": "Floating-point tolerance for coordinate matching, used for exact value or range boundary comparisons. For example, if x=100 and tolerance is 0.1, X values from 99.9 to 100.1 are considered a match. Defaults to 0.1.",
                        "default": 0.1
                    },
                    "x_range": {
                        "type": "array",
                        "description": "X coordinate range, a list containing two floating-point numbers (or null), e.g., `[min_x, max_x]`. Please ensure `min_x` is always less than or equal to `max_x`; if logic is reversed, please automatically correct according to the core parsing rules above.",
                        "items": {"type": ["number", "null"]},
                        "maxItems": 2,
                        "minItems": 2,
                        "default": [None, None]
                    },
                    "y_range": {
                        "type": "array",
                        "description": "Y coordinate range, format and description same as X coordinate range. Please ensure `min_y` is always less than or equal to `max_y`; if logic is reversed, please automatically correct according to the core parsing rules above.",
                        "items": {"type": ["number", "null"]},
                        "maxItems": 2,
                        "minItems": 2,
                        "default": [None, None]
                    },
                    "z_range": {
                        "type": "array",
                        "description": "Z coordinate range, format and description same as X coordinate range. Please ensure `min_z` is always less than or equal to `max_z`; if logic is reversed, please automatically correct according to the core parsing rules above.",
                        "items": {"type": ["number", "null"]},
                        "maxItems": 2,
                        "minItems": 2,
                        "default": [None, None]
                    }
                },
                "required": ["k_file_path", "target_sid", "title_string", "input_kfile_path_for_read", "output_kfile_path_for_write"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_solid_element_nodes_and_save_node_data",
            "description": "Reads all nodes (n1 to n8) from the *ELEMENT_SOLID section of the original K file, collects these unique node IDs, then filters all matching node lines from the *NODE section, and saves these lines to a new TXT file. This operation should be performed first so that subsequent node selection tools can operate on this extracted node set.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_filepath": {
                        "type": "string",
                        "description": "Full path to the original LS-DYNA K file to read. This parameter should be automatically provided by the system."
                    },
                    "output_txt_filepath": {
                        "type": "string",
                        "description": "Full path to the new TXT file to save the filtered node data. This parameter should be automatically provided by the system, typically `solid_nodes.txt`."
                    }
                },
                "required": ["k_filepath", "output_txt_filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_surface_nodes_workflow",
            "description": "Identifies and extracts the model's surface nodes from the extracted solid element node file (solid_nodes.txt) and saves these surface nodes to a new TXT file (surface_nodes.txt). This function uses the KNN-PCA algorithm to robustly handle L-shaped or non-axis-aligned complex geometries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_node_filepath": {
                        "type": "string",
                        "description": "Full path to the input TXT file containing all solid element nodes, typically `solid_nodes.txt`. This parameter should be automatically provided by the system."
                    },
                    "output_surface_filepath": {
                        "type": "string",
                        "description": "Full path to the new TXT file to save extracted surface nodes, typically `surface_nodes.txt`. This parameter should be automatically provided by the system."
                    }
                },
                "required": ["input_node_filepath", "output_surface_filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "process_and_replace_nodeset_in_kfile",
            "description": "Writes the specified list of node IDs into the target node set (*SET_NODE_LIST_TITLE) block in the K file. If a node set with the target SID already exists, its content is replaced; otherwise, new content is appended after the last *SET_NODE_LIST_TITLE block in the K file. If no *SET_NODE_LIST_TITLE block is found, it is appended to the end of the file or before the *END keyword. This operation modifies the K file directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids_to_write": {
                        "type": "array",
                        "description": "List of all node IDs to write to the node set."
                    },
                    "target_sid": {
                        "type": "integer",
                        "description": "The SID (Set ID) of the node set to create or update."
                    },
                    "title_string": {
                        "type": "string",
                        "description": "Title or description for the node set."
                    },
                    "input_kfile_path_for_read": {
                        "type": "string",
                        "description": "Full path to the original K file for reading. This parameter should be automatically provided by the system, typically the path of the K file currently being operated on."
                    },
                    "output_kfile_path_for_write": {
                        "type": "string",
                        "description": "Full path where the modified K file will be saved. This parameter should be automatically provided by the system, typically the path of the K file currently being operated on."
                    }
                },
                "required": ["node_ids_to_write", "target_sid", "title_string", "input_kfile_path_for_read", "output_kfile_path_for_write"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_pulse_curve_to_kfile",
            "description": "Adds a *DEFINE_CURVE_TITLE block to the K file to define a time-amplitude curve (e.g., a shock pulse). This function inserts the curve sorted by LCID; if no other curves exist in the file, it inserts it after the last *PART block.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path_to_read": {"type": "string", "description": "Path to the original K file to read."},
                    "k_file_path_to_write": {"type": "string", "description": "Path to the new K file to save after modification."},
                    "title": {"type": "string", "description": "Title of the pulse curve."},
                    "lcid": {"type": "integer", "description": "ID of the pulse curve (Load Curve ID), must be unique."},
                    "points": {
                        "type": "array",
                        "description": "List of coordinate points for the pulse curve, where each point is a list in [x, y] format. Example: [[0, 0], [0.001, 1], [0.002, 0]].",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2
                        }
                    }
                },
                "required": ["k_file_path_to_read", "k_file_path_to_write", "title", "lcid", "points"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_load_node_set",
            "description": "Inserts a *LOAD_NODE_SET block above the first *PART keyword in the K file, applying a defined pulse curve to a specified node set.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path_to_read": {"type": "string", "description": "Path to the original K file to read."},
                    "k_file_path_to_write": {"type": "string", "description": "Path to the new K file to save after modification."},
                    "nsid": {"type": "integer", "description": "Node Set ID to apply the pulse to."},
                    "dof": {"type": "integer", "description": "Degree of freedom to apply the pulse (1=X, 2=Y, 3=Z, 4=RX, 5=RY, 6=RZ)."},
                    "lcid": {"type": "integer", "description": "LCID of the pulse curve to apply."}
                },
                "required": ["k_file_path_to_read", "k_file_path_to_write", "nsid", "dof", "lcid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_and_run_lsprepost_script",
            "description": "Generates a Tcl script and a batch file to launch LS-PrePost and load the specified K file. If a node set SID is provided, LS-PrePost will attempt to display only that node set; otherwise, it will display all parts. This function is primarily used for the user to visualize results after modifying the K file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path_to_open": {
                        "type": "string",
                        "description": "Full path of the K file to load when LS-PrePost starts. This parameter should be automatically provided by the system, typically the path of the K file currently being operated on."
                    },
                    "sid_to_show": {
                        "type": ["integer", "null"],
                        "description": "Optional Node Set SID. If provided, LS-PrePost will attempt to activate and show this node set; if null, all parts are shown."
                    }
                },
                "required": ["k_file_path_to_open"]
            }
        }
    },
    # --- Material Properties and Section Related Tools (New Features) ---
    {
        "type": "function",
        "function": {
            "name": "llm_modify_rebar_section",
            "description": "Modifies dimensions of an existing rebar section (*SECTION_BEAM or *SECTION_BEAM_TITLE) in the K file. Only TITLE, ts1, and ts2 can be modified; secid remains unchanged. This function modifies directly based on parameters provided by the LLM without user interaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path_to_read": {"type": "string", "description": "Path to the original LS-DYNA K file to read."},
                    "k_file_path_to_write": {"type": "string", "description": "Path to the new LS-DYNA K file to save after modification."},
                    "secid": {"type": "integer", "description": "Unique ID (secid) of the rebar section to modify."},
                    "TITLE": {"type": "string", "description": "New rebar section title (optional). If not provided, it remains unchanged."},
                    "ts1": {"type": "number", "description": "New ts1 value (optional). If not provided, it remains unchanged."},
                    "ts2": {"type": "number", "description": "New ts2 value (optional). If not provided, it remains unchanged."}
                },
                "required": ["k_file_path_to_read", "k_file_path_to_write", "secid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "llm_add_rebar_section",
            "description": "Adds a new rebar section (*SECTION_BEAM_TITLE) to the LS-DYNA K file. If the provided secid already exists, original content is replaced; otherwise, it is added. This function adds or replaces directly based on parameters provided by the LLM without user interaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path_to_read": {"type": "string", "description": "Path to the original LS-DYNA K file to read."},
                    "k_file_path_to_write": {"type": "string", "description": "Path to the new LS-DYNA K file to save after modification."},
                    "secid": {"type": "integer", "description": "Unique ID (secid) for the added or replaced rebar section."},
                    "TITLE": {"type": "string", "description": "Title for the new rebar section."},
                    "ts1": {"type": "number", "description": "New ts1 value."},
                    "ts2": {"type": "number", "description": "New ts2 value."}
                },
                "required": ["k_file_path_to_read", "k_file_path_to_write", "secid", "TITLE", "ts1", "ts2"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_material_rebar_or_concrete",
            "description": "Adds or modifies a rebar material (*MAT_PLASTIC_KINEMATIC_TITLE) or concrete material (*MAT_CSCM_CONCRETE_TITLE) definition in the LS-DYNA K file. The user can provide the material type ('rebar' or 'concrete'), MID, title, and all relevant material property parameters. This function prompts the user for details via an interactive command line, but prioritizes parameters if the LLM has already provided them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path_to_read": {"type": "string", "description": "Path to the original LS-DYNA K file to read.", "default": "<Auto-filled current K file path>"},
                    "k_file_path_to_write": {"type": "string", "description": "Path to the new LS-DYNA K file to save after modification.", "default": "<Auto-filled current K file path>"},
                    "material_type": {"type": "string", "description": "Type of material to add or modify, can be 'rebar' or 'concrete'.", "enum": ["rebar", "concrete"]},
                    "mid": {"type": "integer", "description": "Material ID (mid)."},
                    "material_title": {"type": "string", "description": "Title of the material."},
                    
                    # --- Removed from nested 'parameters', placed directly under top-level properties ---
                    # Concrete material parameters (Example, please list fully according to default_params in tools.py)
                    "ro": {"type": "number", "description": "Mass density."},
                    "nplot": {"type": "integer", "description": "NPLOT parameter."},
                    "incre": {"type": "number", "description": "INCRE parameter."},
                    "irate": {"type": "integer", "description": "IRATE parameter."},
                    "erode": {"type": "number", "description": "ERODE parameter."},
                    "recov": {"type": "number", "description": "RECOV parameter."},
                    "itretrc": {"type": "integer", "description": "ITRETRC parameter."},
                    "pred": {"type": "number", "description": "PRED parameter."},
                    "fpc": {"type": "number", "description": "Concrete compressive strength."},
                    "dagg": {"type": "number", "description": "Aggregate size."},
                    "units": {"type": "integer", "description": "Unit system."},

                    # Rebar material parameters (Example, please list fully according to default_params in tools.py)
                    "e": {"type": "number", "description": "Young's modulus."},
                    "pr": {"type": "number", "description": "Poisson's ratio."},
                    "sigy": {"type": "number", "description": "Yield strength."},
                    "etan": {"type": "number", "description": "Tangent modulus."},
                    "beta": {"type": "number", "description": "BETA parameter."},
                    "src": {"type": "number", "description": "SRC parameter."},
                    "srp": {"type": "number", "description": "SRP parameter."},
                    "fs": {"type": "number", "description": "FS parameter."},
                    "vp": {"type": "number", "description": "VP parameter."}
                    # --- End of removed section ---
                },
                "required": ["material_type"] # Only material_type is required, other parameters are decided by LLM whether to provide
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_formatted_sections_info",
            "description": "Retrieves information on all available rebar sections (*SECTION_BEAM) in the K file and returns it as a formatted table string. This function is non-interactive and used for the LLM to directly query and display existing section information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path": {"type": "string", "description": "Path of the LS-DYNA K file currently being operated on."}
                },
                "required": ["k_file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_formatted_materials_info",
            "description": "Retrieves information on all available materials (*MAT) in the K file and returns it as a formatted table string. This function is non-interactive and used for the LLM to directly query and display existing material information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "k_file_path": {"type": "string", "description": "Path of the LS-DYNA K file currently being operated on."}
                },
                "required": ["k_file_path"]
            }
        }
    },
        {
        "type": "function",
        "function": {
            "name": "visualize_part_workflow",
            "description": "Launches LS-PrePost based on the specified Part ID, loads the K file, displays only that part, and waits for user confirmation before continuing. Used when the user wants to view a specific part.",
            "parameters": {
                "type": "object",
                "properties": {
                    "part_id": {
                        "type": "integer",
                        "description": "Numeric ID of the part to visualize."
                    },
                    "k_file_path": {
                        "type": "string",
                        "description": "Full path to the LS-DYNA K file, should be auto-filled by system.",
                        "default": "AUTO_FILLED" # LLM should auto-fill
                    },
                    "cfile_template_path_for_viz": {
                        "type": "string",
                        "description": "Path to the LS-PrePost command stream template file used for visualizing the part, should be auto-filled by system.",
                        "default": "AUTO_FILLED" # LLM should auto-fill
                    },
                    "lsprepost_path": {
                        "type": "string",
                        "description": "Path to the LS-PrePost executable, should be auto-filled by system.",
                        "default": "AUTO_FILLED" # LLM should auto-fill
                    }
                },
                "required": ["part_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "assign_material_and_section_workflow",
            "description": "Assigns material and section to a specified part in the K file, and allows the user to modify the part title. This is an interactive process that prompts the user for details. If the LLM can infer the material or section ID from the user's request, it can be passed as an initial value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "part_id": {
                        "type": "integer",
                        "description": "Numeric ID of the part to operate on."
                    },
                    "k_file_path": {
                        "type": "string",
                        "description": "Full path to the LS-DYNA K file, should be auto-filled by system.",
                        "default": "AUTO_FILLED" # LLM should auto-fill
                    },
                    "assignment_cfile_template_path": {
                        "type": "string",
                        "description": "Path to the LS-PrePost command stream template file used for assigning material/section, should be auto-filled by system.",
                        "default": "AUTO_FILLED" # LLM should auto-fill
                    },
                    "lsprepost_path": {
                        "type": "string",
                        "description": "Path to the LS-PrePost executable, should be auto-filled by system.",
                        "default": "AUTO_FILLED" # LLM should auto-fill
                    },
                    "initial_material_id": {
                        "type": "integer",
                        "description": "Initial material ID inferred by the LLM from the user request. Defaults to 0 if not explicitly specified by the user.",
                        "default": 0
                    },
                    "initial_section_id": {
                        "type": "integer",
                        "description": "Initial section ID inferred by the LLM from the user request. Defaults to 0 if not explicitly specified by the user.",
                        "default": 0
                    }
                },
                "required": ["part_id"]
            }
        }
    },
]
