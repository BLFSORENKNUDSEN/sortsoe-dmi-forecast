# Sortsø Strand DMI forecast

Lokal vejrudsigt baseret på DMI Forecast Data EDR API og HARMONIE DINI surface modellen.

## Arkitektur

1. GitHub Actions kører to gange i timen.
2. `scripts/fetch_forecast.py` henter punktprognosen fra DMI.
3. Data omsættes til Celsius, hPa, mm/time og danske vindretninger.
4. Scriptet klassificerer vejret og genererer `data/sortsoe.json`.
5. Strandvejr.dk kan hente JSON filen direkte fra GitHub Pages, raw GitHub eller en kopi på eget domæne.

## Koordinater

Standardpunktet er vejrstationen ved Sortsø Strand:

* latitude: 54.9347
* longitude: 11.9889

Koordinaterne kan ændres med miljøvariablerne `SORTSOE_LAT` og `SORTSOE_LON`.

## Kør lokalt

```bash
python scripts/fetch_forecast.py
```

Resultatet skrives til `data/sortsoe.json`.

## GitHub

Under repository Settings > Actions > General skal GitHub Actions have tilladelse til at skrive til repository, hvis standardindstillingen ikke allerede tillader det.

Workflowet kan også startes manuelt via Actions > Update Sortsoe forecast > Run workflow.

## Strandvejr

Indsæt eksempelvis:

```html
<link rel="stylesheet" href="/css/forecast.css">
<div data-sortsoe-forecast></div>
<script>
window.SORTSOE_FORECAST_URL = 'https://DIT-DOMAENE/data/sortsoe.json';
</script>
<script src="/js/forecast.js"></script>
```

I den endelige løsning anbefales egne SVG ikoner i stedet for emoji. JSON strukturen ændrer sig ikke af den grund.

## Vigtige DMI enheder

* `temperature-2m`: Kelvin, omsættes til Celsius
* `wind-speed-10m`: m/s
* `wind-dir-10m`: grader fra sand nord
* `gust-wind-speed-10m`: m/s
* `fraction-of-cloud-cover`: 0 til 1, omsættes til procent
* `rain-precipitation-rate`: kg/m²/s, svarende til mm/s, ganges med 3600 for mm/time
* `pressure-sealevel`: Pa, divideres med 100 for hPa

## Næste trin

Når grundflowet virker, bør vi udskifte emoji med Strandvejr SVG ikoner, forbedre den danske tekstgenerator og koble UV, vandstand, bølger og havtemperatur på samme visning.
