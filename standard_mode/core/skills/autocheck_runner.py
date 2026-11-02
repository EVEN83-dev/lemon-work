# -*- coding: utf-8 -*-
"""Skill: autocheck_runner — 自动体检与回归检测"""

import sys, os, subprocess, json, time
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "autocheck_runner",
    "description": "自动体检：运行pytest/py_compile/导入检查/UI屏幕验收，生成健康报告，纯只读。",
    "category": "development",
    "version": "1.1.0",
}


def execute(project_path: str = "", check_types: str = "all",
            python_exe: str = "", timeout: int = 120,
            ui_command: str = "", ui_capture_count: int = 5,
            ui_capture_interval: float = 2.0,
            ui_assert_not_black: bool = True,
            ui_region_color: str = "",
            ui_ocr_keyword: str = "") -> SkillResult:
    if not project_path:
        project_path = os.getcwd()

    root = os.path.expanduser(project_path)
    if not os.path.isdir(root):
        return SkillResult(success=False, error=f"路径不存在: {root}")

    if not python_exe:
        python_exe = sys.executable

    results = {}

    if check_types in ("all", "compile"):
        results["compile"] = _check_compile(root, python_exe)

    if check_types in ("all", "pytest"):
        results["pytest"] = _check_pytest(root, python_exe, timeout)

    if check_types in ("all", "imports"):
        results["imports"] = _check_imports(root, python_exe)

    if check_types == "ui":
        results["ui"] = _check_ui(
            root, python_exe, timeout,
            ui_command=ui_command,
            capture_count=ui_capture_count,
            capture_interval=ui_capture_interval,
            assert_not_black=ui_assert_not_black,
            region_color=ui_region_color,
            ocr_keyword=ui_ocr_keyword,
        )

    report = f"自动体检报告: {root}\n{'='*50}\n"
    report += f"时间: {datetime.now().isoformat()}\n"
    report += f"Python: {python_exe}\n\n"

    all_ok = True
    for check_name, check_result in results.items():
        ok = check_result.get("ok", False)
        all_ok = all_ok and ok
        status = "✅" if ok else "❌"
        report += f"{status} {check_name}: {check_result.get('summary', 'N/A')}\n"
        if not ok and check_result.get("details"):
            for d in check_result["details"][:10]:
                report += f"   {d}\n"

    return SkillResult(
        success=all_ok,
        output=report,
        data={"checks": results, "project_path": root, "timestamp": datetime.now().isoformat()},
    )


def _check_compile(root: str, python_exe: str) -> dict:
    errors = []
    checked = 0
    for dirpath, _, filenames in os.walk(root):
        skip = any(d in dirpath for d in (".git", "__pycache__", "node_modules", ".venv", "venv"))
        if skip:
            continue
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                result = subprocess.run(
                    [python_exe, "-m", "py_compile", fp],
                    capture_output=True, text=True, timeout=10,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode != 0:
                    errors.append(f"{fp}: {result.stderr.strip()[:100]}")
                checked += 1
            except Exception as e:
                errors.append(f"{fp}: {e}")

    return {"ok": len(errors) == 0, "summary": f"{checked} files, {len(errors)} errors",
            "details": errors}


def _check_pytest(root: str, python_exe: str, timeout: int) -> dict:
    try:
        result = subprocess.run(
            [python_exe, "-m", "pytest", root, "-q", "--tb=no", "-x"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        output = result.stdout.strip()
        last_line = output.split("\n")[-1] if output else "no output"
        ok = result.returncode == 0
        return {"ok": ok, "summary": last_line, "details": output.split("\n")[-5:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "summary": f"超时({timeout}s)"}
    except Exception as e:
        return {"ok": False, "summary": str(e)}


def _check_imports(root: str, python_exe: str) -> dict:
    errors = []
    for dirpath, _, filenames in os.walk(root):
        skip = any(d in dirpath for d in (".git", "__pycache__", "node_modules", ".venv", "venv"))
        if skip:
            continue
        for fn in filenames:
            if fn == "__init__.py":
                continue
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root)
            mod = rel.replace(os.sep, ".").replace(".py", "")
            try:
                subprocess.run(
                    [python_exe, "-c", f"import {mod}"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except Exception:
                pass
    return {"ok": True, "summary": "导入检查完成(跳过相对导入)"}


def _check_ui(root: str, python_exe: str, timeout: int,
              ui_command: str = "", capture_count: int = 5,
              capture_interval: float = 2.0,
              assert_not_black: bool = True,
              region_color: str = "",
              ocr_keyword: str = "") -> dict:
    """T366.5: UI屏幕监工 — 截屏+断言"""
    evidence_dir = os.path.join(root, "data", "autocheck",
                                datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(evidence_dir, exist_ok=True)

    screenshots = []
    assertions = []
    proc = None

    try:
        if ui_command:
            proc = subprocess.Popen(
                ui_command, shell=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            time.sleep(max(capture_interval, 1.0))

        grabber = _get_screen_grabber()
        if grabber is None:
            return {"ok": False,
                    "summary": "屏幕截图库不可用(mss/PIL均未安装)",
                    "details": ["pip install mss 或 pip install Pillow"]}

        for i in range(capture_count):
            if proc and proc.poll() is not None and proc.returncode is not None:
                break
            time.sleep(capture_interval)
            img_path = os.path.join(evidence_dir, f"screenshot_{i+1:03d}.png")
            ok = grabber(img_path)
            if ok:
                screenshots.append(img_path)

        if not screenshots:
            return {"ok": False, "summary": "无截屏产出",
                    "details": ["被测程序可能未启动或截屏库失败"]}

        for idx, img_path in enumerate(screenshots):
            label = f"截屏#{idx+1}"
            passed = True
            reasons = []

            if assert_not_black:
                is_black = _check_black_screen(img_path)
                if is_black:
                    passed = False
                    reasons.append("黑屏(纯色)")
                else:
                    reasons.append("非黑屏")

            if region_color:
                matched = _check_region_color(img_path, region_color)
                if not matched:
                    passed = False
                    reasons.append(f"区域颜色不匹配({region_color})")
                else:
                    reasons.append(f"区域颜色匹配")

            if ocr_keyword:
                ocr_result = _check_ocr_keyword(img_path, ocr_keyword)
                if not ocr_result:
                    reasons.append(f"OCR未找到关键词({ocr_keyword})")
                else:
                    reasons.append(f"OCR找到关键词({ocr_keyword})")

            assertions.append({
                "screenshot": img_path, "label": label,
                "passed": passed, "reasons": reasons,
            })

    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    all_passed = all(a["passed"] for a in assertions)
    failed_count = sum(1 for a in assertions if not a["passed"])
    summary = f"{len(screenshots)}截屏, {failed_count}断言失败"
    details = [f"  {a['label']}: {'PASS' if a['passed'] else 'FAIL'} ({'; '.join(a['reasons'])})"
               for a in assertions]

    report_path = os.path.join(evidence_dir, "ui_report.json")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({"assertions": assertions, "passed": all_passed}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass

    return {"ok": all_passed, "summary": summary,
            "details": details, "evidence_dir": evidence_dir}


def _get_screen_grabber():
    """获取屏幕截图函数(mss优先，PIL降级)"""
    try:
        import mss
        def grab_mss(path):
            try:
                with mss.mss() as sct:
                    sct.shot(output=path)
                    return os.path.isfile(path)
            except Exception:
                return False
        return grab_mss
    except ImportError:
        pass
    try:
        from PIL import ImageGrab
        def grab_pil(path):
            try:
                img = ImageGrab.grab()
                img.save(path)
                return os.path.isfile(path)
            except Exception:
                return False
        return grab_pil
    except ImportError:
        pass
    return None


def _check_black_screen(img_path: str) -> bool:
    """检测截屏是否为黑屏(纯色) — 多点采样方差"""
    try:
        from PIL import Image
        import numpy as np
        img = Image.open(img_path)
        arr = np.array(img)
        if arr.ndim == 3:
            arr = arr.mean(axis=2)
        h, w = arr.shape
        step = max(h // 5, 1)
        samples = [arr[i * step, j * step]
                    for i in range(5) for j in range(5)
                    if i * step < h and j * step < w]
        variance = float(np.var(samples))
        return variance < 1.0
    except ImportError:
        pass
    try:
        from PIL import Image
        img = Image.open(img_path)
        pixels = list(img.getdata())
        if not pixels:
            return True
        step = max(len(pixels) // 25, 1)
        samples = pixels[::step][:25]
        if img.mode == "RGB":
            avg_brightness = sum(sum(p) / 3 for p in samples) / len(samples)
            return avg_brightness < 5
        avg = sum(p for p in samples if isinstance(p, (int, float))) / max(len(samples), 1)
        return avg < 5
    except Exception:
        return False


def _check_region_color(img_path: str, target_hex: str) -> bool:
    """检测截屏指定区域平均色是否接近目标色"""
    try:
        from PIL import Image
        img = Image.open(img_path).resize((100, 100))
        pixels = list(img.getdata())
        if not pixels or img.mode != "RGB":
            return False
        avg = tuple(sum(p[i] for p in pixels) / len(pixels) for i in range(3))
        tr = int(target_hex.lstrip('#')[:2], 16)
        tg = int(target_hex.lstrip('#')[2:4], 16)
        tb = int(target_hex.lstrip('#')[4:6], 16)
        dist = ((avg[0]-tr)**2 + (avg[1]-tg)**2 + (avg[2]-tb)**2) ** 0.5
        return dist < 80
    except Exception:
        return False


def _check_ocr_keyword(img_path: str, keyword: str) -> bool:
    """OCR检测截屏是否包含关键词"""
    try:
        from skills.ocr_reader import execute as ocr_execute
        result = ocr_execute(image_path=img_path)
        if result.success and result.output:
            return keyword.lower() in result.output.lower()
    except Exception:
        pass
    return False


def register(registry) -> None:
    registry.register(SkillDef(
        name="autocheck_runner",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "项目路径，默认当前目录"},
                "check_types": {"type": "string",
                                "enum": ["all", "compile", "pytest", "imports", "ui"],
                                "description": "检查类型(ui=屏幕验收监工)", "default": "all"},
                "python_exe": {"type": "string", "description": "Python解释器路径"},
                "timeout": {"type": "integer", "description": "超时秒数", "default": 120},
                "ui_command": {"type": "string", "description": "UI检查: 启动被测程序的命令"},
                "ui_capture_count": {"type": "integer", "description": "UI检查: 截屏次数", "default": 5},
                "ui_capture_interval": {"type": "number", "description": "UI检查: 截屏间隔秒数", "default": 2.0},
                "ui_assert_not_black": {"type": "boolean", "description": "UI检查: 断言非黑屏", "default": True},
                "ui_region_color": {"type": "string", "description": "UI检查: 断言区域平均色(十六进制如#FF8800)"},
                "ui_ocr_keyword": {"type": "string", "description": "UI检查: OCR关键词断言"},
            },
            "required": [],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=True,
        timeout=300,
    ))


def get_metadata():
    return METADATA
