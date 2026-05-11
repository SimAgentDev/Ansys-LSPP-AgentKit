# Agent1 – ANSYS Barrier Modeling System

LLM-powered APDL code generator & executor for ANSYS barrier modeling.

## Features
- Natural language interaction → APDL code generation
- Fixed steps (auto) & interactive steps (LLM-driven)
- Code review: confirm or request modification
- Auto-send code to ANSYS window + dialog handling
- K-file export
- Fully configurable via `config.toml`

## Requirements
- Windows OS
- Mechanical APDL 18.0 (tested on v18+)
- Python 3.8+

## Installation
```bash
cd Ansys-LSPP-AgentKit/agent1_ansys_geometry
pip install -r requirements.txt
```

## Configuration
Edit `config.toml`:
- Set `ansys_exe_path` (absolute path to MAPDL.exe)
- Adjust other paths (relative paths work, e.g., `"./work_temp"`)
- Add your LLM API tokens (siliconflow / together / openai)

## Usage
```bash
python main.py
```
1. Select LLM model
2. Choose save path for final APDL code
3. Follow GUI: input info when prompted, review generated code, confirm or modify
4. Export K-file at the end

## Troubleshooting
- **Missing config**: program auto-creates template – edit and restart
- **ANSYS not activated**: check `window_title` in config matches your ANSYS window title
- **LLM fails**: verify API token and network

## License
For research/learning only.
