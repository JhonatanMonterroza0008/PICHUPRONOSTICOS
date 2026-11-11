"""Marca como acertados o fallados los pronósticos pendientes de data/ cuyos partidos ya terminaron.

Uso: python tools/verify.py
Fuente: API pública de ESPN. Reglas en README.md. Lo que no se puede leer con seguridad se deja pendiente.
"""
import difflib, json, pathlib, re, sys, unicodedata, urllib.request
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOC = "https://site.api.espn.com/apis/site/v2/sports/soccer/all"
NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ALIAS = {"psg": "paris saint germain", "city": "manchester city", "united": "manchester united"}
STAT = {"puntos": "PTS", "asistencias": "AST", "triples": "3PT", "rebotes": "REB"}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)

def norm(s):
    s = unicodedata.normalize("NFKD", s.lower().replace("ø", "o")).encode("ascii", "ignore").decode()
    s = re.sub(r"sub-?(\d+)", r"u\1", s)
    s = " ".join(w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w not in ("fc", "cf", "de", "women", "w"))
    return ALIAS.get(s, s)

def same(a, b):
    """¿Dos nombres son el mismo equipo o jugador? Admite nombres cortos ('Inter Bogotá' ~ 'Internacional de Bogotá')."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    short, long_ = sorted((a.split(), b.split()), key=len)
    if all(any(t.startswith(w) or w.startswith(t) for t in long_) for w in short if len(w) > 2) and any(len(w) > 2 for w in short):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8

def num(x):
    return f"{x:g}"

# ---------- fútbol
def soccer_events(date):
    out = []
    for d in (date, date + timedelta(days=1)):  # los partidos nocturnos caen en el día siguiente en UTC
        try:
            out += get(f"{SOC}/scoreboard?dates={d:%Y%m%d}&limit=500").get("events", [])
        except Exception:
            pass
    return out

def soccer_ctx(m, events):
    """Marcador, córners y tarjetas del partido, vistos desde el local de nuestro archivo. None si no terminó o no se encontró."""
    for e in events:
        c = e["competitions"][0]
        t = {x["homeAway"]: x for x in c["competitors"]}
        hn, an = t["home"]["team"]["displayName"], t["away"]["team"]["displayName"]
        if same(m["home"], hn) and same(m["away"], an):
            flip = False
        elif same(m["home"], an) and same(m["away"], hn):
            flip = True
        else:
            continue
        st = e["status"]["type"]
        if st["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED"):
            return {"void": True}
        if not st.get("completed"):
            return None
        g = [int(t["home"]["score"]), int(t["away"]["score"])]
        corners = cards = None
        try:
            box = {x["homeAway"]: {s["name"]: s["displayValue"] for s in x.get("statistics", [])} for x in get(f"{SOC}/summary?event={e['id']}")["boxscore"]["teams"]}
            if all("wonCorners" in box[k] for k in ("home", "away")):
                corners = [int(box["home"]["wonCorners"]), int(box["away"]["wonCorners"])]
            if all("yellowCards" in box[k] for k in ("home", "away")):
                cards = [int(box[k]["yellowCards"]) + int(box[k].get("redCards", 0)) for k in ("home", "away")]
        except Exception:
            pass
        if flip:
            g, corners, cards = g[::-1], corners and corners[::-1], cards and cards[::-1]
        return {"g": g, "corners": corners, "cards": cards}
    return None

def grade_soccer(market, m, c):
    """Devuelve (resultado, dato) o None si el mercado no se reconoce."""
    k = re.sub(r"\s*\(cuota.*?\)", "", market).strip()
    low = k.lower()
    side = lambda name: 0 if same(name, m["home"]) else 1 if same(name, m["away"]) else None
    hg, ag = c["g"]
    ok = lambda b: "hit" if b else "miss"
    nodata = ("void", "Sin dato para verificar")
    if x := re.match(r"(m[aá]s|menos) de ([\d.]+) (goles|c[oó]rners|tarjetas)", low):
        kind, line = x[3][0], float(x[2])
        vals = {"g": c["g"], "c": c["corners"], "t": c["cards"]}[kind]
        if vals is None:
            return nodata
        tot = sum(vals)
        unit = {"g": "goles", "c": "córners", "t": "tarjetas"}[kind]
        return ok(tot > line if x[1] != "menos" else tot < line), f"{tot} {unit}"
    if low.startswith("ambos marcan"):
        return ok(hg > 0 and ag > 0), f"{hg}-{ag}"
    if low.startswith("no hay empate"):
        return ok(hg != ag), f"{hg}-{ag}"
    if x := re.match(r"gana (.+)", k, re.I):
        s = side(x[1])
        return None if s is None else (ok(c["g"][s] > c["g"][1 - s]), f"{hg}-{ag}")
    if x := re.match(r"(.+) o empate$", k, re.I):
        s = side(x[1])
        return None if s is None else (ok(c["g"][s] >= c["g"][1 - s]), f"{hg}-{ag}")
    if x := re.match(r"(.+) (saca m[aá]s c[oó]rners|recibe m[aá]s tarjetas)", k, re.I):
        s, vals = side(x[1]), c["corners"] if "rner" in x[2] else c["cards"]
        if s is None:
            return None
        return nodata if vals is None else (ok(vals[s] > vals[1 - s]), f"{vals[s]} a {vals[1 - s]}")
    if x := re.match(r"(.+) h[aá]ndicap ([+-][\d.]+)", k, re.I):
        s = side(x[1])
        return None if s is None else (ok(c["g"][s] - c["g"][1 - s] + float(x[2]) > 0), f"{hg}-{ag}")
    return None

# ---------- NBA
def nba_ctx(m):
    s = get(f"{NBA}/summary?event={m['id']}")
    comp = s["header"]["competitions"][0]
    st = comp["status"]["type"]
    if st["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED"):
        return {"void": True}
    if not st.get("completed"):
        return None
    t = {x["homeAway"]: x for x in comp["competitors"]}
    players = {}
    for team in s["boxscore"].get("players", []):
        for block in team.get("statistics", []):
            col = {n: i for i, n in enumerate(block.get("labels", []))}
            for a in block.get("athletes", []):
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                st_ = a["stats"]
                try:
                    players[a["athlete"]["displayName"]] = {"PTS": int(st_[col["PTS"]]), "AST": int(st_[col["AST"]]), "REB": int(st_[col["REB"]]),
                                                            "3PT": int(st_[col["3PT"]].split("-")[0])}
                except (ValueError, KeyError, IndexError):
                    pass
    return {"g": [int(t["home"]["score"]), int(t["away"]["score"])], "players": players}

def grade_nba(market, m, c):
    k = re.sub(r"\s*\(cuota.*?\)", "", market).strip()
    side = lambda name: 0 if same(name, m["home"]) else 1 if same(name, m["away"]) else None
    hg, ag = c["g"]
    ok = lambda b: "hit" if b else "miss"
    if x := re.match(r"(.+?) (\d+)\+ (puntos|asistencias|triples|rebotes)$", k):
        st = next((v for n, v in c["players"].items() if norm(n) == norm(x[1])), None)
        if st is None:
            return "void", "No jugó"
        v = st[STAT[x[3]]]
        return ok(v >= int(x[2])), f"{v} {x[3]}"
    if x := re.match(r"gana (.+)", k, re.I):
        s = side(x[1])
        return None if s is None else (ok(c["g"][s] > c["g"][1 - s]), f"{hg}-{ag}")
    if x := re.match(r"h[aá]ndicap (.+) ([+-][\d.]+)$", k, re.I):
        s = side(x[1])
        return None if s is None else (ok(c["g"][s] - c["g"][1 - s] + float(x[2]) > 0), f"{hg}-{ag}")
    if x := re.match(r"total: (m[aá]s|menos) de ([\d.]+) puntos", k, re.I):
        tot = hg + ag
        return ok(tot > float(x[2]) if x[1].lower() != "menos" else tot < float(x[2])), f"{tot} puntos"
    return None

def main():
    done = {"hit": 0, "miss": 0, "void": 0}
    for f in sorted((ROOT / "data").glob("*.json")):
        if f.name == "index.json":
            continue
        day = json.loads(f.read_text(encoding="utf-8"))
        pend = [m for m in day["matches"] if any(p["result"] == "pending" for p in m["picks"])]
        if not pend:
            continue
        nba = f.name.startswith("nba-")
        events = None if nba else soccer_events(datetime.strptime(day["date"], "%Y-%m-%d"))
        changed = False
        for m in pend:
            try:
                c = nba_ctx(m) if nba else soccer_ctx(m, events)
            except Exception as ex:
                print("  sin datos:", m["home"], "-", m["away"], ex)
                continue
            if c is None:
                continue
            if not c.get("void"):
                m["score"] = f"{c['g'][0]}-{c['g'][1]}"
            for p in m["picks"]:
                if p["result"] != "pending":
                    continue
                r = ("void", "Partido aplazado") if c.get("void") else (grade_nba if nba else grade_soccer)(p["market"], m, c)
                if r:
                    p["result"], p["fact"] = r
                    done[r[0]] += 1
                    changed = True
            changed = True
        if changed:
            f.write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
    idx = ROOT / "data" / "index.json"
    j = json.loads(idx.read_text(encoding="utf-8"))
    j["updated"] = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d")
    idx.write_text(json.dumps(j, indent=1), encoding="utf-8")
    print(f"verificados: {done['hit']} aciertos, {done['miss']} fallos, {done['void']} anulados")

# autocomprobación de las reglas
_m = {"home": "Inter Bogotá", "away": "América de Cali"}
_c = {"g": [1, 2], "corners": [4, 4], "cards": [3, 2]}
assert same("Internacional de Bogotá", "Inter Bogotá") and not same("Chelsea", "Arsenal")
assert grade_soccer("América o empate", _m, _c) == ("hit", "1-2")
assert grade_soccer("Más de 4.5 tarjetas", _m, _c) == ("hit", "5 tarjetas")
assert grade_soccer("Inter Bogotá saca más córners", _m, _c) == ("miss", "4 a 4")
assert grade_soccer("Inter Bogotá hándicap +1.5", _m, _c)[0] == "hit"
assert grade_nba("Hándicap Jazz +9.5 (cuota 1.93)", {"home": "Utah Jazz", "away": "Miami Heat"}, {"g": [100, 109], "players": {}})[0] == "hit"

if __name__ == "__main__":
    main()
