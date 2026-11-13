"""Aprende de los pronósticos ya verificados: cuánto se pasó o se quedó corto cada tipo de mercado.

Uso: python tools/calibra.py   (imprime la tabla). futbol.py y nba.py lo importan.
Corrección: si un mercado se anunció con 68 % de media y acertó el 52 %, se le resta esa diferencia,
pesada por la muestra (n / (n + 30)), para que pocos partidos no muevan demasiado el número.
"""
import json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FUT = [("over2.5", r"más de 2\.5 goles"), ("under2.5", r"menos de 2\.5 goles"), ("btts", r"ambos marcan"), ("dc", r" o empate$"),
       ("gana", r"^gana "), ("corn_over", r"^más de [\d.]+ córners"), ("corn_under", r"^menos de [\d.]+ córners"),
       ("corn_mas", r"saca más córners"), ("tarj_over", r"^más de [\d.]+ tarjetas"), ("tarj_under", r"^menos de [\d.]+ tarjetas")]
NBA = [("pts", r"\+ puntos$"), ("ast", r"\+ asistencias$"), ("3pt", r"\+ triples$"), ("reb", r"\+ rebotes$"),
       ("handicap", r"^hándicap "), ("total", r"^total: "), ("gana", r"^gana ")]

def tipo(market, nba=False):
    k = re.sub(r"\s*\(cuota.*?\)", "", market).strip().lower()
    return next((("nba:" if nba else "fut:") + name for name, rx in (NBA if nba else FUT) if re.search(rx, k)), None)

def tabla():
    """{tipo: (aciertos, n, probabilidad media anunciada)} con todo lo verificado en data/."""
    acc = {}
    for f in (ROOT / "data").glob("*-*.json"):
        nba = f.name.startswith("nba-")
        for m in json.loads(f.read_text(encoding="utf-8"))["matches"]:
            for p in m["picks"]:
                t = tipo(p["market"], nba)
                if t and p.get("prob") and p["result"] in ("hit", "miss"):
                    h, n, s = acc.get(t, (0, 0, 0))
                    acc[t] = (h + (p["result"] == "hit"), n + 1, s + p["prob"])
    return {t: (h, n, s / n) for t, (h, n, s) in acc.items()}

def ajusta(p, market, tab, nba=False):
    """Probabilidad en % corregida con el historial de ese tipo de mercado."""
    h, n, mean = tab.get(tipo(market, nba), (0, 0, 0))
    return round(p + (100 * h / n - mean) * n / (n + 30)) if n else round(p)

def prob_us(ml):
    """Probabilidad implícita (sin quitar el margen) de una cuota americana."""
    ml = float(ml)
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)

def decimal(ml):
    ml = float(ml)
    return 1 + (ml / 100 if ml > 0 else 100 / -ml)

assert tipo("Gana Jazz (cuota 1.93)", True) == "nba:gana" and tipo("Más de 9.5 córners") == "fut:corn_over"
assert ajusta(68, "Más de 9.5 córners", {"fut:corn_over": (13, 25, 68.0)}) == 61
assert abs(prob_us(-200) - 2 / 3) < 1e-9 and decimal(150) == 2.5

if __name__ == "__main__":
    for t, (h, n, mean) in sorted(tabla().items()):
        print(f"{t:16} {h:3}/{n:<3} acertó {100 * h / n:3.0f} %  anunciado {mean:3.0f} %  corrección {round((100 * h / n - mean) * n / (n + 30)):+d}")
