(() => {
  const RAW_BASE = window.SORTSOE_FORECAST_BASE_URL || 'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/data';
  const SORTSOE_URL = window.SORTSOE_FORECAST_URL || `${RAW_BASE}/sortsoe.json`;
  const MANIFEST_URL = `${RAW_BASE}/grid/manifest.json`;
  const root = document.querySelector('[data-sortsoe-forecast]');
  if (!root) return;

  const state = {
    manifest: null,
    selectedName: 'Sortsø Strand',
    requestId: 0
  };

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtHour = iso => new Intl.DateTimeFormat('da-DK', {hour:'2-digit', minute:'2-digit'}).format(new Date(iso));
  const fmtDayShort = iso => new Intl.DateTimeFormat('da-DK', {weekday:'short'}).format(new Date(iso));
  const fmtDay = iso => new Intl.DateTimeFormat('da-DK', {weekday:'long', day:'numeric', month:'short'}).format(new Date(`${iso}T12:00:00`));
  const fmtGenerated = iso => new Intl.DateTimeFormat('da-DK', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}).format(new Date(iso));

  const svg = (code, time) => {
    const hour = new Date(time || Date.now()).getHours();
    const night = hour < 6 || hour >= 21;
    const common = 'viewBox="0 0 64 64" aria-hidden="true" focusable="false"';
    const sun = '<circle cx="24" cy="24" r="9"/><g stroke-width="3" stroke-linecap="round"><path d="M24 5v6M24 37v6M5 24h6M37 24h6M10.6 10.6l4.3 4.3M33.1 33.1l4.3 4.3M37.4 10.6l-4.3 4.3M14.9 33.1l-4.3 4.3"/></g>';
    const moon = '<path d="M34 8c-10 3-16 14-12 24 4 11 17 16 27 10-6 10-20 15-31 8C5 43 2 26 10 15 16 7 26 4 34 8Z"/>';
    const cloud = '<path d="M18 44h29c7 0 12-5 12-11s-5-11-12-11c-1 0-2 0-3 .3C41 15 35 11 27 11c-9 0-16 6-18 15-6 1-10 5-10 10 0 5 5 8 11 8h8Z"/>';
    const drops = '<g stroke-width="3" stroke-linecap="round"><path d="M20 49l-3 7M32 49l-3 7M44 49l-3 7"/></g>';
    const heavy = '<g stroke-width="4" stroke-linecap="round"><path d="M17 48l-4 9M29 48l-4 9M41 48l-4 9M53 48l-4 9"/></g>';

    if (code === 'clear') {
      return night
        ? `<svg class="weather-svg moon" ${common}>${moon}</svg>`
        : `<svg class="weather-svg sun" ${common}>${sun}</svg>`;
    }
    if (code === 'partly_cloudy') {
      const light = night ? moon : sun;
      return `<svg class="weather-svg partly" ${common}><g class="behind">${light}</g><g class="cloud">${cloud}</g></svg>`;
    }
    if (code === 'light_rain') return `<svg class="weather-svg rain" ${common}><g class="cloud">${cloud}</g><g class="precip">${drops}</g></svg>`;
    if (code === 'rain' || code === 'heavy_rain') return `<svg class="weather-svg rain" ${common}><g class="cloud">${cloud}</g><g class="precip">${code === 'heavy_rain' ? heavy : drops}</g></svg>`;
    return `<svg class="weather-svg cloud" ${common}><g class="cloud">${cloud}</g></svg>`;
  };

  const weatherCode = (cloud, rain) => {
    const c = Number(cloud || 0);
    const r = Number(rain || 0);
    if (r >= 8) return 'heavy_rain';
    if (r >= 1) return 'rain';
    if (r >= 0.1) return 'light_rain';
    if (c >= 88) return 'overcast';
    if (c >= 60) return 'cloudy';
    if (c >= 25) return 'partly_cloudy';
    return 'clear';
  };

  const weatherLabel = code => ({
    clear:'Klart',
    partly_cloudy:'Let skyet',
    cloudy:'Skyet',
    overcast:'Overskyet',
    light_rain:'Let regn',
    rain:'Regn',
    heavy_rain:'Kraftig regn'
  }[code] || 'Vejr');

  const windDirText = deg => {
    if (deg == null) return '';
    const dirs = ['N','NØ','Ø','SØ','S','SV','V','NV'];
    return dirs[Math.floor((Number(deg) + 22.5) / 45) % 8];
  };

  const initShell = () => {
    root.innerHTML = `
      <section class="forecast-block">
        <div class="forecast-tools">
          <button type="button" class="forecast-location-btn" data-use-position aria-label="Brug min position">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><circle cx="12" cy="12" r="5"/></svg>
            <span>Min position</span>
          </button>
          <div class="forecast-search-wrap">
            <svg class="forecast-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="m16 16 5 5"/></svg>
            <input type="search" data-city-search autocomplete="off" placeholder="Søg by i Danmark" aria-label="Søg by i Danmark">
            <div class="forecast-suggestions" data-city-suggestions hidden></div>
          </div>
        </div>
        <div class="forecast-status" data-forecast-status>Henter vejrudsigt…</div>
        <div data-forecast-content></div>
      </section>`;
  };

  const status = text => {
    const el = root.querySelector('[data-forecast-status]');
    if (el) {
      el.textContent = text || '';
      el.hidden = !text;
    }
  };

  const distance2 = (lat1, lon1, lat2, lon2) => {
    const x = (lon1 - lon2) * Math.cos(((lat1 + lat2) / 2) * Math.PI / 180);
    const y = lat1 - lat2;
    return x*x + y*y;
  };

  const summarizeDays = hours => {
    const groups = {};
    hours.forEach(h => {
      const day = h.time.slice(0,10);
      (groups[day] ||= []).push(h);
    });
    const severity = ['heavy_rain','rain','light_rain','overcast','cloudy','partly_cloudy','clear'];
    return Object.entries(groups).map(([date, vals]) => {
      const temps = vals.map(v=>v.temperature).filter(v=>v!=null);
      const winds = vals.map(v=>v.wind).filter(v=>v!=null);
      const rains = vals.map(v=>Number(v.rainMm || 0));
      const codes = vals.map(v=>v.weather);
      const weather = severity.find(c => codes.includes(c)) || 'clear';
      const dirs = vals.map(v=>v.windDirection).filter(v=>v!=null);
      let meanDir = null;
      if (dirs.length) {
        const x = dirs.reduce((a,d)=>a+Math.sin(d*Math.PI/180),0);
        const y = dirs.reduce((a,d)=>a+Math.cos(d*Math.PI/180),0);
        meanDir = (Math.atan2(x,y)*180/Math.PI+360)%360;
      }
      const rainMm = rains.reduce((a,b)=>a+b,0);
      const windAvg = winds.length ? winds.reduce((a,b)=>a+b,0)/winds.length : null;
      let summary = weatherLabel(weather);
      if (temps.length) summary += `, ${Math.round(Math.min(...temps))} til ${Math.round(Math.max(...temps))} grader`;
      if (rainMm >= .1) summary += `, omkring ${rainMm.toFixed(1).replace('.0','')} mm nedbør`;
      if (windAvg != null) summary += `, vind ${windDirText(meanDir)} omkring ${Math.round(windAvg)} m/s`;
      return {
        date,
        temperatureMin: temps.length ? Math.min(...temps) : null,
        temperatureMax: temps.length ? Math.max(...temps) : null,
        rainMm,
        windAvg,
        windDirectionText: windDirText(meanDir),
        weather,
        weatherLabel: weatherLabel(weather),
        summary: summary + '.'
      };
    });
  };

  const pointToForecast = (tile, point, name, lat, lon) => {
    const fields = tile.fields;
    const ix = Object.fromEntries(fields.map((f,i)=>[f,i]));
    const times = tile.times || [];
    const arr = key => point[ix[key]] || [];
    const temp = arr('temperature');
    const wind = arr('wind');
    const dir = arr('windDirection');
    const cloud = arr('cloudCover');
    const rain = arr('rainMm');
    const humidity = arr('humidity');
    const pressure = arr('pressure');

    const hours = times.map((time,i) => {
      const code = weatherCode(cloud[i], rain[i]);
      return {
        time,
        leadHours: i * Number(tile.intervalHours || 3),
        temperature: temp[i],
        wind: wind[i],
        windDirection: dir[i],
        windDirectionText: windDirText(dir[i]),
        cloudCover: cloud[i],
        rainMm: rain[i],
        humidity: humidity[i],
        pressure: pressure[i],
        weather: code,
        weatherLabel: weatherLabel(code)
      };
    });

    return {
      location: {
        name,
        latitude: lat,
        longitude: lon,
        modelPoint: {
          latitude: point[ix.gridLat],
          longitude: point[ix.gridLon]
        }
      },
      source: {
        provider:'DMI',
        model:'HARMONIE DINI surface',
        modelRun:tile.modelRun,
        intervalHours:tile.intervalHours,
        generated: state.manifest?.generated
      },
      currentForecast:hours[0],
      hours,
      days:summarizeDays(hours)
    };
  };

  const tileKey = (lat, lon) => {
    const glat = Math.round(lat * 10) / 10;
    const glon = Math.round(lon * 10) / 10;
    const a = Math.floor(glat);
    const b = Math.floor(glon);
    return `${String(a).padStart(2,'0')}_${String(b).padStart(2,'0')}`;
  };

  const getManifest = async () => {
    if (state.manifest) return state.manifest;
    const r = await fetch(`${MANIFEST_URL}?v=${Date.now()}`, {cache:'no-store'});
    if (!r.ok) throw new Error(`Manifest HTTP ${r.status}`);
    state.manifest = await r.json();
    return state.manifest;
  };

  const loadForecastForCoords = async (lat, lon, name='Din position') => {
    const id = ++state.requestId;
    status(`Henter vejrudsigt for ${name}…`);
    const manifest = await getManifest();
    const b = manifest.bounds || {};
    if (lat < b.south || lat > b.north || lon < b.west || lon > b.east) {
      throw new Error('Positionen ligger uden for Danmark-grid');
    }

    const key = tileKey(lat, lon);
    if (!(manifest.tiles || []).includes(key)) throw new Error('Ingen DMI-griddata for området');
    const r = await fetch(`${RAW_BASE}/grid/tile_${key}.json?v=${encodeURIComponent(manifest.modelRun)}`, {cache:'no-store'});
    if (!r.ok) throw new Error(`Grid HTTP ${r.status}`);
    const tile = await r.json();
    if (id !== state.requestId) return;

    const fi = Object.fromEntries(tile.fields.map((f,i)=>[f,i]));
    let best = null;
    let bestD = Infinity;
    tile.points.forEach(p => {
      const d = distance2(lat, lon, Number(p[fi.gridLat]), Number(p[fi.gridLon]));
      if (d < bestD) { bestD = d; best = p; }
    });
    if (!best) throw new Error('Intet gridpunkt fundet');

    state.selectedName = name;
    render(pointToForecast(tile, best, name, lat, lon));
    status('');
  };

  const loadSortsoe = async () => {
    status('Henter vejrudsigt for Sortsø Strand…');
    const r = await fetch(`${SORTSOE_URL}?v=${Date.now()}`, {cache:'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    state.selectedName = data.location?.name || 'Sortsø Strand';
    render(data);
    status('');
  };

  const weatherText = data => {
    const days = data.days || [];
    if (!days.length) return '';
    let text = days[0].summary || '';
    if (days[1]) text += ` I morgen: ${days[1].summary}`;
    return text;
  };

  const render = data => {
    const content = root.querySelector('[data-forecast-content]');
    if (!content) return;
    const hours = data.hours || [];
    const days = data.days || [];
    const current = hours[0] || data.currentForecast || {};
    const modelPoint = data.location?.modelPoint;
    const pointText = modelPoint
      ? `DMI-grid ${Number(modelPoint.latitude).toFixed(2)}°, ${Number(modelPoint.longitude).toFixed(2)}°`
      : '';

    content.innerHTML = `
      <div class="forecast-head">
        <div>
          <div class="forecast-kicker">DMI HARMONIE</div>
          <h2>Vejrudsigt for ${esc(data.location?.name || state.selectedName)}</h2>
        </div>
        <div class="forecast-updated">Opdateret ${data.source?.generated ? fmtGenerated(data.source.generated) : '–'}</div>
      </div>

      <div class="forecast-current">
        <div class="forecast-current-icon">${svg(current.weather, current.time)}</div>
        <div>
          <div class="forecast-current-temp">${current.temperature == null ? '–' : Math.round(current.temperature) + '°'}</div>
          <div class="forecast-current-label">${esc(current.weatherLabel || '')}</div>
        </div>
        <div class="forecast-current-facts">
          <span>Vind <strong>${current.wind == null ? '–' : Number(current.wind).toFixed(1)} m/s ${esc(current.windDirectionText || '')}</strong></span>
          <span>Nedbør <strong>${current.rainMm == null ? '–' : Number(current.rainMm).toFixed(1)} mm</strong></span>
          <span>Skydække <strong>${current.cloudCover == null ? '–' : Math.round(current.cloudCover) + '%'}</strong></span>
          <span>Tryk <strong>${current.pressure == null ? '–' : Math.round(current.pressure) + ' hPa'}</strong></span>
        </div>
      </div>

      <div class="forecast-text">${esc(weatherText(data))}</div>

      <h3>De kommende 60 timer</h3>
      <div class="forecast-hours">
        ${hours.map((h,i) => `
          <article class="forecast-hour">
            <div class="forecast-hour-day">${i === 0 || new Date(h.time).getDate() !== new Date(hours[i-1]?.time || h.time).getDate() ? esc(fmtDayShort(h.time)) : ''}</div>
            <div class="forecast-hour-time">${fmtHour(h.time)}</div>
            <div class="forecast-icon">${svg(h.weather, h.time)}</div>
            <div class="forecast-temp">${h.temperature == null ? '–' : Math.round(h.temperature) + '°'}</div>
            <div class="forecast-hour-label">${esc(h.weatherLabel)}</div>
            <div class="forecast-rain">${h.rainMm == null ? '–' : Number(h.rainMm).toFixed(1)} mm</div>
            <div class="forecast-wind">${h.wind == null ? '–' : Number(h.wind).toFixed(1)} m/s ${esc(h.windDirectionText || '')}</div>
          </article>`).join('')}
      </div>

      <h3>Døgnoversigt</h3>
      <div class="forecast-days">
        ${days.map(d => `
          <article class="forecast-day">
            <div class="forecast-day-name">${fmtDay(d.date)}</div>
            <div class="forecast-icon">${svg(d.weather, `${d.date}T12:00:00`)}</div>
            <div class="forecast-day-temp"><strong>${d.temperatureMax == null ? '–' : Math.round(d.temperatureMax) + '°'}</strong> / ${d.temperatureMin == null ? '–' : Math.round(d.temperatureMin) + '°'}</div>
            <div>${esc(d.weatherLabel)}</div>
            <div>${d.rainMm == null ? '–' : Number(d.rainMm).toFixed(1)} mm</div>
            <div>${d.windAvg == null ? '–' : Number(d.windAvg).toFixed(1)} m/s ${esc(d.windDirectionText || '')}</div>
          </article>`).join('')}
      </div>

      <div class="forecast-meta">Modelkørsel: ${esc(data.source?.modelRun || '–')} ${pointText ? '· ' + esc(pointText) : ''}</div>
    `;
  };

  const extractId = suggestion => {
    const candidates = [
      suggestion?.data?.sted_id,
      suggestion?.data?.stedid,
      suggestion?.data?.id,
      suggestion?.data?.sted?.id,
      suggestion?.sted_id,
      suggestion?.stedid,
      suggestion?.id
    ];
    return candidates.find(v => typeof v === 'string' && v.length > 10) || null;
  };

  const centerFromGeometry = geometry => {
    if (!geometry) return null;
    if (geometry.type === 'Point') return {lon:Number(geometry.coordinates[0]), lat:Number(geometry.coordinates[1])};
    const pts = [];
    const walk = value => {
      if (Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') {
        pts.push(value);
      } else if (Array.isArray(value)) value.forEach(walk);
    };
    walk(geometry.coordinates);
    if (!pts.length) return null;
    const lons = pts.map(p=>Number(p[0])), lats = pts.map(p=>Number(p[1]));
    return {lon:(Math.min(...lons)+Math.max(...lons))/2, lat:(Math.min(...lats)+Math.max(...lats))/2};
  };

  const resolveSuggestion = async suggestion => {
    const name = suggestion?.tekst || suggestion?.forslagstekst || suggestion?.data?.navn || 'Valgt by';
    const id = extractId(suggestion);
    let url;
    if (id) {
      url = `https://api.dataforsyningen.dk/steder?id=${encodeURIComponent(id)}&format=geojson`;
    } else {
      const rawName = suggestion?.data?.navn || String(name).split(',')[0].trim();
      url = `https://api.dataforsyningen.dk/steder?hovedtype=Bebyggelse&primærtnavn=${encodeURIComponent(rawName)}&format=geojson`;
    }
    const r = await fetch(url);
    if (!r.ok) throw new Error(`Stedopslag HTTP ${r.status}`);
    const geo = await r.json();
    const feature = geo.features?.[0] || geo;
    let center = null;
    const vc = feature?.properties?.visueltcenter || feature?.properties?.visuelt_center;
    if (vc?.coordinates) center = {lon:Number(vc.coordinates[0]), lat:Number(vc.coordinates[1])};
    if (!center) center = centerFromGeometry(feature.geometry);
    if (!center) throw new Error('Kunne ikke finde koordinater for byen');
    return {name:String(name).split(',')[0], ...center};
  };

  const setupSearch = () => {
    const input = root.querySelector('[data-city-search]');
    const box = root.querySelector('[data-city-suggestions]');
    let timer = null;
    let currentSuggestions = [];

    input.addEventListener('input', () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) {
        box.hidden = true;
        box.innerHTML = '';
        return;
      }
      timer = setTimeout(async () => {
        try {
          const url = `https://api.dataforsyningen.dk/stednavne2/autocomplete?q=${encodeURIComponent(q)}&hovedtype=Bebyggelse&per_side=8`;
          const r = await fetch(url);
          if (!r.ok) throw new Error(`Autocomplete HTTP ${r.status}`);
          currentSuggestions = await r.json();
          box.innerHTML = currentSuggestions.slice(0,8).map((s,i) => `<button type="button" data-suggestion-index="${i}">${esc(s.forslagstekst || s.tekst || s.data?.navn || '')}</button>`).join('');
          box.hidden = !currentSuggestions.length;
        } catch (err) {
          console.error('Bysøgning:', err);
          box.hidden = true;
        }
      }, 220);
    });

    box.addEventListener('click', async e => {
      const btn = e.target.closest('[data-suggestion-index]');
      if (!btn) return;
      const suggestion = currentSuggestions[Number(btn.dataset.suggestionIndex)];
      box.hidden = true;
      input.value = suggestion?.tekst || suggestion?.forslagstekst || '';
      try {
        const place = await resolveSuggestion(suggestion);
        await loadForecastForCoords(place.lat, place.lon, place.name);
      } catch (err) {
        console.error(err);
        status('Byen kunne ikke slås op. Prøv et andet navn.');
      }
    });

    document.addEventListener('click', e => {
      if (!e.target.closest('.forecast-search-wrap')) box.hidden = true;
    });
  };

  const usePosition = () => {
    if (!navigator.geolocation) {
      status('Din browser understøtter ikke positionsbestemmelse.');
      return;
    }
    status('Finder din position…');
    navigator.geolocation.getCurrentPosition(
      pos => loadForecastForCoords(
        pos.coords.latitude,
        pos.coords.longitude,
        'Din position'
      ).catch(err => {
        console.error(err);
        status('Kunne ikke hente vejr for din position. Viser Sortsø Strand.');
        loadSortsoe().catch(console.error);
      }),
      err => {
        console.warn('Geolocation:', err);
        status('');
        loadSortsoe().catch(console.error);
      },
      {enableHighAccuracy:false, timeout:10000, maximumAge:600000}
    );
  };

  initShell();
  setupSearch();
  root.querySelector('[data-use-position]').addEventListener('click', usePosition);

  // Show the known Sortsø forecast immediately, then replace it with the
  // user's local forecast if browser geolocation succeeds.
  loadSortsoe()
    .catch(err => { console.error(err); status('Vejrudsigten kunne ikke hentes lige nu.'); })
    .finally(() => {
      if (window.SORTSOE_AUTO_GEOLOCATION !== false && navigator.geolocation) {
        usePosition();
      }
    });
})();