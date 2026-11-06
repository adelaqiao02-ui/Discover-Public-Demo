import sys, subprocess, importlib.util
from pathlib import Path
if sys.version_info < (3,10): raise SystemExit("Python 3.10+ required")
root=Path(__file__).resolve().parent
if any(importlib.util.find_spec(n) is None for n in ('streamlit','pandas','numpy','plotly')):
    subprocess.check_call([sys.executable,'-m','pip','install','-r',str(root/'requirements.txt')])
subprocess.run([sys.executable,'-m','streamlit','run',str(root/'app.py'),'--server.address=127.0.0.1','--server.headless=false'],check=True,cwd=root)
