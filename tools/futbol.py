"""Genera data/AAAA-MM-DD.json con pronósticos de fútbol para esa fecha.

Uso: python tools/futbol.py 2026-11-11
Fuente: API pública de ESPN. Solo biblioteca estándar.
Método: goles con un modelo de Poisson sobre los últimos 10 partidos de cada equipo; córners y tarjetas
con los promedios de sus últimos 6 partidos con estadísticas. Todo se acerca al 50 % por la muestra pequeña.
"""
import json, math, pathlib, re, statistics, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

SOC = "https://site.api.espn.com/apis/site/v2/sports/soccer/all"
ROOT = pathlib.Path(__file__).resolve().parent.parent
UTC_OFFSET = -3
MAX_MATCHES = 14
# orden de preferencia por nombre de competición; lo que no aparece va al final
PRIORITY = ["UEFA Champions League", "World Cup", "Europa League", "Nations League", "Premier League", "LaLiga", "Serie A", "Bundesliga",
            "Ligue 1", "Conference League", "Qualif", "Libertadores", "Sudamericana", "Copa del Rey", "FA Cup", "Liga MX", "Colombia",
            "Argentin", "Brazil", "Championship", "LaLiga 2", "EFL", "International Friendly", "Women's Champions League"]
SKIP = re.compile(r"NCAA|Club Friendly|U-?\d\d|Under|Reserve|Youth", re.I)

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)

def score(x):
    s = x.get("score")
    return int(float(s["value"] if isinstance(s, dict) else s))

def team_form(team_id):
    """Últimos 10 partidos terminados: goles a favor y en contra; y córners y tarjetas de los 6 más recientes que tengan datos."""
    try:
        events = get(f"{SOC}/teams/{team_id}/schedule")["events"]
    except Exception:
        return None
    done = []
    for e in events:
        c = e["competitions"][0]
        if not c["status"]["type"].get("completed"):
            continue
        try:
            me = next(x for x in c["competitors"] if x["team"]["id"] == team_id)
            other = next(x for x in c["competitors"] if x["team"]["id"] != team_id)
            done.append((e["id"], score(me), score(other)))
        except (StopIteration, KeyError, TypeError, ValueError):
            pass
    done = done[-10:]
    def stats(eid):
        try:
            box = get(f"{SOC}/summary?event={eid}")["boxscore"]["teams"]
            row = lambda t: {s["name"]: float(s["displayValue"]) for s in t.get("statistics", []) if s["name"] in ("wonCorners", "yellowCards", "redCards")}
            me = row(next(t for t in box if t["team"]["id"] == team_id))
            ot = row(next(t for t in box if t["team"]["id"] != team_id))
            if "wonCorners" in me and "wonCorners" in ot:
                return me["wonCorners"], ot["wonCorners"], me.get("yellowCards", 0) + me.get("redCards", 0)
        except Exception:
            pass
    with ThreadPoolExecutor(6) as ex:
        extra = [s for s in ex.map(stats, [d[0] for d in done[-6:]]) if s]
    return {"gf": [d[1] for d in done], "ga": [d[2] for d in done], "extra": extra}

def pois(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)

def p_over(lam, line):
    """P(total > line) para un total de Poisson."""
    return 1 - sum(pois(lam, k) for k in range(int(math.floor(line)) + 1))

def shrunk(p, base=0.5):
    return round(100 * (base + (p - base) * 0.75))

def conf(p):
    return "alta" if p >= 65 else "media" if p >= 50 else "baja"

def analyse(home, away, hf, af):
    """Lista de pronósticos para un partido, del más al menos probable."""
    avg = lambda v: sum(v) / len(v)
    out = []
    def add(market, p, why):
        if p >= 55:
            p = min(p, 85)
            out.append({"market": market, "prob": p, "conf": conf(p), "why": why.replace(".", ","), "result": "pending", "fact": None, "top": False})
    n = f"últimos {len(hf['gf'])} y {len(af['gf'])} partidos"
    lh, la = (avg(hf["gf"]) + avg(af["ga"])) / 2 * 1.08, (avg(af["gf"]) + avg(hf["ga"])) / 2 * 0.92
    grid = [[pois(lh, i) * pois(la, j) for j in range(9)] for i in range(9)]
    ph = sum(grid[i][j] for i in range(9) for j in range(9) if i > j)
    pa = sum(grid[i][j] for i in range(9) for j in range(9) if i < j)
    pd = 1 - ph - pa
    fav, pf = (home, ph) if ph >= pa else (away, pa)
    form = f"{home}: {avg(hf['gf']):.1f} goles a favor y {avg(hf['ga']):.1f} en contra; {away}: {avg(af['gf']):.1f} y {avg(af['ga']):.1f}"
    if shrunk(pf, 0.4) >= 55:
        add(f"Gana {fav}", shrunk(pf, 0.4), form)
    else:
        add(f"{fav} o empate", shrunk(pf + pd, 0.66), form)
    po = sum(grid[i][j] for i in range(9) for j in range(9) if i + j > 2)
    o_h, o_a = sum(a + b > 2 for a, b in zip(hf["gf"], hf["ga"])), sum(a + b > 2 for a, b in zip(af["gf"], af["ga"]))
    why = f"Se esperan {lh + la:.1f} goles; más de 2.5 en {o_h} de {len(hf['gf'])} de {home} y {o_a} de {len(af['gf'])} de {away}"
    add("Más de 2.5 goles", shrunk(po), why) if po >= 0.5 else add("Menos de 2.5 goles", shrunk(1 - po), why)
    pb = (1 - pois(lh, 0)) * (1 - pois(la, 0))
    add("Ambos marcan", shrunk(pb), f"Goles esperados: {home} {lh:.1f}, {away} {la:.1f}")
    if len(hf["extra"]) >= 4 and len(af["extra"]) >= 4:
        hc, ac = (avg([e[0] for e in hf["extra"]]) + avg([e[1] for e in af["extra"]])) / 2, (avg([e[0] for e in af["extra"]]) + avg([e[1] for e in hf["extra"]])) / 2
        why = f"Se esperan {hc + ac:.1f} córners: {home} {hc:.1f} y {away} {ac:.1f}"
        over = [(l, p_over(hc + ac, l)) for l in (10.5, 9.5, 8.5, 7.5)]
        under = [(l, 1 - p_over(hc + ac, l)) for l in (8.5, 9.5, 10.5, 11.5)]
        best = next(((f"Más de {l} córners", p) for l, p in over if p >= 0.66), None) or next(((f"Menos de {l} córners", p) for l, p in under if p >= 0.66), None)
        if best:
            add(best[0], shrunk(best[1]), why)
        if abs(hc - ac) >= 1.8:
            p = statistics.NormalDist().cdf(abs(hc - ac) / math.sqrt(hc + ac))
            add(f"{home if hc > ac else away} saca más córners", shrunk(p), why)
        cards = avg([e[2] for e in hf["extra"]]) + avg([e[2] for e in af["extra"]])
        why = f"Se esperan {cards:.1f} tarjetas entre los dos"
        best = next(((f"Más de {l} tarjetas", p_over(cards, l)) for l in (4.5, 3.5) if p_over(cards, l) >= 0.66), None) \
            or next(((f"Menos de {l} tarjetas", 1 - p_over(cards, l)) for l in (4.5, 5.5) if 1 - p_over(cards, l) >= 0.66), None)
        if best:
            add(best[0], shrunk(best[1]), why)
    return sorted(out, key=lambda p: -p["prob"])[:4]

def build(date):
    cands = []
    for e in get(f"{SOC}/scoreboard?dates={date.replace('-', '')}&limit=500").get("events", []):
        c = e["competitions"][0]
        league = c.get("altGameNote") or ""
        if not league or SKIP.search(league) or e["status"]["type"]["name"] != "STATUS_SCHEDULED":
            continue
        rank = next((i for i, k in enumerate(PRIORITY) if k.lower() in league.lower()), len(PRIORITY))
        if "women" in league.lower() and "Women" not in PRIORITY[rank] if rank < len(PRIORITY) else False:
            rank = len(PRIORITY)
        cands.append((rank, e["date"], e, league))
    cands.sort(key=lambda x: (x[0], x[1]))
    matches = []
    for rank, _, e, league in cands[:30]:
        if len(matches) >= MAX_MATCHES:
            break
        t = {x["homeAway"]: x["team"] for x in e["competitions"][0]["competitors"]}
        hf, af = team_form(t["home"]["id"]), team_form(t["away"]["id"])
        if not hf or not af or len(hf["gf"]) < 5 or len(af["gf"]) < 5:
            continue
        picks = analyse(t["home"]["displayName"], t["away"]["displayName"], hf, af)
        if not picks:
            continue
        local = datetime.strptime(e["date"], "%Y-%m-%dT%H:%MZ") + timedelta(hours=UTC_OFFSET)
        w = lambda f: f"{sum(a > b for a, b in zip(f['gf'], f['ga']))}G {sum(a == b for a, b in zip(f['gf'], f['ga']))}E {sum(a < b for a, b in zip(f['gf'], f['ga']))}P"
        matches.append({"comp": league.split(",")[0], "id": e["id"], "time": local.strftime("%H:%M"), "home": t["home"]["displayName"],
                        "away": t["away"]["displayName"], "score": None,
                        "meta": f"hora UTC−3 · últimos partidos: {t['home']['abbreviation']} {w(hf)} · {t['away']['abbreviation']} {w(af)}", "picks": picks})
    if not matches:
        return None
    allp = [p for m in matches for p in m["picks"]]
    for p in sorted(allp, key=lambda p: -p["prob"])[:9]:
        p["top"] = True
    comps = list(dict.fromkeys(m["comp"] for m in matches))
    return {"date": date, "title": ", ".join(comps[:4]) + (" y más" if len(comps) > 4 else ""),
            "note": "Goles con un modelo de Poisson sobre los últimos 10 partidos de cada equipo; córners y tarjetas con los últimos 6 que tienen estadísticas. Sin datos de árbitros ni bajas.",
            "matches": matches}

assert abs(p_over(2.5, 2.5) - 0.456) < 0.01 and shrunk(0.9) == 80  # autocomprobación

if __name__ == "__main__":
    date = sys.argv[1]
    day = build(date)
    if not day:
        print("sin partidos de fútbol con datos suficientes para", date)
        sys.exit(0)
    (ROOT / "data" / f"{date}.json").write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
    idx_path = ROOT / "data" / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    idx["days"] = sorted(set(idx.get("days", [])) | {date})
    idx_path.write_text(json.dumps(idx, indent=1), encoding="utf-8")
    print(len(day["matches"]), "partidos,", sum(len(m["picks"]) for m in day["matches"]), "pronósticos")
