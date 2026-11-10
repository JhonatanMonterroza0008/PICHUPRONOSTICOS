"""Genera data/nba-AAAA-MM-DD.json con pronósticos de la NBA para esa fecha (fecha de EE. UU.).

Uso: python tools/nba.py 2026-11-11 [tools/lines/nba-2026-11-11.json]
El segundo argumento es opcional: líneas de una casa de apuestas por abreviatura del local
(ml, spread del local, total y sus cuotas [local/más, visitante/menos]). Con él se añaden hándicap y total.
Fuente: API pública de ESPN. Solo biblioteca estándar.
Los umbrales ("20+ puntos") son propios: el mayor valor que el jugador alcanzó en al menos
el 80 % de sus últimos 10 partidos. No son líneas de casas de apuestas.
"""
import json, math, pathlib, statistics, sys, urllib.request
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

def team_form(team_id):
    """Últimos 10 partidos terminados del equipo: lista de (puntos a favor, puntos en contra)."""
    out = []
    for e in get(f"{SITE}/teams/{team_id}/schedule")["events"]:
        c = e["competitions"][0]
        if not c["status"]["type"]["completed"]:
            continue
        me = next(x for x in c["competitors"] if x["team"]["id"] == team_id)
        other = next(x for x in c["competitors"] if x["team"]["id"] != team_id)
        out.append((me["score"]["value"], other["score"]["value"]))
    return out[-10:]

def shrunk(p):
    """Probabilidad en %, acercada al 50 porque la muestra es de unos 10 partidos."""
    return round(50 + (100 * p - 50) * 0.6)

def line_picks(teams, line):
    """Hándicap y total frente a la línea de la casa. Desviaciones típicas habituales en NBA: 13 (margen) y 18 (total)."""
    phi = statistics.NormalDist().cdf
    h, a = team_form(teams["home"]["team"]["id"]), team_form(teams["away"]["team"]["id"])
    if len(h) < 5 or len(a) < 5:
        return []
    avg = lambda rows, i: sum(r[i] for r in rows) / len(rows)
    total = (avg(h, 0) + avg(a, 1)) / 2 + (avg(a, 0) + avg(h, 1)) / 2
    margin = ((avg(h, 0) - avg(h, 1)) - (avg(a, 0) - avg(a, 1))) / 2 + 2.5  # 2,5 puntos por jugar en casa
    hn, an = teams["home"]["team"]["shortDisplayName"], teams["away"]["team"]["shortDisplayName"]
    picks = []
    def add(market, p, odds, why):
        if p >= 55:  # por debajo no hay ventaja clara frente a la línea
            picks.append({"market": f"{market} (cuota {odds:.2f})", "prob": min(p, 85), "conf": conf(p), "why": why.replace(".", ","),
                          "result": "pending", "fact": None, "top": False})
    sp, t = line["spread"], line["total"]
    p_home = shrunk(1 - phi((-sp - margin) / 13))
    side = (f"Hándicap {hn} {sp:+g}", p_home, line["spread_odds"][0]) if p_home >= 50 else (f"Hándicap {an} {-sp:+g}", 100 - p_home, line["spread_odds"][1])
    add(*side, f"Diferencia esperada: {hn} {margin:+.1f} con los últimos {len(h)} y {len(a)} partidos")
    p_over = shrunk(1 - phi((t - total) / 18))
    over_h, over_a = sum(x + y > t for x, y in h), sum(x + y > t for x, y in a)
    side = (f"Total: más de {t:g} puntos", p_over, line["total_odds"][0]) if p_over >= 50 else (f"Total: menos de {t:g} puntos", 100 - p_over, line["total_odds"][1])
    add(*side, f"Total esperado {total:.0f}; lo superaron {hn} en {over_h} de {len(h)} y {an} en {over_a} de {len(a)}")
    return picks

def conf(p):
    return "alta" if p >= 65 else "media" if p >= 50 else "baja"

def build(date, lines=None):
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
            line = (lines or {}).get(teams["home"]["team"]["abbreviation"])
            odds = f" (cuota {line['ml'][0 if side == 'home' else 1]:.2f})" if line else ""
            picks.append({"market": f"Gana {teams[side]['team']['shortDisplayName']}{odds}", "prob": p, "conf": conf(p),
                          "why": f"{p} % según el modelo de ESPN", "result": "pending", "fact": None, "top": False})
            if line:
                picks += line_picks(teams, line)
        except (KeyError, ValueError, TypeError):
            pass
        for key in STATS:  # los 3 más probables de cada estadística
            best = sorted((c for c in cands if c["key"] == key), key=lambda c: (-c["prob"], -c["avg"]))[:3]
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
    note = "Umbrales de jugadores propios, a partir de sus últimos 10 partidos; no son líneas de casas de apuestas."
    if lines:
        note += " Hándicap, total y cuotas: líneas de una casa de apuestas tomadas el día del partido."
    return {"date": date, "sport": "nba", "title": f"NBA, {len(matches)} partidos",
            "note": note,
            "matches": matches}

if __name__ == "__main__":
    date = sys.argv[1]
    lines = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")) if len(sys.argv) > 2 else None
    day = build(date, lines)
    (ROOT / "data" / f"nba-{date}.json").write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
    idx_path = ROOT / "data" / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    idx["nba"] = sorted(set(idx.get("nba", [])) | {date})
    idx_path.write_text(json.dumps(idx, indent=1), encoding="utf-8")
    assert pick_for([30, 28, 25, 25, 22, 21, 20, 20, 19, 8], 10, 5) == (20, 8)  # autocomprobación del umbral
    assert shrunk(0.5) == 50 and shrunk(1) == 80
    print(len(day["matches"]), "partidos,", sum(len(m["picks"]) for m in day["matches"]), "pronósticos")
