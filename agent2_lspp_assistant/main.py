# main.py
# 程序的入口点，负责启动图形用户界面。

import tkinter as tk
from GUI import APDLModelingGUI # 从 GUI.py 文件导入 APDLModelingGUI 类

if __name__ == "__main__":
    # 创建 Tkinter 的根窗口
    root = tk.Tk()
    
    # 实例化你的 GUI 应用
    app = APDLModelingGUI(root)
    
    # 启动 Tkinter 事件循环，这将显示 GUI 窗口
    root.mainloop()
