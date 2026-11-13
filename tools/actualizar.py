"""Actualización diaria: verifica resultados, genera el día siguiente si falta y publica. Uso: python tools/actualizar.py"""
import datetime, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
run = lambda *a: subprocess.run(a, cwd=ROOT).returncode
manana = str(datetime.date.today() + datetime.timedelta(days=1))
print("====", datetime.datetime.now().isoformat(timespec="seconds"), "mañana =", manana, flush=True)
run("git", "pull", "-q", "--ff-only", "origin", "main")
run(sys.executable, "tools/verify.py")
for dia in (str(datetime.date.today()), manana):  # hoy también, por si ayer no corrió
    if not (ROOT / "data" / f"{dia}.json").exists():
        run(sys.executable, "tools/futbol.py", dia)
    if not (ROOT / "data" / f"nba-{dia}.json").exists():
        run(sys.executable, "tools/nba.py", dia)
run("git", "add", "data")
if run("git", "diff", "--cached", "--quiet"):
    run("git", "commit", "-q", "-m", f"Actualización diaria {manana}")
print("push:", "ok" if run("git", "push", "-q", "origin", "main") == 0 else "FALLÓ", flush=True)
