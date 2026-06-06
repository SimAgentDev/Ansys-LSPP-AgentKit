# Ansys-LSPP-AgentKit

> A multi-agent toolkit for FEM simulation, enabling automatic ANSYS geometric modeling and LS-PrePost pre/post processing.

## Project Introduction
This project consists of two independent agents responsible for different stages of FEM simulation:

- **Agent1 – ANSYS Barrier Modeling System**
  Generates APDL code via natural language interaction and automatically executes it in ANSYS to complete geometric modeling of barrier structures.

- **Agent2 – LS-PrePost Assistant**
  A graphical LS-PrePost assistant supporting K-file initialization, boundary condition setup, and material/section definition and assignment.

Each agent has its own directory, dependencies and execution procedure, and can be used independently on demand.

## System Requirements
- Operating System: Windows
- Python 3.10 or above
- Corresponding software installation as required:
  - Agent1 requires ANSYS Mechanical APDL 18.0 or later
  - Agent2 requires LS-PrePost 4.6 or later
- LLM API keys (SiliconFlow / Together AI / OpenAI)

## Quick Start
### Clone the Repository
```bash
git clone https://github.com/SimAgentDev/Ansys-LSPP-AgentKit.git
cd Ansys-LSPP-AgentKit
```

### Use Agent1 (ANSYS Modeling)
```bash
cd agent1_ansys_geometry
pip install -r requirements.txt
# Edit config.toml to fill in ANSYS path and API keys
python main.py
```
For detailed instructions, see [agent1_ansys_geometry/README.md](agent1_ansys_geometry/README.md)

### Use Agent2 (LS-PrePost Pre/Post Processing)
```bash
cd agent2_lspp_assistant
pip install -r requirements.txt
# Edit utils.py to fill in LS-PrePost path and API keys
python main.py
```
For detailed instructions, see [agent2_lspp_assistant/README.md](agent2_lspp_assistant/README.md)

## Notes
- The two agents are **completely independent**, and you do not need to install dependencies for both at the same time.
- Agent1 relies on Tkinter (built-in with Python), while Agent2 requires additional image processing libraries (included in requirements.txt).
- Do not commit API keys or local absolute paths to GitHub. Use `.gitignore` to exclude configuration files.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
