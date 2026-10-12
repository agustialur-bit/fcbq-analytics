# La Nit dels Tirs

Pòster il·lustrat (no forma part de l'app): cada tir es converteix en un
estel, sobre un skyline de Manresa l'alçada del qual reflecteix el volum
real de tirs per zona.

- `data.json` — **temporada passada**, tancada. No s'actualitza.
- `data_temporada_actual.json` — **temporada en curs**. Es va ampliant
  jornada a jornada amb `append_shots.py`.
- `template.html` — el generador del pòster.
- `build.py` — combina `template.html` amb un dels dos `data*.json` i
  escriu l'HTML final.

## Afegir una jornada nova

```
python3 append_shots.py tirs_jornada.json --data data_temporada_actual.json
python3 build.py sortida.html --data data_temporada_actual.json
```
