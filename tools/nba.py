"""Genera data/nba-AAAA-MM-DD.json con pronósticos de la NBA para esa fecha (fecha de EE. UU.).

Uso: python tools/nba.py 2026-11-11
Fuente: API pública de ESPN. Solo biblioteca estándar.
Los umbrales ("20+ puntos") son propios: el mayor valor que el jugador alcanzó en al menos
el 80 % de sus últimos 10 partidos. No son líneas de casas de apuestas.
"""
import json, math, pathlib, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
WEB = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
ROOT = pathlib.Path(__file__).resolve().parent.parent
UTC_OFFSET = -3  # hora que muestra la página
# estadística: (columna del gamelog, nombre, mínimo que vale la pena, paso del umbral)
STATS = {"PTS": ("puntos", 10, 5), "AST": ("asistencias", 4, 2), "3PT": ("triples", 2, 1), "REB": ("rebotes", 6, 2)}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)

def last_games(athlete_id):
    """Últimos 10 partidos de temporada regular, del más reciente al más antiguo."""
    try:
        g = get(f"{WEB}/athletes/{athlete_id}/gamelog")
    except Exception:
        return []
    col = {name: i for i, name in enumerate(g.get("labels", []))}
    rows = []
    for st in g.get("seasonTypes", []):
        if "Regular" not in st.get("displayName", ""):
            continue
        for c in st.get("categories", []):
            for ev in c.get("events", []):
                s = ev["stats"]
                try:
                    rows.append({"MIN": float(s[col["MIN"]]), "PTS": int(s[col["PTS"]]), "AST": int(s[col["AST"]]),
                                 "REB": int(s[col["REB"]]), "3PT": int(s[col["3PT"]].split("-")[0])})
                except (ValueError, KeyError, IndexError):
                    pass
        break  # solo la temporada actual
    return rows[:10]

def pick_for(vals, floor, step):
    """Mayor umbral (múltiplo de step) alcanzado en >= 80 % de los partidos. Devuelve (umbral, aciertos) o None."""
    n = len(vals)
    t = sorted(vals, reverse=True)[math.ceil(0.8 * n) - 1] // step * step
    return (t, sum(v >= t for v in vals)) if t >= floor else None

def conf(p):
    return "alta" if p >= 65 else "media" if p >= 50 else "baja"

def build(date):
    events = get(f"{SITE}/scoreboard?dates={date.replace('-', '')}")["events"]
    matches = []
    for e in events:
        comp = e["competitions"][0]
        teams = {t["homeAway"]: t for t in comp["competitors"]}
        summ = get(f"{SITE}/summary?event={e['id']}")
        status = {i["athlete"]["id"]: i.get("status", "") for t in summ.get("injuries", []) for i in t.get("injuries", [])}
        out_names = [i["athlete"]["displayName"] for t in summ.get("injuries", []) for i in t.get("injuries", []) if "Out" in i.get("status", "")]
        cands = []
        for side in ("home", "away"):
            tid = teams[side]["team"]["id"]
            roster = [a for a in get(f"{SITE}/teams/{tid}/roster")["athletes"] if "Out" not in status.get(a["id"], "")]
            with ThreadPoolExecutor(8) as ex:
                logs = list(ex.map(lambda a: last_games(a["id"]), roster))
            for a, rows in zip(roster, logs):
                if len(rows) < 6 or sum(r["MIN"] for r in rows) / len(rows) < 24:
                    continue
                doubt = "Day-To-Day" in status.get(a["id"], "")
                for key, (name, floor, step) in STATS.items():
                    vals = [r[key] for r in rows]
                    got = pick_for(vals, floor, step)
                    if not got:
                        continue
                    t, hits = got
                    n, avg = len(vals), sum(vals) / len(vals)
                    p = min(88, round(100 * (hits + 1) / (n + 2))) - (8 if doubt else 0)
                    why = f"Lo logró en {hits} de sus últimos {n}; promedia {avg:.1f}".replace(".", ",")
                    cands.append({"key": key, "avg": avg, "market": f"{a['displayName']} {t}+ {name}", "prob": p, "conf": conf(p),
                                  "why": why + (" · en duda por lesión" if doubt else ""), "result": "pending", "fact": None, "top": False})
        picks = []
        pred = summ.get("predictor") or {}
        try:
            ph, pa = float(pred["homeTeam"]["gameProjection"]), float(pred["awayTeam"]["gameProjection"])
            side, p = ("home", ph) if ph >= pa else ("away", pa)
            p = min(85, round(p))
            picks.append({"market": f"Gana {teams[side]['team']['shortDisplayName']}", "prob": p, "conf": conf(p),
                          "why": f"{p} % según el modelo de ESPN", "result": "pending", "fact": None, "top": False})
        except (KeyError, ValueError, TypeError):
            pass
        for key in STATS:  # los 2 más probables de cada estadística
            best = sorted((c for c in cands if c["key"] == key), key=lambda c: (-c["prob"], -c["avg"]))[:2]
            picks += [{k: v for k, v in c.items() if k not in ("key", "avg")} for c in best]
        rec = lambda s: (teams[s].get("records") or [{}])[0].get("summary", "")
        local = datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ") + timedelta(hours=UTC_OFFSET)
        meta = f"hora UTC−3 · {teams['home']['team']['abbreviation']} {rec('home')} · {teams['away']['team']['abbreviation']} {rec('away')}"
        if out_names:
            meta += " · Bajas: " + ", ".join(out_names[:6])
        matches.append({"comp": "NBA", "id": e["id"], "time": local.strftime("%H:%M"), "home": teams["home"]["team"]["displayName"],
                        "away": teams["away"]["team"]["displayName"], "score": None, "meta": meta, "picks": picks})
    allp = [p for m in matches for p in m["picks"]]
    assert matches and all(1 <= p["prob"] <= 99 for p in allp), "datos de NBA incompletos"
    for p in sorted(allp, key=lambda p: -p["prob"])[:10]:
        p["top"] = True
    return {"date": date, "sport": "nba", "title": f"NBA, {len(matches)} partidos",
            "note": "Umbrales propios a partir de los últimos 10 partidos de cada jugador; no son líneas de casas de apuestas.",
            "matches": matches}

if __name__ == "__main__":
    date = sys.argv[1]
    day = build(date)
    (ROOT / "data" / f"nba-{date}.json").write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
    idx_path = ROOT / "data" / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    idx["nba"] = sorted(set(idx.get("nba", [])) | {date})
    idx_path.write_text(json.dumps(idx, indent=1), encoding="utf-8")
    assert pick_for([30, 28, 25, 25, 22, 21, 20, 20, 19, 8], 10, 5) == (20, 8)  # autocomprobación del umbral
    print(len(day["matches"]), "partidos,", sum(len(m["picks"]) for m in day["matches"]), "pronósticos")
