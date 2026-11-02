from __future__ import annotations
import sys

try:
    from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
    HAS_PYQT = True
except ImportError:
    try:
        from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
        HAS_PYQT = True
    except ImportError:
        HAS_PYQT = False

if not HAS_PYQT:
    print("PyQt not available, demo skipped")
    sys.exit(0)

from workflow_tree_widget import WorkflowTreeWidget

class FakeRun:
    def __init__(self, run_id, title, status="completed", duration_ms=1500):
        self.run_id = run_id
        self.title = title
        self.status = status
        self.duration_ms = duration_ms

class FakeStep:
    def __init__(self, step_id, title, status="completed", duration_ms=500):
        self.step_id = step_id
        self.title = title
        self.status = status
        self.duration_ms = duration_ms

class FakeToolCall:
    def __init__(self, toolcall_id, tool_name, status="success", duration_ms=100):
        self.toolcall_id = toolcall_id
        self.tool_name = tool_name
        self.status = status
        self.duration_ms = duration_ms

def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("WorkflowTree Demo")
    window.resize(600, 400)
    central = QWidget()
    layout = QVBoxLayout(central)
    tree = WorkflowTreeWidget()
    layout.addWidget(tree)
    window.setCentralWidget(central)

    for i in range(2):
        run = FakeRun(f"run_{i}", f"Run {i+1}")
        tree.add_run(run)
        for j in range(3):
            step = FakeStep(f"step_{i}_{j}", f"Step {j+1}")
            tree.add_step(run.run_id, step)
            for k in range(2):
                tc = FakeToolCall(f"tc_{i}_{j}_{k}", f"tool_{k}", duration_ms=50+k*20)
                tree.add_toolcall(step.step_id, tc)

    tree.toolcall_double_clicked.connect(lambda tc_id: print(f"Double-clicked: {tc_id}"))
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
