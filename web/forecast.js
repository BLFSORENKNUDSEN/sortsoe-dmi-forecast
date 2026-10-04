(() => {
  const FORECAST_FRONTEND_VERSION = '20261004-7';
  console.info('Strandvejr forecast frontend', FORECAST_FRONTEND_VERSION);
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

  const placeCenter = item => {
    const sted = item?.sted || item?.data?.sted || item?.data || {};
    const vc = sted?.visueltcenter || item?.visueltcenter;

    if (Array.isArray(vc) && vc.length >= 2) {
      return {lon:Number(vc[0]), lat:Number(vc[1])};
    }
    if (vc?.coordinates && vc.coordinates.length >= 2) {
      return {lon:Number(vc.coordinates[0]), lat:Number(vc.coordinates[1])};
    }

    const bbox = sted?.bbox || item?.bbox;
    if (Array.isArray(bbox) && bbox.length >= 4) {
      return {
        lon:(Number(bbox[0]) + Number(bbox[2])) / 2,
        lat:(Number(bbox[1]) + Number(bbox[3])) / 2
      };
    }
    return null;
  };

  const placeName = item =>
    item?.navn ||
    item?.sted?.primærtnavn ||
    item?.data?.navn ||
    item?.data?.sted?.primærtnavn ||
    'Valgt by';

  const municipalityName = item => {
    const sted = item?.sted || item?.data?.sted || item?.data || {};
    const kommuner = sted?.kommuner || [];
    return Array.isArray(kommuner) && kommuner.length ? kommuner[0]?.navn || '' : '';
  };

  const POSTCODE_API = 'https://dawa.companydata.dk';
  let postcodeCache = null;

  const reversePlaceName = async (lat, lon) => {
    // Reverse endpoint expects x=longitude, y=latitude.
    const url =
      POSTCODE_API + '/postnumre/reverse' +
      '?x=' + encodeURIComponent(lon) +
      '&y=' + encodeURIComponent(lat);

    const r = await fetch(url);
    if (!r.ok) throw new Error(`Postnummer reverse HTTP ${r.status}`);
    const item = await r.json();
    return item?.navn || 'Din position';
  };

  const loadPostcodes = async () => {
    if (postcodeCache) return postcodeCache;
    const r = await fetch(POSTCODE_API + '/postnumre?per_side=2000');
    if (!r.ok) throw new Error(`Postnummerliste HTTP ${r.status}`);
    const rows = await r.json();
    postcodeCache = Array.isArray(rows) ? rows : [];
    return postcodeCache;
  };

  const postcodeCenter = item => {
    const vc = item?.visueltcenter;
    if (Array.isArray(vc) && vc.length >= 2) {
      return {lon:Number(vc[0]), lat:Number(vc[1])};
    }
    const bbox = item?.bbox;
    if (Array.isArray(bbox) && bbox.length >= 4) {
      return {
        lon:(Number(bbox[0]) + Number(bbox[2])) / 2,
        lat:(Number(bbox[1]) + Number(bbox[3])) / 2
      };
    }
    return null;
  };

  const getPostcodeDetails = async nr => {
    const r = await fetch(POSTCODE_API + '/postnumre/' + encodeURIComponent(nr));
    if (!r.ok) throw new Error(`Postnummeropslag HTTP ${r.status}`);
    return r.json();
  };

  const normalize = value =>
    String(value || '')
      .toLocaleLowerCase('da-DK')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');

  const setupSearch = () => {
    const input = root.querySelector('[data-city-search]');
    const box = root.querySelector('[data-city-suggestions]');
    let timer = null;
    let currentSuggestions = [];
    let searchSerial = 0;

    const showSuggestions = rows => {
      currentSuggestions = rows;
      box.innerHTML = rows.map((s,i) => {
        const label = s?.navn || '';
        const nr = s?.nr ? `<span>${esc(s.nr)}</span>` : '';
        return `<button type="button" data-suggestion-index="${i}"><strong>${esc(label)}</strong>${nr}</button>`;
      }).join('');
      box.hidden = !rows.length;
    };

    input.addEventListener('input', () => {
      clearTimeout(timer);
      const q = input.value.trim();
      const serial = ++searchSerial;

      if (q.length < 2) {
        box.hidden = true;
        box.innerHTML = '';
        currentSuggestions = [];
        return;
      }

      timer = setTimeout(async () => {
        try {
          const all = await loadPostcodes();
          if (serial !== searchSerial) return;

          const nq = normalize(q);
          const starts = [];
          const contains = [];

          for (const item of all) {
            const name = normalize(item?.navn);
            if (!name) continue;
            if (name.startsWith(nq)) starts.push(item);
            else if (name.includes(nq)) contains.push(item);
          }

          const seen = new Set();
          const usable = [...starts, ...contains].filter(item => {
            const key = item.nr || item.navn;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          }).slice(0,8);

          showSuggestions(usable);
        } catch (err) {
          console.error('Bysøgning:', err);
          if (serial === searchSerial) {
            box.hidden = true;
            currentSuggestions = [];
          }
        }
      }, 180);
    });

    box.addEventListener('click', async e => {
      const btn = e.target.closest('[data-suggestion-index]');
      if (!btn) return;

      const item = currentSuggestions[Number(btn.dataset.suggestionIndex)];
      box.hidden = true;
      input.value = item?.navn || '';

      try {
        const details = await getPostcodeDetails(item.nr);
        const center = postcodeCenter(details);
        const name = details?.navn || item?.navn || 'Valgt by';

        if (!center || !Number.isFinite(center.lat) || !Number.isFinite(center.lon)) {
          throw new Error('Postnummeret har ingen brugbare koordinater');
        }

        await loadForecastForCoords(center.lat, center.lon, name);
      } catch (err) {
        console.error('Valg af by:', err);
        status('Kunne ikke hente vejrudsigten for byen.');
      }
    });

    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !box.hidden && currentSuggestions.length) {
        e.preventDefault();
        const first = box.querySelector('[data-suggestion-index="0"]');
        if (first) first.click();
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
      async pos => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        let name = 'Din position';

        try {
          name = await reversePlaceName(lat, lon);
        } catch (err) {
          console.warn('Kunne ikke finde bynavn for position:', err);
        }

        try {
          await loadForecastForCoords(lat, lon, name);
        } catch (err) {
          console.error(err);
          status('Kunne ikke hente vejr for din position. Viser Sortsø Strand.');
          loadSortsoe().catch(console.error);
        }
      },
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