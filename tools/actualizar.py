"""Actualización diaria: verifica resultados, genera el día siguiente si falta y publica. Uso: python tools/actualizar.py"""
import datetime, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
run = lambda *a: subprocess.run(a, cwd=ROOT).returncode
manana = str(datetime.date.today() + datetime.timedelta(days=1))
print("====", datetime.datetime.now().isoformat(timespec="seconds"), "mañana =", manana, flush=True)
run("git", "pull", "-q", "--ff-only", "origin", "main")
run(sys.executable, "tools/verify.py")
if not (ROOT / "data" / f"{manana}.json").exists():
    run(sys.executable, "tools/futbol.py", manana)
if not (ROOT / "data" / f"nba-{manana}.json").exists():
    run(sys.executable, "tools/nba.py", manana)
run("git", "add", "data")
if run("git", "diff", "--cached", "--quiet"):
    run("git", "commit", "-q", "-m", f"Actualización diaria {manana}")
print("push:", "ok" if run("git", "push", "-q", "origin", "main") == 0 else "FALLÓ", flush=True)
