import subprocess, sys, os, json

_LEMON_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = r"""
import sys, os
sys.path.insert(0, r'""" + _LEMON_ROOT.replace("\\", "\\\\") + r"""')
os.chdir(r'""" + _LEMON_ROOT.replace("\\", "\\\\") + r"""')

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from standard_mode.ui.mimo_panel import MIMOCodePanel

panel = MIMOCodePanel()
panel.setWindowTitle("DIAG: Right Panel Check")
panel.resize(420, 700)
panel.show()

DIAG_JS = '''
(function() {
  var r = {};
  r.bodyClasses = document.body ? Array.from(document.body.classList) : [];
  r.innerWidth = window.innerWidth;
  r.innerHeight = window.innerHeight;
  
  var ct = document.getElementById('content');
  if (ct) {
    var cs = getComputedStyle(ct);
    r.content = {
      w: ct.offsetWidth, h: ct.offsetHeight,
      pos: cs.position, z: cs.zIndex,
      bg: cs.background, isol: cs.isolation,
      display: cs.display, flex: cs.flex,
      minH: cs.minHeight, overflow: cs.overflow,
      top: cs.top, left: cs.left
    };
  } else { r.content = 'NOT_FOUND'; }
  
  var sf = document.getElementById('starfield');
  if (sf) {
    r.starfield = {
      w: sf.width, h: sf.height,
      offW: sf.offsetWidth, offH: sf.offsetHeight,
      opacity: sf.style.opacity || getComputedStyle(sf).opacity,
      parent: sf.parentElement ? sf.parentElement.id : 'N/A'
    };
  } else { r.starfield = 'NOT_FOUND'; }
  
  var wl = document.getElementById('wallpaper-layer');
  if (wl) {
    r.wallpaperLayer = {
      w: wl.offsetWidth, h: wl.offsetHeight,
      pos: getComputedStyle(wl).position,
      isol: getComputedStyle(wl).isolation
    };
  } else { r.wallpaperLayer = 'NOT_FOUND'; }
  
  var oa = document.querySelector('.output-area');
  r.outputArea = oa ? {w: oa.offsetWidth, h: oa.offsetHeight} : 'NOT_FOUND';
  
  var ia = document.querySelector('.input-area');
  r.inputArea = ia ? {w: ia.offsetWidth, h: ia.offsetHeight} : 'NOT_FOUND';
  
  var la = document.querySelector('.logo-area');
  r.logoArea = la ? {w: la.offsetWidth, h: la.offsetHeight} : 'NOT_FOUND';
  
  r.starfieldRAF = typeof _starfieldRAF !== 'undefined' ? _starfieldRAF : 'UNDEF';
  r.wallpaperMode = typeof _wallpaperMode !== 'undefined' ? _wallpaperMode : 'UNDEF';
  r.wallpaperTheme = typeof _wallpaperTheme !== 'undefined' ? _wallpaperTheme : 'UNDEF';
  
  console.log('[DIAG_RESULT]', JSON.stringify(r));
  return JSON.stringify(r);
})();
'''

results = {}

def run_diag():
    try:
        panel.web_view.page().runJavaScript(DIAG_JS, 0, lambda v: (
            print("[DIAG_RESULT]", json.dumps(v, indent=2) if v else "null"),
            results.update({'data': v}),
            app.quit()
        ))
    except Exception as e:
        print(f"[DIAG_ERROR] {e}")
        app.quit()

QTimer.singleShot(5000, run_diag)
app.exec_()
if not results:
    print("[DIAG] No result collected within timeout")
"""

tmp = os.path.join(os.environ.get('TEMP', r'C:\Users\Legion\AppData\Local\Temp\deveco'), 'diag_right_panel.py')
with open(tmp, 'w', encoding='utf-8') as f:
    f.write(SCRIPT)
print(f"Script written to {tmp}")
