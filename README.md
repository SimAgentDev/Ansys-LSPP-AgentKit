# Ansys-LSPP-AgentKit

> A multi-agent toolkit for FEM simulation, enabling automatic ANSYS geometric modeling and LS-PrePost pre/post processing.

## Paper Information
> **Paper**: [Human-Enhanced Loop Modeling (HELM): Agent-Based Finite Element Modeling of Concrete Bridge Barriers](https://arxiv.org/abs/2606.12025)  
> **Authors**: Quankai Wang, Yulin Xie, Tongfei Yang, Minghui Cheng, Ran Cao.
> **arXiv ID**: [2606.12025](https://arxiv.org/abs/2606.12025)

## Project Introduction
This project consists of two independent agents responsible for different stages of FEM simulation:

- **Agent1 – ANSYS Barrier Modeling System**
  It generates APDL code via natural language interaction and executes the code automatically in ANSYS. This agent completes geometric modeling for the concrete part of barrier structures (Checkpoints 1–3, in accordance with Table A1 in the paper) and reinforcement layout (Checkpoints 4–9).

- **Agent2 – LS-PrePost Assistant**
  This graphical LS-PrePost tool supports K-file configuration for boundary conditions (Checkpoints 10–15, in accordance with Table A1 in the paper), load application (Checkpoints 16–18), as well as definition and assignment of material and section properties (Checkpoints 19–22).

Each agent has its own directory, dependencies and execution procedure, and can be used independently on demand.


### Table A1. Checkpoint Specifications for Parapet Modeling
This table details all functional checkpoints of the multi-agent system, corresponding to the workflow in the reference paper.

<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Checkpoint</th>
      <th>Operation</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td rowspan="9">Agent_Geo<br>(ANSYS)</td>
      <td>1</td>
      <td>Parapet Cross-Section Definition</td>
      <td>Delineate the parapet cross-sectional geometry by interconnecting vertices at user-specified coordinates</td>
    </tr>
    <tr>
      <td>2</td>
      <td>Deck Cross-Section Definition</td>
      <td>Delineate the deck cross-sectional geometry by interconnecting vertices at user-specified coordinates</td>
    </tr>
    <tr>
      <td>3</td>
      <td>Longitudinal Geometric Extrusion & Meshing</td>
      <td>Execute 3D solid generation through profile extrusion, followed by mesh discretization based on prescribed element sizes</td>
    </tr>
    <tr>
      <td>4</td>
      <td>Parapet Longitudinal Rebar Modeling</td>
      <td>Model the longitudinal rebars and distribute them at specified intervals along the barrier</td>
    </tr>
    <tr>
      <td>5</td>
      <td>Parapet Stirrup Modeling</td>
      <td>Define the stirrup profiles and arrange them at a set spacing along the longitudinal axis</td>
    </tr>
    <tr>
      <td>6</td>
      <td>Deck Top Transverse Rebar Modeling</td>
      <td>Define the top transverse rebar and implement longitudinal distribution along the bridge axis based on specified spacing, including adaptive densification in critical reinforcement zones</td>
    </tr>
    <tr>
      <td>7</td>
      <td>Deck Bottom Transverse Rebar Modeling</td>
      <td>Define the bottom transverse rebar and implement longitudinal distribution along the bridge axis based on specified spacing</td>
    </tr>
    <tr>
      <td>8</td>
      <td>Deck Top Longitudinal Rebar Modeling</td>
      <td>Define the top longitudinal rebar and implement lateral distribution across the deck width based on specified spacing</td>
    </tr>
    <tr>
      <td>9</td>
      <td>Deck Bottom Longitudinal Rebar Modeling</td>
      <td>Define the bottom longitudinal rebar and implement lateral distribution across the deck width based on specified spacing</td>
    </tr>
    <tr>
      <td rowspan="9">Agent_BC<br>(LS-PrePost)</td>
      <td>10</td>
      <td>Standardized Orientation Alignment</td>
      <td>Align the model’s orientation with the prescribed global coordinate system to establish a spatial reference for subsequent automated node identification</td>
    </tr>
    <tr>
      <td>11</td>
      <td>Origin Normalization</td>
      <td>Translate the model to the global origin (0,0,0) to enable node selection based on spatial coordinates</td>
    </tr>
    <tr>
      <td>12</td>
      <td>Boundary Support Node Ⅰ Selection</td>
      <td>Select nodes of the initial support interface (Support I) based on spatial coordinate to define the Constraint_NodeSet</td>
    </tr>
    <tr>
      <td>13</td>
      <td>Boundary Support Node Ⅱ Selection</td>
      <td>Select nodes of the subsequent support interface (Support II) based on spatial coordinate and append them to the Constraint_NodeSet</td>
    </tr>
    <tr>
      <td>14</td>
      <td>Boundary Support Node Ⅲ Selection</td>
      <td>Select nodes of the longitudinal symmetry plane (Support III) based on spatial coordinate and append these nodes to the Constraint_NodeSet</td>
    </tr>
    <tr>
      <td>15</td>
      <td>Boundary Condition Application</td>
      <td>Impose a fixed boundary condition to the Constraint_NodeSet to restrict all 6 DOFs (X, Y, Z, Rx, Ry, Rz)</td>
    </tr>
    <tr>
      <td>16</td>
      <td>Loading Node Selection</td>
      <td>Select nodes along the parapet's top edge (per AASHTO-LRFD 2024) based on spatial coordinates and define them as the Loading_NodeSet</td>
    </tr>
    <tr>
      <td>17</td>
      <td>Load Curve Definition</td>
      <td>Define the impulse Loading_Curve via discrete (time, force) data points (per AASHTO-LRFD 2024)</td>
    </tr>
    <tr>
      <td>18</td>
      <td>Dynamic Load Imposition</td>
      <td>Impose the specified transverse force onto the Loading_NodeSet via the defined Loading_Curve</td>
    </tr>
    <tr>
      <td rowspan="4">Agent_Mat<br>(LS-PrePost)</td>
      <td>19</td>
      <td>Concrete Constitutive Modeling</td>
      <td>Define the concrete material properties, including the failure pressure limit and the maximum aggregate size</td>
    </tr>
    <tr>
      <td>20</td>
      <td>Steel Constitutive Modeling</td>
      <td>Define the steel material properties, including mass density, Young's modulus, and Poisson's ratio</td>
    </tr>
    <tr>
      <td>21</td>
      <td>Dimensional Parameter Setup</td>
      <td>Define the physical thickness of the elements to enable the subsequent association between sectional attributes and geometric parts</td>
    </tr>
    <tr>
      <td>22</td>
      <td>Material Property Assignment</td>
      <td>Incorporate material identification (MID) and sectional properties (SECID) into specific Part IDs (PID) to finalize the structural characterization of the parapet system</td>
    </tr>
  </tbody>
</table>

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

## Project Structure
```
Ansys-LSPP-AgentKit/
├── agent1_ansys_geometry/     # ANSYS geometric modeling agent
│   ├── APDL_Copilot/
│   │   ├── step_images/
│   │   ├── config.toml
│   │   └── main.py
│   ├── document/
│   │   └── LLM_ANSYS_Barrier_Case_V6.toml
│   ├── work_path/
│   │   └── ansys_barrier_model.txt
│   ├── README.md
│   └── requirements.txt
├── agent2_lspp_assistant/     # LS-PrePost assistant agent
│   ├── main.py
│   ├── GUI.py
│   ├── utils.py
│   ├── requirements.txt
│   ├── *.cfile (template files)
│   └── README.md
├── LICENSE
└── README.md                  # This file
```

## Notes
- The two agents are **completely independent**, and you do not need to install dependencies for both at the same time.
- Agent1 relies on Tkinter (built-in with Python), while Agent2 requires additional image processing libraries (included in requirements.txt).
- Do not commit API keys or local absolute paths to GitHub. Use `.gitignore` to exclude configuration files.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
