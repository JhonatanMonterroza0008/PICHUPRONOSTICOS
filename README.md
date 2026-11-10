# PICHUPRONOSTICOS

Página estática (GitHub Pages) con pronósticos de fútbol por día, su resultado verificado y el porcentaje de acierto.

## Cómo se actualiza

La página solo lee archivos de `data/`. Para añadir o corregir un día no se toca `index.html`:

1. Crear o editar `data/AAAA-MM-DD.json`.
2. Añadir la fecha a `days` en `data/index.json` y poner `updated` con la fecha de hoy.

## Formato de un día

```json
{
  "date": "2026-11-10",
  "title": "Competiciones del día",
  "note": "Aclaraciones sobre los datos",
  "matches": [{
    "comp": "EFL Trophy", "time": "19:00", "home": "Leicester", "away": "Walsall",
    "score": null, "meta": "hora de Inglaterra · contexto del partido",
    "picks": [{
      "market": "Más de 8.5 córners", "prob": 76, "conf": "alta",
      "why": "Motivo en una línea", "result": "pending", "fact": null, "top": true
    }]
  }]
}
```

- `score`: `null` hasta que termina el partido; después, `"2-1"`.
- `conf`: `alta` (65 % o más), `media` (50–64 %), `baja` (menos de 50 %). `prob` puede ser `null`.
- `result`: `pending`, `hit`, `miss` o `void` (partido aplazado o dato imposible de verificar).
- `fact`: el dato real que decide el pronóstico, por ejemplo `"10 córners"`.
- `top`: `true` en los pronósticos que salen en "Lo más probable del día".

## Verificación de resultados

Goles, córners y tarjetas salen de la API pública de ESPN:
`https://site.api.espn.com/apis/site/v2/sports/soccer/<liga>/scoreboard?dates=AAAAMMDD` y
`.../summary?event=<id>` (`boxscore.teams[].statistics`: `wonCorners`, `yellowCards`, `redCards`).
Las tarjetas cuentan amarillas más rojas. Un empate en "saca más córners" o "recibe más tarjetas" es fallo.
