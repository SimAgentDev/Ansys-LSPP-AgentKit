import subprocess
import time
import threading
import win32gui
import win32con
import win32process
import win32api
import win32clipboard
import ctypes
import requests
import toml
import re
import os
from pathlib import Path
from ctypes import wintypes
from collections import defaultdict 
from together import Together
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog
from PIL import Image, ImageTk


# ------------------------------ Load Configuration File ------------------------------
CONFIG_FILE = Path(__file__).parent / "config.toml"

def load_config():
    """Load the main configuration file, if it does not exist, create a template and exit"""
    if not CONFIG_FILE.exists():
        # Create a default configuration file template
        default_config = '''# ==================== System Path Configuration ====================
[paths]
ansys_exe_path = "D:\\\\ANSYS18\\\\v180\\\\ANSYS\\\\bin\\\\winx64\\\\MAPDL.exe"
apdl_working_dir = "E:\\\\project\\\\LS_PrePost_Agent\\\\reference\\\\hulan_task\\\\build_model_task\\\\Datasets"
case_toml_path = "APDL_build_model/document/LLM_ANSYS_Barrier_Case_V6.toml"
default_save_path = "E:\\\\project\\\\LS_PrePost_Agent\\\\APDL_build_model\\\\work_path\\\\ansys_barrier_model.txt"
llm_history_dir = "E:\\\\project\\\\LS_PrePost_Agent\\\\APDL_build_model\\\\work_path\\\\llm_history"
step_images_dir = "step_images"

# ==================== ANSYS Window Related Configuration ====================
[ansys]
window_title = "ANSYS LS-DYNA Utility Menu"
dialog_titles = ["Verify", "Error", "Warning"]
base_wait_time = 5
dialog_interval = 2
first_dialog_timeout = 2
max_dialog_count = 5
activation_retries = 1

# ==================== LLM Model Configuration ====================
[[llm.models]]
name = "DeepSeek-V3 (SiliconFlow)"
type = "siliconflow"
api_url = "https://api.siliconflow.cn/v1/chat/completions"
api_token = "your_siliconflow_token_here"
model = "Pro/deepseek-ai/DeepSeek-V3"

[[llm.models]]
name = "DeepSeek-V3.2 (SiliconFlow)"
type = "siliconflow"
api_url = "https://api.siliconflow.cn/v1/chat/completions"
api_token = "your_siliconflow_token_here"
model = "deepseek-ai/DeepSeek-V3.2"

[[llm.models]]
name = "Llama-3.1-8B (Together)"
type = "together"
api_url = ""
api_token = "your_together_token_here"
model = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"

[[llm.models]]
name = "Llama-3.3-70B (Together)"
type = "together"
api_url = ""
api_token = "your_together_token_here"
model = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
'''
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.write(default_config)
            messagebox.showwarning(
                "Configuration file missing",
                f"Configuration file not found; a template has been automatically created：\n{CONFIG_FILE}\n\n"
                "Please edit this file, enter the correct paths and API keys, then rerun the program."
            )
            return None
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create the configuration file：{str(e)}")
            return None

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = toml.load(f)
        return config
    except Exception as e:
        messagebox.showerror("Configuration Error", f"Failed to parse the configuration file：{str(e)}")
        return None


# Load the global configuration
CONFIG = load_config()
if CONFIG is None:
    exit(1)

# Extract common constants from the configuration
ANSYS_PATH = CONFIG["paths"]["ansys_exe_path"]
APDL_WORKING_DIR = CONFIG["paths"]["apdl_working_dir"]
CASE_PATH_COMPLEX = Path(CONFIG["paths"]["case_toml_path"])
DEFAULT_SAVE_PATH = Path(CONFIG["paths"]["default_save_path"])
LLM_HISTORY_DIR = Path(CONFIG["paths"]["llm_history_dir"])
STEP_IMAGES_DIR = Path(CONFIG["paths"]["step_images_dir"])

ANSYS_WINDOW_TITLE = CONFIG["ansys"]["window_title"]
DIALOG_TITLES = CONFIG["ansys"]["dialog_titles"]
BASE_WAIT_TIME = CONFIG["ansys"]["base_wait_time"]
DIALOG_INTERVAL = CONFIG["ansys"]["dialog_interval"]
FIRST_DIALOG_TIMEOUT = CONFIG["ansys"]["first_dialog_timeout"]
MAX_DIALOG_COUNT = CONFIG["ansys"]["max_dialog_count"]
ACTIVATION_RETRIES = CONFIG["ansys"]["activation_retries"]

# # Step classification (fixed business logic, no configuration required)
COMMON_FIXED_STEPS = {0, 1, 2, 6, 7, 8, 9, 10, 17}
COMMON_INTERACTIVE_STEPS = {11, 12, 13, 14, 15, 16}


# Image canvas component with zoom and drag support
class ImageCanvas(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent,** kwargs)
        
        self.original_image = None
        self.display_image = None
        self.image_id = None
        
        self.scale = 0.4
        self.offset_x = 0
        self.offset_y = 0
        self.start_x = 0
        self.start_y = 0
        self.dragging = False
        
        self.bind("<MouseWheel>", self.on_mouse_wheel)
        self.bind("<Button-1>", self.on_button_press)
        self.bind("<B1-Motion>", self.on_mouse_drag)
        self.bind("<ButtonRelease-1>", self.on_button_release)
        self.bind("<Configure>", self.on_resize)
        
        self.prompt_text = self.create_text(
            0, 0, text="No image to display", anchor=tk.CENTER,
            font=("Arial", 12)
        )
    
    def set_image(self, image_path):
        self.original_image = None
        self.display_image = None
        if self.image_id:
            self.delete(self.image_id)
            self.image_id = None
        
        try:
            with Image.open(image_path) as img:
                self.original_image = img.copy()
                self.reset_view()
                self.update_display()
                return True
        except Exception as e:
            self.update_prompt(f"Error loading image:\n{str(e)}")
            return False
    
    def update_prompt(self, text):
        self.delete(self.prompt_text)
        self.prompt_text = self.create_text(
            self.winfo_width() // 2, self.winfo_height() // 2,
            text=text, anchor=tk.CENTER, font=("Arial", 12),
            fill="red"
        )
    
    def reset_view(self):
        self.scale = 0.4
        self.offset_x = 0
        self.offset_y = 0
    
    def on_mouse_wheel(self, event):
        if not self.original_image:
            return
            
        x = self.canvasx(event.x)
        y = self.canvasy(event.y)
        
        scale_factor = 1.1 if event.delta > 0 else 0.9
        new_scale = self.scale * scale_factor
        
        if 0.1 <= new_scale <= 5.0:
            self.offset_x = x - (x - self.offset_x) * scale_factor
            self.offset_y = y - (y - self.offset_y) * scale_factor
            self.scale = new_scale
            self.update_display()
    
    def on_button_press(self, event):
        if not self.original_image:
            return
            
        self.start_x = event.x
        self.start_y = event.y
        self.dragging = True
        self.config(cursor="fleur")
    
    def on_mouse_drag(self, event):
        if not self.dragging or not self.original_image:
            return
            
        dx = event.x - self.start_x
        dy = event.y - self.start_y
        
        self.offset_x += dx
        self.offset_y += dy
        self.start_x = event.x
        self.start_y = event.y
        
        self.update_display()
    
    def on_button_release(self, event):
        self.dragging = False
        self.config(cursor="")
    
    def on_resize(self, event):
        self.delete(self.prompt_text)
        self.prompt_text = self.create_text(
            event.width // 2, event.height // 2,
            text="No image to display" if not self.original_image else "",
            anchor=tk.CENTER, font=("Arial", 12)
        )
        
        if self.original_image:
            self.update_display()
    
    def update_display(self):
        if not self.original_image:
            return
            
        width = int(self.original_image.width * self.scale)
        height = int(self.original_image.height * self.scale)
        
        resized_img = self.original_image.resize(
            (width, height), Image.Resampling.LANCZOS
        )
        self.display_image = ImageTk.PhotoImage(resized_img)
        
        if self.image_id:
            self.delete(self.image_id)
        
        x = self.offset_x
        y = self.offset_y
        
        self.image_id = self.create_image(x, y, anchor=tk.NW, image=self.display_image)
        self.tag_lower(self.image_id)


# GUI Main Window Class
class APDLModelingGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ANSYS Barrier Modeling System")
        self.root.geometry("1100x800")
        self.root.minsize(900, 600)

        # Add binding for the window resize event
        self.root.bind("<Configure>", self.on_window_configure)
        
        self.default_font = ("Arial", 14)
        self.code_font = ("Consolas", 14)
        
        self.current_step = None
        self.step_codes = {}
        self.conversation_history = []
        self.llm_client = None
        self.save_path = None
        self.model_type = "complex"
        self.all_steps = []
        self.is_input_enabled = True
        
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Construct the image path from the configured `step_images_dir`
        self.step_images = {
            3: STEP_IMAGES_DIR / "step_3.png",
            4: STEP_IMAGES_DIR / "step_4.png",
            5: STEP_IMAGES_DIR / "step_5.png",
            11: STEP_IMAGES_DIR / "step_11.png",
            12: STEP_IMAGES_DIR / "step_12.png",
            13: STEP_IMAGES_DIR / "step_13.png",
            14: STEP_IMAGES_DIR / "step_14.png",
            15: STEP_IMAGES_DIR / "step_15.png",
            16: STEP_IMAGES_DIR / "step_16.png"
        }
        # Convert to an absolute path (relative to the program directory)
        self.step_images = {k: (self.app_dir / v if not v.is_absolute() else v) for k, v in self.step_images.items()}
        self.current_image = None
        
        self.ensure_image_directory_exists()
        self.init_ui()

    def on_window_configure(self, event):
        """Handle window resize events"""
        if event.widget == self.root:
            pass
        
    def ensure_image_directory_exists(self):
        image_dir = self.app_dir / STEP_IMAGES_DIR
        if not image_dir.exists():
            try:
                image_dir.mkdir(parents=True, exist_ok=True)
                self.log(f"Created image directory: {image_dir}")
                messagebox.showinfo("Info", f"Image directory created: {image_dir}\nPlease place images in this directory")
            except Exception as e:
                self.log(f"Failed to create image directory: {str(e)}")
                messagebox.showerror("Error", f"Failed to create image directory: {str(e)}")
    
    def init_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.process_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.process_frame, text="Modeling Process")
        
        self.create_resizable_panels()
        
        self.steps_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.steps_frame, text="Steps List")
        
        self.steps_listbox = tk.Listbox(self.steps_frame, font=self.default_font)
        self.steps_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.steps_listbox.config(state=tk.DISABLED)
        
        self.status_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.status_frame, text="System Status")
        
        self.status_text = scrolledtext.ScrolledText(
            self.status_frame, wrap=tk.WORD, font=self.default_font
        )
        self.status_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.status_text.config(state=tk.DISABLED)
        
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W, font=self.default_font)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
    def create_resizable_panels(self):
        self.paned_window = ttk.PanedWindow(self.process_frame, orient=tk.VERTICAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        step_image_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(step_image_frame, weight=1)
        
        left_frame = ttk.Frame(step_image_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        ttk.Label(left_frame, text="Current Step Information:", font=("Arial", 14, "bold")).pack(anchor=tk.W, padx=5, pady=2)
        self.step_display = scrolledtext.ScrolledText(
            left_frame, wrap=tk.WORD, font=self.default_font, height=8
        )
        self.step_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        self.step_display.config(state=tk.DISABLED)
        
        right_frame = ttk.Frame(step_image_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        ttk.Label(right_frame, text="Step Diagram:", font=("Arial", 14, "bold")).pack(anchor=tk.W, padx=5, pady=2)
        self.image_frame = ttk.LabelFrame(right_frame, text="")
        self.image_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        
        self.image_canvas = ImageCanvas(self.image_frame, bg="white", highlightthickness=0)
        self.image_canvas.pack(fill=tk.BOTH, expand=True)
        
        code_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(code_frame, weight=1)
        
        ttk.Label(code_frame, text="Generated APDL Code:", font=("Arial", 14, "bold")).pack(anchor=tk.W, padx=5, pady=2)
        self.code_display = scrolledtext.ScrolledText(
            code_frame, wrap=tk.WORD, font=self.code_font, height=15
        )
        self.code_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        self.code_display.config(state=tk.DISABLED)
        
        input_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(input_frame, weight=1)

        # 使用grid布局
        input_frame.columnconfigure(0, weight=1)
        input_frame.columnconfigure(1, weight=0)
        
        ttk.Label(input_frame, text="Please enter information:", font=self.default_font).grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=2
        )

        if not hasattr(self, 'input_controls_frame_created'):
            input_controls_frame = ttk.Frame(input_frame)
            input_controls_frame.grid(row=1, column=1, sticky=tk.NSEW, padx=5, pady=2)

            self.no_problem_btn = ttk.Button(
                input_controls_frame, 
                text="No Problem", 
                command=lambda: self.main_app.process_feedback_button("no problem")
            )
            self.no_problem_btn.pack(fill=tk.X, pady=(0, 2))
            
            self.needs_modification_btn = ttk.Button(
                input_controls_frame, 
                text="Needs Modification", 
                command=lambda: self.main_app.process_feedback_button("needs modification")
            )
            self.needs_modification_btn.pack(fill=tk.X, pady=(0, 2))

            self.submit_btn = ttk.Button(input_controls_frame, text="Submit", command=self.submit_input)
            self.submit_btn.pack(fill=tk.X, pady=(0, 5))

            self.input_controls_frame_created = True
        
        self.user_input = scrolledtext.ScrolledText(
            input_frame, font=self.default_font, wrap=tk.WORD, height=3
        )
        self.user_input.grid(row=1, column=0, sticky=tk.NSEW, padx=5, pady=2)
        self.user_input.bind("<Return>", lambda e: self.submit_input() if not e.state & 0x10 else None)
        
        self.no_problem_btn.config(state=tk.DISABLED)
        self.needs_modification_btn.config(state=tk.DISABLED)
        
        self.setup_input_context_menu()

    def set_feedback_buttons_state(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.root.after(0, lambda: self.no_problem_btn.config(state=state))
        self.root.after(0, lambda: self.needs_modification_btn.config(state=state))
    
    def setup_input_context_menu(self):
        self.context_menu = tk.Menu(self.user_input, tearoff=0)
        self.context_menu.add_command(label="Cut", command=lambda: self.user_input.event_generate("<<Cut>>"))
        self.context_menu.add_command(label="Copy", command=lambda: self.user_input.event_generate("<<Copy>>"))
        self.context_menu.add_command(label="Paste", command=lambda: self.user_input.event_generate("<<Paste>>"))
        self.user_input.bind("<Button-3>", self.show_context_menu)
    
    def show_context_menu(self, event):
        self.context_menu.post(event.x_root, event.y_root)
    
    def set_input_state(self, enabled):
        self.is_input_enabled = enabled
        state = tk.NORMAL if enabled else tk.DISABLED
        self.user_input.config(state=state)
        self.submit_btn.config(state=state)
        
    def log(self, message):
        self.status_text.config(state=tk.NORMAL)
        self.status_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)
        self.status_bar.config(text=message)
        self.root.update_idletasks()
    
    def display_step_image(self, step_num):
        if step_num not in self.step_images:
            self.image_canvas.update_prompt(f"No diagram for step {step_num}")
            return
            
        image_path = self.step_images[step_num]
        self.log(f"Attempting to load image: {image_path}")
            
        if not image_path.exists():
            self.image_canvas.update_prompt(f"Image not found:\n{image_path}")
            self.log(f"Warning: Missing image file - {image_path}")
            return
            
        try:
            success = self.image_canvas.set_image(str(image_path))
            if success:
                self.log(f"Successfully loaded image for step {step_num}")
            else:
                self.log(f"Error loading image for step {step_num}")
        except Exception as e:
            self.log(f"Error loading image for step {step_num}: {str(e)}")
            self.image_canvas.update_prompt(f"Failed to load image:\n{str(e)}")
    
    def update_step_display(self, text):
        text = text.replace("According to the user's idea, here is the code for step 3:", "")
        text = text.replace("**Generated Code:**", "")
        
        if "```apdl" in text:
            parts = re.split(r'```apdl[\s\S]*?```', text, flags=re.IGNORECASE)
            text = ''.join(parts)
        
        keywords = ["no problem", "no issues", "no need to modify", "okay", "can do", "needs modification"]
        for keyword in keywords:
            text = text.replace(keyword, f"**{keyword}**")
        
        self.step_display.config(state=tk.NORMAL)
        self.step_display.delete(1.0, tk.END)
        self.step_display.insert(tk.END, text)
        self.apply_bold_tags()
        self.step_display.config(state=tk.DISABLED)
    
    def apply_bold_tags(self):
        start_pos = "1.0"
        while True:
            start_pos = self.step_display.search("**", start_pos, stopindex=tk.END)
            if not start_pos:
                break
            end_pos = self.step_display.search("**", f"{start_pos}+2c", stopindex=tk.END)
            if not end_pos:
                break
            self.step_display.tag_add("bold", f"{start_pos}+2c", end_pos)
            start_pos = f"{end_pos}+2c"
        self.step_display.tag_config("bold", font=("Arial", 16, "bold"))
        
    def update_code_display(self, code):
        self.code_display.config(state=tk.NORMAL)
        self.code_display.delete(1.0, tk.END)
        self.code_display.insert(tk.END, code)
        self.code_display.config(state=tk.DISABLED)
        
    def update_steps_list(self, steps):
        self.steps_listbox.config(state=tk.NORMAL)
        self.steps_listbox.delete(0, tk.END)
        for step in steps:
            status = "✓" if step["num"] in self.step_codes else " "
            self.steps_listbox.insert(tk.END, f"[{status}] Step {step['num']}: {step['name']}")
        self.steps_listbox.config(state=tk.DISABLED)
        
    def clear_input(self):
        self.user_input.delete(1.0, tk.END)
        
    def submit_input(self):
        if not self.is_input_enabled:
            messagebox.showwarning("Warning", "Input is currently disabled. Please wait for the operation to complete.")
            return
        user_input = self.user_input.get(1.0, tk.END).strip()
        if not user_input:
            messagebox.showwarning("Prompt", "Input cannot be empty!")
            return
        self.main_app.process_user_input(user_input)
        self.clear_input()


# LLM call abstraction layer with retry mechanism
class LLMClient:
    def __init__(self, config):
        self.config = config
        self.headers = self._create_headers()
        self.max_retries = 5
        self.retry_delay = 3
        self.last_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}  
        
    def _create_headers(self):
        return {
            "Authorization": f"Bearer {self.config.get('api_token')}",
            "Content-Type": "application/json"
        }
        
    def generate_response(self, conversation_history, temperature=0.2, max_tokens=2500):
        raise NotImplementedError("Subclasses must implement generate_response method")

    def get_last_token_usage(self): 
        return self.last_token_usage.copy()


class SiliconFlowClient(LLMClient):
    def generate_response(self, conversation_history, temperature=0.2, max_tokens=2500):
        payload = {
            "model": self.config.get("model"),
            "messages": conversation_history,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        for attempt in range(self.max_retries):
            try:
                response = requests.post(self.config.get("api_url"), json=payload, headers=self.headers)
                if response.status_code == 503:
                    print(f"Service unavailable (503), retry {attempt + 1}...")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (attempt + 1))
                    continue
                if response.status_code != 200:
                    print(f"LLM call failed: {response.status_code}")
                    if attempt < self.max_retries - 1:
                        print(f"Retry {attempt + 1}...")
                        time.sleep(self.retry_delay * (attempt + 1))
                    continue
                response_data = response.json()
                if 'usage' in response_data:
                    self.last_token_usage = response_data['usage']
                else:
                    self.last_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"SiliconFlow call error: {e}")
                if attempt < self.max_retries - 1:
                    print(f"Retry {attempt + 1}...")
                    time.sleep(self.retry_delay * (attempt + 1))
        print(f"Max retries reached, call failed")
        return None


class OpenAIClient(LLMClient):
    def _create_headers(self):
        return {
            "Authorization": f"Bearer {self.config.get('api_token')}",
            "Content-Type": "application/json"
        }
    
    def generate_response(self, conversation_history, temperature=0.2, max_tokens=2500):
        payload = {
            "model": self.config.get("model"),
            "messages": conversation_history,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if self.config.get("model", "").startswith("qwen3-"):
            payload["extra_body"] = {"enable_thinking": True}
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    self.config.get("api_url", "https://api.openai.com/v1/chat/completions"), 
                    json=payload, headers=self.headers
                )
                if response.status_code == 503:
                    print(f"Service unavailable (503), retry {attempt + 1}...")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (attempt + 1))
                    continue
                if response.status_code != 200:
                    print(f"LLM call failed: {response.status_code}, response: {response.text}")
                    if attempt < self.max_retries - 1:
                        print(f"Retry {attempt + 1}...")
                        time.sleep(self.retry_delay * (attempt + 1))
                    continue
                response_data = response.json()
                if 'usage' in response_data:
                    self.last_token_usage = response_data['usage']
                else:
                    self.last_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}       
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"OpenAI call error: {e}")
                if attempt < self.max_retries - 1:
                    print(f"Retry {attempt + 1}...")
                    time.sleep(self.retry_delay * (attempt + 1))
        print(f"Max retries reached, call failed")
        return None


class TogetherClient(LLMClient):
    def __init__(self, config):
        super().__init__(config)
        self.client = Together(api_key=self.config.get('api_token'))
        
    def _create_headers(self):
        return {}
    
    def generate_response(self, conversation_history, temperature=0.2, max_tokens=2500):
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.get("model"),
                    messages=conversation_history,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                if hasattr(response, 'usage') and response.usage:
                    self.last_token_usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens
                    }
                else:
                    self.last_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                return response.choices[0].message.content
            except Exception as e:
                if hasattr(e, 'response') and e.response is not None and e.response.status_code == 503:
                    error_type = "Service unavailable (503)"
                else:
                    error_type = str(e)
                print(f"Together API error: {error_type}")
                if attempt < self.max_retries - 1:
                    print(f"Retry {attempt + 1}...")
                    time.sleep(self.retry_delay * (attempt + 1))
        print(f"Max retries reached, call failed")
        return None


class LLMClientFactory:
    @staticmethod
    def create_client(config):
        client_type = config.get("type", "").lower()
        if client_type == "siliconflow":
            return SiliconFlowClient(config)
        elif client_type == "together":
            return TogetherClient(config)
        elif client_type == "openai":
            return OpenAIClient(config)
        else:
            raise ValueError(f"Unsupported client type: {client_type}")


current_step_response = ""
apdl_hwnd = None
apdl_proc = None
last_activation_time = 0
activation_valid_duration = 3


# Window activation core optimization
def is_window_already_active(hwnd):
    if not hwnd:
        return False
    return win32gui.GetForegroundWindow() == hwnd

def force_alt_tab_switch():
    try:
        ctypes.windll.user32.keybd_event(18, 0, 0, 0)
        time.sleep(0.2)
        ctypes.windll.user32.keybd_event(9, 0, 0, 0)
        time.sleep(0.2)
        ctypes.windll.user32.keybd_event(9, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.2)
        ctypes.windll.user32.keybd_event(18, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"Alt+Tab switch failed: {e}")
        return False

def find_all_windows():
    windows = {}
    def callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows[hwnd] = title
    win32gui.EnumWindows(callback, None)
    return windows

def focus_window(hwnd, window_name):
    global last_activation_time
    if is_window_already_active(hwnd):
        print(f"{window_name} window already active, no need to reactivate")
        last_activation_time = time.time()
        return True
    if not hwnd:
        print(f"Invalid {window_name} window handle")
        return False
    try:
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement[1] == win32con.SW_SHOWMINIMIZED:
            print(f"{window_name} window minimized, attempting to restore...")
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.5)
    except Exception as e:
        print(f"Failed to check window status: {e}")
    try:
        print(f"Attempting to directly activate {window_name} window...")
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, 
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, 
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        if win32gui.GetForegroundWindow() == hwnd:
            print(f"Direct activation successful, {window_name} window activated")
            last_activation_time = time.time()
            return True
        else:
            print("Direct activation unsuccessful, attempting alternative method...")
    except Exception as e:
        print(f"Direct activation failed: {e}, attempting alternative method...")
    for attempt in range(ACTIVATION_RETRIES):
        try:
            print(f"Attempt {attempt+1}: Using Alt+Tab to switch to {window_name} window")
            if force_alt_tab_switch():
                time.sleep(0.5)
                if win32gui.GetForegroundWindow() == hwnd:
                    print(f"Attempt {attempt+1} successful, {window_name} window activated")
                    last_activation_time = time.time()
                    return True
        except Exception as e:
            print(f"Activation attempt {attempt+1} error: {e}")
        time.sleep(0.5)
    final_check = win32gui.GetForegroundWindow() == hwnd
    if final_check:
        print(f"Despite errors, {window_name} window was eventually activated")
        last_activation_time = time.time()
        return True
    print(f"All activation attempts failed, current foreground window: {win32gui.GetWindowText(win32gui.GetForegroundWindow())}")
    print("Current visible window list:")
    windows = find_all_windows()
    for hwnd, title in windows.items():
        print(f"Handle: {hwnd}, Title: {title}")
    return False


# APDL command sending function
def send_apdl_commands(hwnd, commands):
    global last_activation_time
    current_time = time.time()
    if current_time - last_activation_time < activation_valid_duration and is_window_already_active(hwnd):
        print("Window is active and within activation validity period, skipping reactivation")
        activation_success = True
    else:
        print("===== Starting ANSYS window activation =====")
        activation_success = focus_window(hwnd, ANSYS_WINDOW_TITLE)
    if not activation_success:
        print("Warning: ANSYS window activation may have failed, attempting to continue operation...")
        force_alt_tab_switch()
        time.sleep(1)
    switch_to_english_input()
    try:
        print("Preparing to copy step code to clipboard...")
        if not set_clipboard_text(commands):
            print("Clipboard operation failed, cannot send commands")
            return False
        if not is_window_already_active(hwnd):
            print("Detected window focus loss, attempting to reactivate...")
            if not focus_window(hwnd, ANSYS_WINDOW_TITLE):
                print("Reactivation failed, attempting to send commands anyway...")
            time.sleep(0.5)
        print("Pasting code into ANSYS command box...")
        win32api.keybd_event(17, 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(86, 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(86, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)
        win32api.keybd_event(17, 0, win32con.KEYEVENTF_KEYUP, 0)
        paste_delay = max(1.0, len(commands) / 1000)
        time.sleep(paste_delay)
        print(f"Pasting completed, waiting {paste_delay:.1f} seconds")
        print("Executing commands...")
        send_enter_key()
        dialog_count = 0
        processed_hwnds = []
        print("Starting to detect first dialog box...")
        dialog_found, dialog_hwnd, dialog_title = wait_for_first_dialog()
        if not dialog_found:
            print("Warning: First dialog box not detected, attempting to force send Enter key once")
            send_enter_key()
            dialog_found, dialog_hwnd, dialog_title = wait_for_first_dialog()
            if not dialog_found:
                print("Still no first dialog box detected, there may be no dialog boxes or detection failed")
                return True
        if dialog_found and dialog_hwnd:
            dialog_count += 1
            processed_hwnds.append(dialog_hwnd)
            print(f"Detected {dialog_count}th [{dialog_title}] dialog box (handle: {dialog_hwnd})")
            if focus_window(dialog_hwnd, dialog_title):
                send_enter_key()
                if wait_for_window_close(dialog_hwnd):
                    print(f"{dialog_count}th dialog box closed")
                else:
                    print(f"Warning: {dialog_count}th dialog box may not have closed, attempting to send Enter again")
                    send_enter_key()
                    win32gui.EnumWindows(lambda h, e: None, None)
                    time.sleep(1.0)
            else:
                print(f"Cannot activate {dialog_title} dialog box, attempting to send Enter directly")
                send_enter_key()
                time.sleep(1.0)
        while dialog_count < MAX_DIALOG_COUNT:
            print(f"Checking for new dialog boxes (processed {dialog_count} so far)...")
            dialog_found, dialog_hwnd, dialog_title = wait_for_next_dialog(processed_hwnds)
            if dialog_found and dialog_hwnd:
                dialog_count += 1
                processed_hwnds.append(dialog_hwnd)
                print(f"Detected {dialog_count}th [{dialog_title}] dialog box (handle: {dialog_hwnd})")
                if focus_window(dialog_hwnd, dialog_title):
                    send_enter_key()
                    if wait_for_window_close(dialog_hwnd):
                        print(f"{dialog_count}th dialog box closed")
                    else:
                        print(f"Warning: {dialog_count}th dialog box may not have closed")
                        send_enter_key()
                        win32gui.EnumWindows(lambda h, e: None, None)
                        time.sleep(1.0)
                else:
                    print(f"Cannot activate {dialog_title} dialog box, attempting to send Enter directly")
                    send_enter_key()
                    time.sleep(1.0)
                time.sleep(DIALOG_INTERVAL)
            else:
                print("No new dialog boxes detected, ending processing")
                break
        if dialog_count >= MAX_DIALOG_COUNT:
            print(f"Processed {MAX_DIALOG_COUNT} dialog boxes, limit reached, forcing end to avoid loop")
        print(f"Code execution completed, processed {dialog_count} dialog boxes in total")
        return True
    except Exception as e:
        print(f"Error sending commands: {e}")
        return False


# ------------------------------
# Main Application Logic Class
# ------------------------------
class APDLModelingApp:
    def __init__(self, gui):
        self.gui = gui
        self.gui.main_app = self
        self.current_step_index = 0
        self.user_inputs = {}
        self.in_feedback_phase = False
        self.save_path = None
        self.generation_count = 1
        self.llm_client = None
        self.model_name = None
        
    def start(self):
        self.gui.log("===== ANSYS Barrier Modeling and Execution System =====")
        self.gui.log("Integrating LLM code generation and APDL interaction functions~ \n")
        try:
            LLM_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            self.gui.log(f"LLM history will be saved to: {LLM_HISTORY_DIR}")
        except Exception as e:
            self.gui.log(f"Failed to create LLM history directory: {str(e)}")
            messagebox.showerror("Error", f"Cannot create LLM history directory: {str(e)}")
            return
        # # Retrieve the model list from the global configuration
        self.llm_models = CONFIG.get("llm", {}).get("models", [])
        if not self.llm_models:
            messagebox.showerror("Configuration Error", "No LLM models defined in the configuration file; please check the [llm.models] section of config.toml")
            return
        self.select_llm_model()

    def get_L_location_guidance(self):
        if 5 not in self.gui.step_codes:
            return "IMPORTANT: L value should be defined in Step 5, but Step 5 code not found in history."
        step5_code = self.gui.step_codes[5]["code"]
        code_preview = step5_code[:300]
        return f"""CRITICAL: You MUST find and use the ACTUAL L value from Step 5 code.

    WHERE TO FIND L VALUE:
    - Look in Step 5 generated APDL code for L definition
    - Search for patterns like: L=xxx, L = xxx, L: xxx
    - The L value is the user-provided total barrier length

    STEP 5 CODE PREVIEW (find L value here):
    {code_preview}...

    IMPORTANT: 
    - Extract the L value from the code above
    - For ITIME calculations in steps 12,13,14, use L (unit： mm)
    - CRITICAL: The L value extracted from Step 5 is in millimeters
    - Use the ACTUAL user-provided L value, NOT example values from template"""

    def process_feedback_button(self, feedback_type):
        if not self.in_feedback_phase:
            messagebox.showwarning("Warning", "Feedback buttons are only available during code review phase")
            return
        if feedback_type == "no problem":
            self.confirm_current_code()
        elif feedback_type == "needs modification":
            self.open_modification_dialog()
        else:
            messagebox.showwarning("Warning", "Unknown feedback type")

    def confirm_current_code(self):
        step_num = self.current_step["num"]
        step_name = self.current_step["name"]
        self.gui.log("Confirming code is correct via button click...")
        self.gui.step_codes[step_num] = {"name": step_name, "code": self.current_code}
        update_code_file(self.gui.step_codes, self.save_path)
        self.gui.update_steps_list(self.all_steps)
        current_text = self.gui.step_display.get(1.0, tk.END)
        confirmed_text = current_text + "\n\n--- Code confirmed via 'No Problem' button ---"
        self.gui.update_step_display(confirmed_text)
        self.current_step_index += 1
        self.process_next_step()

    def open_modification_dialog(self):
        feedback_window = tk.Toplevel(self.gui.root)
        feedback_window.title("Enter Modification Suggestions")
        feedback_window.geometry("500x200")
        feedback_window.transient(self.gui.root)
        feedback_window.grab_set()
        ttk.Label(feedback_window, text="Please specify what needs modification:", font=("Arial", 12)).pack(padx=10, pady=10, anchor=tk.W)
        feedback_text = scrolledtext.ScrolledText(feedback_window, font=("Segoe UI", 12), height=5)
        feedback_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        def confirm_feedback():
            feedback_detail = feedback_text.get(1.0, tk.END).strip()
            if not feedback_detail:
                messagebox.showwarning("Prompt", "Modification suggestions cannot be empty")
                return
            feedback_window.destroy()
            self.process_modification(feedback_detail)
        ttk.Button(feedback_window, text="Confirm", command=confirm_feedback).pack(pady=10)
        feedback_window.wait_window()

    def set_feedback_buttons_state(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.gui.root.after(0, lambda: self.gui.no_problem_btn.config(state=state))
        self.gui.root.after(0, lambda: self.gui.needs_modification_btn.config(state=state))

    def select_llm_model(self):
        model_window = tk.Toplevel(self.gui.root)
        model_window.title("Select Large Language Model")
        model_window.geometry("500x400")
        model_window.transient(self.gui.root)
        model_window.grab_set()
        ttk.Label(model_window, text="Please select the large language model to use:", font=("Arial", 12)).pack(padx=10, pady=10, anchor=tk.W)
        frame = ttk.Frame(model_window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        model_listbox = tk.Listbox(frame, font=("Segoe UI", 12), height=12, yscrollcommand=scrollbar.set)
        model_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=model_listbox.yview)
        model_names = [model["name"] for model in self.llm_models]
        for name in model_names:
            model_listbox.insert(tk.END, name)
        def confirm_selection():
            if not model_listbox.curselection():
                messagebox.showwarning("Prompt", "Please select a model")
                return
            selected_idx = model_listbox.curselection()[0]
            selected_config = self.llm_models[selected_idx]
            self.model_name = selected_config["name"]
            self.gui.log(f"Selected model: {self.model_name}")
            try:
                self.llm_client = LLMClientFactory.create_client(selected_config)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create LLM client: {str(e)}")
                model_window.destroy()
                return
            self.confirm_save_path()
            model_window.destroy()
        ttk.Button(model_window, text="Confirm", command=confirm_selection).pack(pady=10)
        model_window.wait_window()
        
    def confirm_save_path(self):
        default_dir = DEFAULT_SAVE_PATH.parent
        default_filename = DEFAULT_SAVE_PATH.name
        file_path = filedialog.asksaveasfilename(
            parent=self.gui.root,
            title="Select APDL Code Save Path",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(default_dir),
            initialfile=default_filename
        )
        if not file_path:
            messagebox.showwarning("Prompt", "Please select a save path to continue")
            return self.confirm_save_path()
        self.save_path = Path(file_path)
        self.gui.save_path = self.save_path
        self.gui.log(f"Code will be saved to: {self.save_path}")
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Cannot create save directory: {str(e)}")
            return self.confirm_save_path()
        self.load_case_and_start()
        
    def load_case_and_start(self):
        self.gui.log("Complex model selected, will model according to corresponding process")
        case_data = load_toml_file(CASE_PATH_COMPLEX)
        if not case_data:
            self.gui.log("Case document loading failed, exiting")
            messagebox.showerror("Error", "Case document loading failed")
            return
        self.all_steps = extract_case_steps(case_data)
        if not self.all_steps:
            self.gui.log("No valid steps extracted, exiting")
            messagebox.showerror("Error", "No valid steps extracted")
            return
        self.gui.update_steps_list(self.all_steps)
        system_prompt = """
    I. Identity and Core Objective
    You are an exclusive ANSYS barrier modeling expert, serving non-professional users. Your core objective is to help users complete barrier geometric modeling and reinforcement arrangement through "everyday language interaction + standardized APDL code", strictly following the principle of "case template first, modifying parameters within the basic framework".


    II. General Principles for Interaction and Code Generation
    1. Interaction language: Communicate in everyday language (avoid piling up engineering technical terms), for example "Please provide the value of the barrier base width, the default unit is millimeters~".
    2. Core requirements for code generation (must be strictly followed):
    - Completely follow the structure of the case code (command order, comment format, parameter naming);
    - Retain the verified command usage in the case (such as LGEN parameter order);
    - Modify specific values (such as dimensions, quantities, spacing) according to user input without changing the basic code framework.


    III. Detailed Explanation of Key Commands (Frequently Used: LGEN)
    Used for reinforcement replication generation, it is the core command for barrier modeling, requiring precise mastery of parameter meanings and usage:
    1. Command format: LGEN,ITIME,NL1,NL2,NINC,DX,DY,DZ,KINC,NOELEM,IMOVE
    2. Explanation of core parameters (only listing frequently modified parameters):
    - ITIME: Total number of generations (including original line), rule: ITIME = 1 original + n-1 new copies; example "copy 3 times" "add 3 new" both correspond to ITIME=3+1=4.
    - DX/DY/DZ: Copy direction and spacing, DX (5th parameter) corresponds to X direction, DY (6th parameter) corresponds to Y direction, DZ (7th parameter) corresponds to Z direction.
    3. Case (directly reuse format):
    ```apdl
    ! Select original reinforcement line with number 35
    lsel,s,line,,35
    ! Copy 3 times in Y direction (total 4), spacing 191 mm
    LGEN, 4, all, NL2, NINC, DX, 191, DZ, KINC, NOELEM, IMOVE
    ```


    IV. Core Modeling Rules
    1. Reinforcement Spacing and Quantity Matching Rules (Avoid Arrangement Conflicts)
    Applicable to stirrups and vertical reinforcements, need to ensure logical consistency between "spacing" and "ITIME":
    - Calculation logic: ITIME = (Total length L ÷ Spacing S) + 1 
    (Note: If Total length L is not divisible by Spacing S, use the floor of (L ÷ S) before adding 1.);
    - Case: Total length L=8229.6 mm, spacing S=-305 mm (negative sign indicates direction)→ ITIME = (8229.6 ÷ |-305|) +1=27+1=28, corresponding command:
    ```apdl
    LGEN, 28, all, NL2, NINC, , DY, -305, KINC, NOELEM, IMOVE
    ```

    2. Point/Line Numbering and Selection Rules (Avoid Numbering Confusion)
    (1) Point Numbering Rules
    - Must use *GET command at the beginning of the step to get the current maximum point number (KMAX), new point numbers start from "KMAX+1";
    - Each new point increases number by 1; each new line (requires 2 points) increases point number by 2;
    - Case:
    ```apdl
    ! Step 1: Get maximum number of existing points
    *GET, KMAX, KP,, NUM, MAX  
    ! Create 2 new points (numbers are KMAX+1, KMAX+2 in sequence)
    K, KMAX+1, 45.7, 191, 0  
    K, KMAX+2, 45.7, 191, -L  
    ```

    (2) Line Numbering and Selection Rules
    - Line numbering: Each new line increases number by 1, first line number is current maximum line number (LMAX);
    - Selection methods:
    By newly created line: After creating line, use "*GET,LMAX,LINE,0,NUM,MAX" to get number, then select.

    3. Arc Stirrup Modeling Rules (Indicator Point Method)
    **Core Calculation Formulas:**
    (1) **Midpoint Base Coordinate Calculation**
    - X Midpoint = (Start X Coordinate + End X Coordinate) ÷ 2
    - Y Midpoint = (Start Y Coordinate + End Y Coordinate) ÷ 2
    (2) **Horizontal Span Distance Calculation**
    - Horizontal Span = |End X Coordinate - Start X Coordinate|
    (3) **Indicator Point Offset Calculation**
    - Horizontal Offset = Horizontal Span × 10% (always offset to the right)
    - Vertical Offset = Horizontal Span × 40% (positive for upward convex, negative for downward concave)
    (4) **Final Indicator Point Coordinates**
    - Indicator X Coordinate = X Midpoint + Horizontal Offset
    - Indicator Y Coordinate = Y Midpoint + Vertical Offset
    - Indicator Z Coordinate = 0

    **Specific Application Examples:**
    **Example 1: Upward Convex Arc**
    - User provides: Start point (127, 178, 0), End point (254, 178, 0), Upward convex arc
    - Calculation process:
    - X Midpoint = (127 + 254) ÷ 2
    - Y Midpoint = (178 + 178) ÷ 2
    - Horizontal Span = |254 - 127|
    - Horizontal Offset = Horizontal Span × 0.1
    - Vertical Offset = Horizontal Span × 0.4 = |254 - 127| × 0.4 (positive for upward convex)

    ```apdl
    ! Indicator point 2000: Complete embedded calculation formula
    K,2000, ((127+254)/2)+(|254-127|*0.1), ((178+178)/2)+(|254-127|*0.4), 0
    ! Draw upward convex arc
    LARC, start_point_number, end_point_number, 2000
    ```
    **Example 2: Downward Concave Arc**
    Key difference: Vertical Offset is negative (- Horizontal Span × 0.4 = - |254 - 127| × 0.4 )

    ```apdl
    ! Indicator point 2001: Downward concave arc uses minus sign for Y coordinate
    K,2001, ((127+254)/2)+(|254-127|*0.1), ((178+178)/2)-(|254-127|*0.4), 0
    ! Draw downward concave arc
    LARC, start_point_number, end_point_number, 2001
    ```
    **Key Rules:**
    - **Upward Convex Arc**: Use `+ Horizontal Span × 0.4` for Y coordinate calculation
    - **Downward Concave Arc**: Use `- Horizontal Span × 0.4` for Y coordinate calculation
    - **Horizontal Offset**: Always use `+ Horizontal Span × 0.1` (offset to the right)

    4. Topology Conflict Avoidance Rules
    - If new point coordinates are exactly the same as existing points, must recognize as the same point and not create duplicates;
    - Must "remember" coordinates of built points in real-time during modeling (e.g., if (2,3,1) already exists, do not create new points with different numbers but same coordinates).
"""
        self.conversation_history = [{"role": "system", "content": system_prompt}]
        self.gui.log("Starting APDL...")
        threading.Thread(target=lambda: run_apdl(), daemon=True).start()
        self.process_next_step()
    
    def process_next_step(self):
        self.set_feedback_buttons_state(False)
        if self.current_step_index >= len(self.all_steps):
            self.finish_processing()
            return
        self.current_step = self.all_steps[self.current_step_index]
        self.in_feedback_phase = False
        step_num = self.current_step["num"]
        step_name = self.current_step["name"]
        self.gui.log(f"\n===== Now processing: Step {step_num} - {step_name} =====")
        step_info = f"Step {step_num}: {step_name}\n\n"
        self.gui.update_step_display(step_info)
        self.gui.display_step_image(step_num)
        self.gui.update_code_display("Waiting for input...")
        if self.current_step["is_fixed"]:
            threading.Thread(target=self.process_fixed_step, daemon=True).start()
        elif self.current_step["is_interactive"]:
            self.process_interactive_step()
    
    def process_fixed_step(self):
        step_num = self.current_step["num"]
        step_name = self.current_step["name"]
        step_code = self.current_step["code_template"]
        self.gui.root.after(0, lambda: self.gui.log("This is a fixed operation, code set according to case"))
        self.gui.root.after(0, lambda: self.gui.update_step_display(
            f"Step {step_num}: {step_name}\n\nThis is a fixed step, no input needed, executing..."))
        self.gui.root.after(0, lambda: self.gui.update_code_display("Generating code, please wait..."))
        pure_code = extract_pure_code(step_code)
        self.gui.step_codes[step_num] = {"name": step_name, "code": pure_code}
        update_code_file(self.gui.step_codes, self.save_path)
        self.gui.root.after(0, lambda: self.gui.update_code_display(pure_code))
        hwnd = run_apdl()
        if hwnd:
            send_apdl_commands(hwnd, pure_code)
        self.gui.log("Fixed step execution completed, proceeding to next step~")
        self.current_step_index += 1
        self.gui.root.after(0, lambda: self.gui.update_steps_list(self.all_steps))
        self.gui.root.after(1000, self.process_next_step)
    
    def process_interactive_step(self):
        step_num = self.current_step["num"]
        step_name = self.current_step["name"]
        step_templates = get_interactive_step_templates()
        step_template = step_templates.get(step_num, "You need to provide some information to complete this step")
        is_skippable = 11 <= step_num <= 16
        skip_hint = "\n\nHint: To skip this step, enter 'skip'" if is_skippable else ""
        self.gui.update_step_display(f"Step {step_num}: {step_name}\n\n{step_template}{skip_hint}")
        self.gui.display_step_image(step_num)
        self.conversation_history.append({"role": "assistant", "content": step_template})
        self.gui.root.after(0, lambda: self.gui.set_input_state(True))
        self.gui.root.after(0, lambda: self.gui.update_code_display("You can input now"))
        self.gui.user_input.focus_set()
    
    def process_user_input(self, user_input):
        step_num = self.current_step["num"]
        step_name = self.current_step["name"]
        is_skippable = 11 <= step_num <= 16
        self.user_inputs[step_num] = user_input
        if self.in_feedback_phase:
            self.process_feedback(user_input)
            return
        if user_input.lower() == "exit":
            self.gui.log("User exited modeling")
            messagebox.showinfo("Prompt", "Exited modeling")
            self.gui.root.quit()
            return
        if is_skippable and user_input.lower() == "skip":
            self.gui.log(f"Confirmed to skip step {step_num} - {step_name}")
            self.gui.step_codes[step_num] = {"name": step_name, "code": ""}
            update_code_file(self.gui.step_codes, self.save_path)
            self.gui.update_steps_list(self.all_steps)
            self.current_step_index += 1
            self.process_next_step()
            return
        if not user_input:
            messagebox.showwarning("Prompt", "Input cannot be empty, please provide information or enter 'skip' (only for skippable steps)~")
            return
        current_step_text = self.gui.step_display.get(1.0, tk.END)
        self.gui.update_step_display(current_step_text)
        self.gui.root.after(0, lambda: self.gui.set_input_state(False))
        self.gui.root.after(0, lambda: self.gui.update_code_display("Please pause operation now"))
        threading.Thread(target=self.generate_code_in_background, args=(user_input, step_num, step_name), daemon=True).start()
    
    def generate_code_in_background(self, user_input, step_num, step_name):
        L_guidance = ""
        if step_num in [12, 13, 14]:
            L_guidance = self.get_L_location_guidance()
        code_template = self.current_step["code_template"]
        user_msg = f"""User's idea: {user_input}. Please generate code for step {step_num}, requirements:
    1. Strictly refer to the format and logic of the following case code template: {code_template}
    2. Only modify specific values according to user needs, keep command structure, parameter names and comment style consistent with template
    3. First summarize modifications in plain language, then show code, finally ask if adjustments are needed

    {L_guidance}"""
        temp_conversation = [msg.copy() for msg in self.conversation_history]
        temp_conversation.append({"role": "user", "content": user_msg})
        self.gui.log(f"Performing 1 LLM call...")
        responses = []
        raw_codes = []
        token_usages = []
        try:
            self.gui.log(f"LLM call 1/1")
            step_response = self.llm_client.generate_response(temp_conversation, temperature=0.2, max_tokens=3400)
            token_usage = self.llm_client.get_last_token_usage()
            token_usages.append(token_usage)
            self.gui.log(f"LLM call 1 tokens - Input: {token_usage['prompt_tokens']}, Output: {token_usage['completion_tokens']}, Total: {token_usage['total_tokens']}")
            if step_response:
                responses.append(step_response)
                code_match = re.search(r'```\s*[a-zA-Z0-9]*\s*([\s\S]*?)\s*```', step_response, re.IGNORECASE)
                raw_code = code_match.group(1).strip() if code_match else step_response
                pure_code = extract_pure_code(raw_code)
                raw_codes.append(pure_code)
            else:
                self.gui.log(f"LLM call failed")
        except Exception as e:
            self.gui.log(f"Error in LLM call: {e}")
            self.gui.root.after(0, lambda: messagebox.showerror("Error", f"LLM call failed: {e}"))
            self.gui.root.after(0, lambda: self.gui.set_input_state(True))
            return
        if not responses:
            self.gui.log(f"LLM call failed")
            self.gui.root.after(0, lambda: messagebox.showerror("Error", f"LLM call failed"))
            self.gui.root.after(0, lambda: self.gui.set_input_state(True))
            return
        self.gui.log(f"Successfully obtained 1 valid response")
        most_frequent_code = raw_codes[0] if raw_codes else ""
        try:
            LLM_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_model_name = self.model_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
            filename = f"step_{step_num}_{step_name.replace(' ', '_')}_{safe_model_name}_{timestamp}.apdl"
            save_path = LLM_HISTORY_DIR / filename
            total_prompt_tokens = sum(usage['prompt_tokens'] for usage in token_usages)
            total_completion_tokens = sum(usage['completion_tokens'] for usage in token_usages)
            total_tokens = sum(usage['total_tokens'] for usage in token_usages)
            file_content = []
            file_content.append(f"===== Step {step_num}: {step_name} =====")
            file_content.append(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            file_content.append(f"Model: {self.model_name}")
            file_content.append(f"Total LLM calls: 1")
            file_content.append(f"Total tokens used: {total_tokens} (Input: {total_prompt_tokens}, Output: {total_completion_tokens})")
            file_content.append("")
            file_content.append("="*50)
            file_content.append("===== Generated APDL Code =====")
            file_content.append("="*50 + "\n")
            file_content.append(f"Tokens - Input: {token_usages[0]['prompt_tokens']}, Output: {token_usages[0]['completion_tokens']}, Total: {token_usages[0]['total_tokens']}")
            file_content.append(most_frequent_code)
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(file_content))
            self.gui.log(f"Result saved to: {save_path}")
            self.gui.log(f"Total tokens used for step {step_num}: {total_tokens} (Input: {total_prompt_tokens}, Output: {total_completion_tokens})")
        except Exception as e:
            self.gui.log(f"Failed to save result: {str(e)}")
        self.gui.root.after(0, lambda: self.update_ui_after_code_generation(
            step_num, step_name, responses[0], most_frequent_code, 1, 1
        ))
        self.gui.log("Generating code based on LLM response, sending to ANSYS command window...")
        hwnd = run_apdl()
        if hwnd:
            send_apdl_commands(hwnd, most_frequent_code)
    
    def update_ui_after_code_generation(self, step_num, step_name, response, code, response_count, freq_count):
        result_text = f"Step {step_num}: {step_name}\n\nSuccessfully generated 1 response\n{response}"
        self.gui.update_step_display(result_text)
        display_text = f"{code}\n\n--- You can input now ---"
        self.gui.update_code_display(display_text)
        self.gui.root.after(0, lambda: self.gui.set_input_state(True))
        self.set_feedback_buttons_state(True)
        self.in_feedback_phase = True
        self.current_code = code
        current_text = self.gui.step_display.get(1.0, tk.END)
        feedback_prompt = "\n\nPlease provide feedback: Enter 'no problem' to confirm, or 'needs modification' to adjust, or use the buttons above"
        self.gui.update_step_display(current_text + feedback_prompt)
        self.gui.user_input.focus_set()
    
    def process_feedback(self, user_feedback):
        step_num = self.current_step["num"]
        step_name = self.current_step["name"]
        user_feedback = user_feedback.lower().strip()
        confirm_phrases = ["no problem", "no issues", "no need to modify", "okay", "can do", 
                        "like this", "alright", "confirm", "ok", "yes"]
        modify_phrases = ["modify", "needs modification", "need to modify", "requires modification", 
                        "want to change", "need adjustment", "needs adjustment"]
        if any(phrase in user_feedback for phrase in confirm_phrases):
            self.gui.log("Confirming code is correct, saving current step code...")
            self.gui.step_codes[step_num] = {"name": step_name, "code": self.current_code}
            update_code_file(self.gui.step_codes, self.save_path)
            self.gui.update_steps_list(self.all_steps)
            self.current_step_index += 1
            self.process_next_step()
        elif any(phrase in user_feedback for phrase in modify_phrases):
            feedback_window = tk.Toplevel(self.gui.root)
            feedback_window.title("Enter Modification Suggestions")
            feedback_window.geometry("500x200")
            feedback_window.transient(self.gui.root)
            feedback_window.grab_set()
            ttk.Label(feedback_window, text="Please specify what needs modification:", font=("Arial", 12)).pack(padx=10, pady=10, anchor=tk.W)
            feedback_text = scrolledtext.ScrolledText(feedback_window, font=("Segoe UI", 12), height=5)
            feedback_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            def confirm_feedback():
                feedback_detail = feedback_text.get(1.0, tk.END).strip()
                if not feedback_detail:
                    messagebox.showwarning("Prompt", "Modification suggestions cannot be empty")
                    return
                feedback_window.destroy()
                self.process_modification(feedback_detail)
            ttk.Button(feedback_window, text="Confirm", command=confirm_feedback).pack(pady=10)
            feedback_window.wait_window()
        else:
            messagebox.showwarning("Prompt", "Please provide valid feedback (e.g.: no problem/needs modification)")
    
    def process_modification(self, feedback_detail):
        step_num = self.current_step["num"]
        code_template = self.current_step["code_template"]
        original_user_input = self.user_inputs.get(step_num, "")
        self.gui.log(f"User wants to modify: {feedback_detail}")
        self.gui.update_step_display(f"Step {step_num}: Generating modified APDL code based on modification suggestions...")
        self.gui.root.after(0, lambda: self.gui.set_input_state(False))
        self.gui.root.after(0, lambda: self.gui.update_code_display("Generating modified code, please wait..."))
        threading.Thread(target=self.generate_modified_code_in_background, 
                        args=(feedback_detail, step_num, code_template, original_user_input, self.current_code), 
                        daemon=True).start()

    def generate_modified_code_in_background(self, feedback_detail, step_num, code_template, original_user_input, current_code):
        L_guidance = ""
        if step_num in [12, 13, 14]:
            L_guidance = self.get_L_location_guidance()
        user_msg = f"""
    CRITICAL INSTRUCTION: You must output the complete modified APDL code. Focus on generating functional APDL commands.

    CONTEXT:
    - Step Number: {step_num}
    - Step Name: {self.current_step['name']}
    - User's Original Input: {original_user_input}
    - User's Modification Feedback: {feedback_detail}

    CURRENT APDL CODE (to be modified):
    ```apdl
    {current_code}
    STEP CODE TEMPLATE (for reference):

    apdl
    {code_template}
    MODIFICATION REQUIREMENTS:
    Make ONLY the specific changes requested in the feedback: "{feedback_detail}"
    Keep the same overall structure, command order, and style as the current APDL code
    Ensure the modified code is syntactically correct and complete for this step
    Do NOT change parts of the code that are not related to the feedback
    Maintain consistency with the original user input: "{original_user_input}"

    {L_guidance}

    OUTPUT FORMAT:
    Start with the modified APDL code
    Use proper APDL command syntax
    Include necessary comments for clarity
    """
        self.gui.log(f"Performing 1 modified LLM call...")
        responses = []
        raw_codes = []
        token_usages = []
        try:
            temp_conversation = [msg.copy() for msg in self.conversation_history]
            temp_conversation.append({"role": "user", "content": user_msg})
            step_response = self.llm_client.generate_response(temp_conversation, temperature=0.2, max_tokens=3400)
            token_usage = self.llm_client.get_last_token_usage()
            token_usages.append(token_usage)
            self.gui.log(f"Modified LLM call tokens - Input: {token_usage['prompt_tokens']}, Output: {token_usage['completion_tokens']}, Total: {token_usage['total_tokens']}")
            if step_response:
                responses.append(step_response)
                code_match = re.search(r'```\s*[a-zA-Z0-9]*\s*([\s\S]*?)\s*```', step_response, re.IGNORECASE)
                raw_code = code_match.group(1).strip() if code_match else step_response
                pure_code = extract_pure_code(raw_code)
                raw_codes.append(pure_code)
            else:
                self.gui.log(f"Modified LLM call failed")
        except Exception as e:
            self.gui.log(f"Error in modified LLM call: {e}")
            self.gui.root.after(0, lambda: messagebox.showerror("Error", f"Modified LLM call failed: {e}"))
            self.gui.root.after(0, lambda: self.gui.set_input_state(True))
            return
        if not responses:
            self.gui.log(f"Modified LLM call failed")
            self.gui.root.after(0, lambda: messagebox.showerror("Error", f"Modified LLM call failed"))
            self.gui.root.after(0, lambda: self.gui.set_input_state(True))
            return
        most_frequent_code = raw_codes[0] if raw_codes else ""
        try:
            LLM_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_model_name = self.model_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
            filename = f"step_{step_num}_{self.current_step['name'].replace(' ', '_')}_modified_{safe_model_name}_{timestamp}.apdl"
            save_path = LLM_HISTORY_DIR / filename
            total_prompt_tokens = sum(usage['prompt_tokens'] for usage in token_usages)
            total_completion_tokens = sum(usage['completion_tokens'] for usage in token_usages)
            total_tokens = sum(usage['total_tokens'] for usage in token_usages)
            file_content = []
            file_content.append(f"===== Step {step_num}: {self.current_step['name']} (Modified) =====")
            file_content.append(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            file_content.append(f"Model: {self.model_name}")
            file_content.append(f"Original user input: {original_user_input}")
            file_content.append(f"Modification feedback: {feedback_detail}")
            file_content.append(f"Total modified LLM calls: 1")
            file_content.append(f"Total tokens used: {total_tokens} (Input: {total_prompt_tokens}, Output: {total_completion_tokens})")
            file_content.append("")
            file_content.append("="*50)
            file_content.append("===== Modified APDL Code =====")
            file_content.append("="*50 + "\n")
            file_content.append(f"Tokens - Input: {token_usages[0]['prompt_tokens']}, Output: {token_usages[0]['completion_tokens']}, Total: {token_usages[0]['total_tokens']}")
            file_content.append(most_frequent_code)
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(file_content))
            self.gui.log(f"Modified result saved to: {save_path}")
        except Exception as e:
            self.gui.log(f"Failed to save modified result: {str(e)}")
        history_code = ""
        for step_id in self.gui.step_codes:
            if step_id < step_num:
                history_code += self.gui.step_codes[step_id]["code"] + "\n"
        full_code = f"{history_code}{most_frequent_code}"
        self.gui.log("Generated modified code, sending history code + new code to ANSYS command window...")
        hwnd = run_apdl()
        if hwnd:
            send_apdl_commands(hwnd, full_code)
        self.current_code = most_frequent_code
        self.gui.step_codes[step_num] = {"name": self.current_step["name"], "code": most_frequent_code}
        update_code_file(self.gui.step_codes, self.save_path)
        self.gui.root.after(0, lambda: self.update_ui_after_modification(
            step_num, responses[0], most_frequent_code, 1, 1
        ))
    
    def update_ui_after_modification(self, step_num, response, code, response_count, freq_count):
        result_text = f"Step {step_num}:\n\nSuccessfully generated 1 modified response\n\n{response}"
        self.gui.update_step_display(result_text)
        self.gui.update_code_display(code)
        self.gui.root.after(0, lambda: self.gui.set_input_state(True))
        self.set_feedback_buttons_state(True)
        current_text = self.gui.step_display.get(1.0, tk.END)
        feedback_prompt = "\n\nPlease provide feedback: Enter 'no problem' to confirm, or 'needs modification' to adjust, or use the buttons above"
        self.gui.update_step_display(current_text + feedback_prompt)
        self.gui.user_input.focus_set()
    
    def finish_processing(self):
        self.gui.log("\n===== All steps processed! =====")
        self.gui.log(f"Complete code saved to: {self.save_path}")
        self.gui.update_step_display("All interactive steps completed! The generated APDL code can be copied for use.")
        self.gui.user_input.config(state=tk.DISABLED)
        self.gui.submit_btn.config(state=tk.DISABLED)
        apdl_hwnd = find_apdl_window()
        self.export_k_file(apdl_hwnd)
        self.gui.log("Please manually check results in APDL window")
        messagebox.showinfo("Completed", "All steps processed!")
    
    def export_k_file(self, hwnd):
        export_window = tk.Toplevel(self.gui.root)
        export_window.title("Export K File")
        export_window.geometry("500x300")
        export_window.transient(self.gui.root)
        export_window.grab_set()
        ttk.Label(export_window, text="K File Export Settings", font=("Arial", 14, "bold")).pack(padx=10, pady=10)
        ttk.Label(export_window, text="Save path:", font=("Arial", 12)).pack(anchor=tk.W, padx=10)
        path_var = tk.StringVar(value=APDL_WORKING_DIR)
        path_entry = ttk.Entry(export_window, textvariable=path_var, font=("Arial", 12))
        path_entry.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(export_window, text="File name (no extension needed):", font=("Arial", 12)).pack(anchor=tk.W, padx=10)
        name_var = tk.StringVar(value="barrier_model")
        name_entry = ttk.Entry(export_window, textvariable=name_var, font=("Arial", 12))
        name_entry.pack(fill=tk.X, padx=10, pady=5)
        def do_export():
            save_dir = path_var.get()
            filename = name_var.get()
            try:
                os.makedirs(save_dir, exist_ok=True)
                filename = os.path.splitext(filename)[0]
                formatted_dir = save_dir.replace("\\", "/")
                export_commands = f"""FINISH
/CWD, '{formatted_dir}'
/SOLU
EDWRITE, LSDYNA, '{filename}', 'k'
FINISH
"""
                self.gui.log(f"Generated APDL export commands:\n{export_commands}")
                self.gui.log(f"Exporting .k file to: {os.path.join(save_dir, f'{filename}.k')}")
                if hwnd:
                    result = send_apdl_commands(hwnd, export_commands)
                    if result:
                        expected_path = os.path.join(save_dir, f"{filename}.k")
                        if os.path.exists(expected_path):
                            self.gui.log(f".k file exported successfully! Saved to: {expected_path}")
                            messagebox.showinfo("Success", f".k file exported successfully!\n{expected_path}")
                        else:
                            self.gui.log(f".k file export command sent, but file not found")
                            messagebox.showwarning("Warning", ".k file export command sent, but file not found")
                    else:
                        self.gui.log("Failed to export .k file")
                        messagebox.showerror("Error", "Failed to export .k file")
                else:
                    self.gui.log("ANSYS window not found, cannot export .k file")
                    messagebox.showerror("Error", "ANSYS window not found, cannot export .k file")
            except Exception as e:
                self.gui.log(f"Export failed: {e}")
                messagebox.showerror("Error", f"Export failed: {e}")
            export_window.destroy()
        btn_frame = ttk.Frame(export_window)
        btn_frame.pack(fill=tk.X, padx=10, pady=20)
        ttk.Button(btn_frame, text="Cancel Export", command=export_window.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Confirm Export", command=do_export).pack(side=tk.RIGHT, padx=5)
        export_window.wait_window()


# ------------------------------
# Other Helper Functions
# ------------------------------
def set_clipboard_text(text):
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()
        return True
    except Exception as e:
        print(f"Failed to set clipboard: {e}")
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            win32clipboard.CloseClipboard()
        return False

def find_dialog_window(processed_hwnds):
    for title in DIALOG_TITLES:
        hwnd = None
        def callback(window_hwnd, extra):
            nonlocal hwnd
            if win32gui.GetWindowText(window_hwnd) == title:
                hwnd = window_hwnd
        win32gui.EnumWindows(callback, None)
        if hwnd and is_window_valid(hwnd) and hwnd not in processed_hwnds:
            return hwnd, title
    return None, None

def is_window_valid(hwnd):
    if not hwnd:
        return False
    if not win32gui.IsWindow(hwnd):
        return False
    if not win32gui.IsWindowVisible(hwnd):
        return False
    return True

def wait_for_first_dialog():
    start_time = time.time()
    while time.time() - start_time < FIRST_DIALOG_TIMEOUT:
        dialog_hwnd, dialog_title = find_dialog_window([])
        if dialog_hwnd:
            print(f"Successfully identified first [{dialog_title}] dialog box (Handle: {dialog_hwnd})")
            return True, dialog_hwnd, dialog_title
        win32gui.EnumWindows(lambda h, e: None, None)
        time.sleep(0.5)
    return False, None, None

def wait_for_next_dialog(processed_hwnds):
    start_time = time.time()
    while time.time() - start_time < BASE_WAIT_TIME:
        dialog_hwnd, dialog_title = find_dialog_window(processed_hwnds)
        if dialog_hwnd:
            return True, dialog_hwnd, dialog_title
        time.sleep(0.3)
    return False, None, None

def wait_for_window_close(hwnd, timeout=3):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return True
        time.sleep(0.2)
    return False

def send_enter_key():
    win32api.keybd_event(13, 0, 0, 0)
    time.sleep(0.2)
    win32api.keybd_event(13, 0, win32con.KEYEVENTF_KEYUP, 0)
    print("Sent Enter key")
    time.sleep(0.5)

def find_apdl_window():
    hwnd = None
    def callback(window_hwnd, extra):
        nonlocal hwnd
        if win32gui.GetWindowText(window_hwnd) == ANSYS_WINDOW_TITLE:
            hwnd = window_hwnd
    win32gui.EnumWindows(callback, None)
    return hwnd

def get_current_input_language():
    hwnd = win32gui.GetForegroundWindow()
    thread_id = win32process.GetWindowThreadProcessId(hwnd)[0]
    klid = win32api.GetKeyboardLayout(thread_id)
    return klid & 0xFFFF

def switch_to_english_input():
    current_lang = get_current_input_language()
    if current_lang == 0x0804:
        ctypes.windll.user32.keybd_event(17, 0, 0, 0)
        ctypes.windll.user32.keybd_event(32, 0, 0, 0)
        time.sleep(0.1)
        ctypes.windll.user32.keybd_event(32, 0, win32con.KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(17, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)

def load_toml_file(path):
    try:
        if not path.exists():
            print(f"Error: File does not exist - {path}")
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return toml.load(f)
    except Exception as e:
        print(f"Failed to load {path}: {str(e)}")
        return None

def extract_case_steps(case_data):
    steps = []
    for key in case_data:
        if key.startswith("STEP_"):
            try:
                step_num = int(key.split("_")[1])
                if step_num == 18:
                    step_num = 17
                step_info = case_data[key]
                if step_num in {3,4,5}:
                    is_fixed = False
                    is_interactive = True
                elif step_num in COMMON_FIXED_STEPS:
                    is_fixed = True
                    is_interactive = False
                elif step_num in COMMON_INTERACTIVE_STEPS:
                    is_fixed = False
                    is_interactive = True
                else:
                    is_fixed = False
                    is_interactive = True
                steps.append({
                    "num": step_num,
                    "name": step_info["name"],
                    "code_template": step_info["code"],
                    "is_fixed": is_fixed,
                    "is_interactive": is_interactive
                })
            except Exception as e:
                print(f"Failed to parse step {key}: {str(e)}")
    return sorted(steps, key=lambda x: x["num"])

def get_interactive_step_templates():
    return {
        3: """
        Create Barrier cross-section (red surface):
        (Refer to the coordinate system, origin, and point input order in the right figure)
        1. Input point coordinates
            """,
        4: """
        Create Deck cross-section (blue surface):
        1. Input point coordinates
            """,
        5: """
        Provide 2 dimensional information:
        1. Barrier base width (WB)
        2. Total Barrier length (L)
            """,
        11: """
        Create Longitudinal rebars(create 1 first, then copy):
        (1) Provide the endpoints of the initial rebar:
        【Format】
        Start point: (X,Y,0),
        End point: (X,Y,-L)    (L is the total Barrier length)
        (2) Copying method 
        (explain step by step, format as "Step + which rebar to select + copying direction + number of copies + spacing"):
        【Example】
        Step 1: Select the initial rebar, copy upward 3 times with spacing 150 mm;
        Step 2: Select the latest generated rebar, copy rightward 1 time with spacing 50 mm;
        Step 3: Select the latest generated rebar, copy downward 3 times with spacing 150 mm;
        And so on
        【Note】
        a. "latest generated rebar" refers to the last rebar generated after the previous copying step;
        """,
        12: """
        Create Barrier stirrups of the Barrier:
        1. Provide the outline turning points:
        【Format】:
        Stirrup 1: (X₁, Y₁,0), (X₂, Y₂,0) ... (Xn, Yn,0)
        Stirrup 2: (X₁, Y₁,0), (X₂, Y₂,0) ... (Xn, Yn,0)
        and so on
        2. Specify stirrup outline type:
        All straight segments or Contains arc segments
        3. Copying method:
        Along the length of the barrier, Arrange one (rebar) at intervals of ____ mm
        """,
        13: """
        Create upper Longitudinal rebars of the Deck:
        Provide two types of reinforcement information (choose either format):
        Format A: Transverse Reinforcement Only
        Transverse reinforcement: (X1,Y1,0), (X2,Y2,0)
        Spaced at ____mm along the length

        Format B: Transverse Reinforcement + Dense Reinforcement
        Transverse reinforcement: (X1,Y1,0), (X2,Y2,0)
        Dense reinforcement: (X3,Y3,Z3), (X4,Y4,Z4)
        Spaced at ____mm along the length
        """,
        14: """
        Create lower Longitudinal rebars of the Deck:
        1. Provide the endpoints of the initial rebar:
        【Format】:
        Point 1: (X₁, Y₁,0)
        Point 2: (X₂, Y₂,0)
        2. Copying method: 
        Along the length of the barrier, Arrange one (rebar) at intervals of ____ mm
        """,
        15: """
        Create upper Transverse rebars of the Deck:
        Provide reinforcement information and copying method:
        1. Reinforcement endpoints:
        (X,Y,0), (X,Y,-L)

        2. Copying method (choose either):
        - Single-stage: Copy to the right ____ times at a spacing of ____mm
        - Multi-stage: Copy to the right ____ times at a spacing of ____mm; select the newly generated line and copy to the right ____ times at a spacing of ____mm
        """,
        16: """
        Create lower Transverse rebars of the Deck:
        1. Provide the endpoints of the initial rebar:
        【Format】
        Start point: (X₁, Y₁,0); 
        End point: (X₂, Y₂,-L) 
        2. Copying method: 
        Copy rightward ____ times with a spacing of ____ mm
        """
    }

def extract_pure_code(raw_code):
    pattern = r'```\s*[a-zA-Z0-9]*\s*([\s\S]*?)\s*```'
    match = re.search(pattern, raw_code, re.IGNORECASE)
    if match:
        code_content = match.group(1).strip()
    else:
        code_content = "\n".join([line for line in raw_code.splitlines() if line.strip()])
    lines = code_content.split('\n')
    filtered_lines = [line.strip() for line in lines if not line.strip().startswith('!')]
    filtered_lines = [line for line in filtered_lines if line]
    return "\n".join(filtered_lines) + "\n"

def update_code_file(step_codes, save_path):
    try:
        with open(save_path, 'w', encoding='utf-8') as f:
            for step_num in sorted(step_codes.keys()):
                step_info = step_codes[step_num]
                f.write(f"! Step {step_num}: {step_info['name']}\n")
                f.write(step_info['code'])
                f.write("\n")
        print(f"Code updated to file: {save_path}")
    except Exception as e:
        print(f"Saving failed: {str(e)}")
        messagebox.showerror("Error", f"Cannot save code to file: {str(e)}")

def read_history_code(save_path):
    try:
        if not save_path.exists():
            print(f"History code file does not exist: {save_path}")
            return ""
        with open(save_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Failed to read history code: {str(e)}")
        return ""

def run_apdl():
    global apdl_proc, apdl_hwnd
    print("Checking for existing ANSYS window...")
    apdl_hwnd = find_apdl_window()
    if apdl_hwnd and win32gui.IsWindow(apdl_hwnd) and win32gui.IsWindowVisible(apdl_hwnd):
        print(f"Found existing {ANSYS_WINDOW_TITLE} window, no need to restart")
        try:
            _, process_id = win32process.GetWindowThreadProcessId(apdl_hwnd)
            apdl_proc = subprocess.Popen(
                f"tasklist /FI \"PID eq {process_id}\"", 
                shell=True, 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            output_bytes = apdl_proc.communicate()[0]
            encodings = ['gbk', 'utf-8', 'latin-1']
            output = None
            for encoding in encodings:
                try:
                    output = output_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if output is None:
                print("Cannot decode process information, but window exists, continuing to use")
                return apdl_hwnd
            if f"{process_id}" in output:
                print(f"ANSYS process (PID: {process_id}) is running")
                return apdl_hwnd
        except Exception as e:
            print(f"Error checking ANSYS process: {e}")
            print("Continuing to use detected window")
        return apdl_hwnd
    if not os.path.exists(ANSYS_PATH):
        print(f"Error: APDL executable not found, please check path: \n{ANSYS_PATH}")
        return None
    try:
        os.makedirs(APDL_WORKING_DIR, exist_ok=True)
        print(f"Using working directory: {APDL_WORKING_DIR}")
    except Exception as e:
        print(f"Failed to create working directory: {e}")
        return None
    args = [
        ANSYS_PATH, "-g", "-p", "dyna", "-dir", APDL_WORKING_DIR,
        "-j", "file", "-dyn", "-s", "read", "-l", "en-us", "-t", "-d", "win32"
    ]
    try:
        print("Starting APDL...")
        apdl_proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=APDL_WORKING_DIR)
        print("Waiting for APDL GUI to start...")
        start_time = time.time()
        timeout = 30
        while time.time() - start_time < timeout:
            apdl_hwnd = find_apdl_window()
            if apdl_hwnd and win32gui.IsWindowVisible(apdl_hwnd):
                print("APDL GUI started successfully")
                return apdl_hwnd
            time.sleep(2)
        print(f"Warning: Timeout waiting for APDL to start ({timeout} seconds)")
        if apdl_proc.poll() is not None:
            print(f"APDL process exited, return code: {apdl_proc.returncode}")
            try:
                error_output = apdl_proc.stderr.read().decode('gbk')
            except UnicodeDecodeError:
                error_output = apdl_proc.stderr.read().decode('utf-8', errors='replace')
            print("Error output:")
            print(error_output)
            return None
        apdl_hwnd = find_apdl_window()
        if apdl_hwnd:
            print("Detected possible APDL window, attempting to use it")
            return apdl_hwnd
        print("No APDL window found, startup failed")
        return None
    except Exception as e:
        print(f"Error starting APDL: {str(e)}")
        return None


# ------------------------------
# Program Entry
# ------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    root.attributes("-alpha", 0.99)
    root.option_add("*Font", "Arial 10")
    gui = APDLModelingGUI(root)
    app = APDLModelingApp(gui)
    root.after(100, app.start)
    root.mainloop()
