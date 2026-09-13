# Selvstændige GFS temperaturkort

Denne mappe indeholder en separat produktion af temperaturkort fra NOAA GFS. Den eksisterende DMI prognose, dens scripts, workflow og datafiler anvendes ikke af GFS produktionen.

## Resultat

Scriptet henter temperatur i to meters højde fra den nyeste tilgængelige GFS kørsel. Det fremstiller europæiske PNG kort for hver sjette prognosetime frem til fem døgn og skriver en oversigt i `gfs/output/manifest.json`.

Kortene får navnene `temperature_f000.png`, `temperature_f006.png` og så videre.

## Manuel kørsel

```bash
python -m pip install -r gfs/requirements.txt
python gfs/generate_temperature_maps.py
```

En kort prøvekørsel kan laves med:

```bash
python gfs/generate_temperature_maps.py --steps 0
```

## Automatisk kørsel

Workflowet `.github/workflows/gfs_maps.yml` starter klokken 05.15, 11.15, 17.15 og 23.15 UTC. Det kan også startes manuelt fra fanen Actions.

GFS workflowet skriver kun til `gfs/output`. DMI workflowet skriver fortsat kun til `data/sortsoe.json`.
