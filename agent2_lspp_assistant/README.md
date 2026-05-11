Alright, understood. Below is the complete English translation, kept in standard technical document style, fully retaining original markdown format, code blocks, file names and paths without extra explanation.

```markdown
# Agent2: LS-PrePost Assistant (Boundary & Material)

> A graphical intelligent assistant for LS-PrePost, supporting K-file initialization, boundary condition setup, and material/section definition and assignment.

## Environment Requirements
- Windows (LS-PrePost 4.6 or above required)
- Python 3.10 or higher
- LLM API keys (SiliconFlow / Together AI / OpenAI)

## Installation
```bash
git clone https://github.com/your-username/Ansys-LSPP-AgentKit.git
cd Ansys-LSPP-AgentKit/agent2_lspp_assistant
pip install -r requirements.txt
```

## Configuration
### 1. LS-PrePost Path
Edit `utils.py` and modify the following path:
```python
LSPREPOST_EXE_PATH = r"D:\Your_Path\lsprepost4.6_x64.exe"
```

### 2. LLM API Keys
Replace the corresponding `api_token` of each model inside `LLM_CONFIGS` in `utils.py`.

### 3. Template Files
Ensure the following files are placed in the same directory as `GUI.py` (default templates provided):
- `transit_modified_1.cfile` (translation)
- `rotate_modified_1.cfile` (rotation)
- `select_part.cfile` (visualization)
- `assignment_modified_1.cfile` (material assignment)

## Execution
```bash
python main.py
```

## Notes
- Upon first use, select and initialize an LLM model in the interface, then load the K-file (automatic backup and node extraction will be performed).
- Node retrieval relies on automatically generated `solid_nodes.txt` and `surface_nodes.txt`.
- Certain operations will launch LS-PrePost and keep the window open. Please close it manually to proceed with subsequent operations.
```