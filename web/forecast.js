(() => {
  const FORECAST_FRONTEND_VERSION = '20261009-2';
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
      const humidities = vals.map(v=>v.humidity).filter(v=>v!=null);
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
        humidityAvg: humidities.length ? Math.round(humidities.reduce((a,b)=>a+b,0)/humidities.length) : null,
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

  const dayOfYear = date => {
    const start = new Date(date.getFullYear(), 0, 0);
    return Math.floor((date - start) / 86400000);
  };

  const sunTime = (dateStr, lat, lon, sunrise) => {
    const d = new Date(dateStr + 'T12:00:00');
    const N = dayOfYear(d);
    const lngHour = lon / 15;
    const t = N + (((sunrise ? 6 : 18) - lngHour) / 24);
    const M = (0.9856 * t) - 3.289;
    let L = M + (1.916 * Math.sin(M * Math.PI / 180)) + (0.020 * Math.sin(2 * M * Math.PI / 180)) + 282.634;
    L = (L + 360) % 360;
    let RA = Math.atan(0.91764 * Math.tan(L * Math.PI / 180)) * 180 / Math.PI;
    RA = (RA + 360) % 360;
    const Lquadrant = Math.floor(L / 90) * 90;
    const RAquadrant = Math.floor(RA / 90) * 90;
    RA = (RA + (Lquadrant - RAquadrant)) / 15;

    const sinDec = 0.39782 * Math.sin(L * Math.PI / 180);
    const cosDec = Math.cos(Math.asin(sinDec));
    const cosH =
      (Math.cos(90.833 * Math.PI / 180) - (sinDec * Math.sin(lat * Math.PI / 180))) /
      (cosDec * Math.cos(lat * Math.PI / 180));

    if (cosH > 1 || cosH < -1) return null;

    let H = sunrise
      ? 360 - (Math.acos(cosH) * 180 / Math.PI)
      : (Math.acos(cosH) * 180 / Math.PI);
    H /= 15;

    const T = H + RA - (0.06571 * t) - 6.622;
    let UT = T - lngHour;
    UT = (UT + 24) % 24;

    const hours = Math.floor(UT);
    const minutes = Math.floor((UT - hours) * 60);
    return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate(), hours, minutes));
  };

  const formatSunTime = date => date
    ? new Intl.DateTimeFormat('da-DK', {hour:'2-digit', minute:'2-digit'}).format(date)
    : '–';

  const dayLengthText = (rise, set) => {
    if (!rise || !set) return '';
    let ms = set.getTime() - rise.getTime();
    if (ms < 0) ms += 86400000;
    const h = Math.floor(ms / 3600000);
    const m = Math.round((ms % 3600000) / 60000);
    return `Dagen varer ${h} t. og ${m} min.`;
  };

  const waitForHighcharts = callback => {
    let tries = 0;
    const tick = () => {
      if (window.Highcharts) return callback(window.Highcharts);
      if (++tries < 30) setTimeout(tick, 200);
    };
    tick();
  };

  const renderMeteogram = (hours) => {
    if (!hours.length) return;

    waitForHighcharts(Highcharts => {
      const container = document.getElementById('forecastMeteogram');
      const windContainer = document.getElementById('forecastWindChart');
      if (!container || !windContainer) return;

      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      const textColor = isDark ? '#f8fafc' : '#334155';
      const gridColor = isDark ? 'rgba(255,255,255,.12)' : 'rgba(15,23,42,.12)';
      const bg = 'transparent';

      const tempData = hours.map(h => [Date.parse(h.time), Number(h.temperature)]);
      const rainData = hours.map(h => [Date.parse(h.time), Number(h.rainMm || 0)]);
      const windData = hours.map(h => [Date.parse(h.time), Number(h.wind || 0)]);

      const plotLines = [];
      let lastDate = null;
      hours.forEach(h => {
        const d = new Date(h.time);
        const key = d.toDateString();
        if (lastDate && key !== lastDate) {
          plotLines.push({
            value: d.setHours(0,0,0,0),
            width: 1,
            color: gridColor,
            zIndex: 2,
            label: {
              text: new Intl.DateTimeFormat('da-DK', {weekday:'long', day:'numeric', month:'short'}).format(d),
              rotation:0,
              x:6,
              y:14,
              style:{color:textColor,fontSize:'11px'}
            }
          });
        }
        lastDate = key;
      });

      const chart = Highcharts.chart(container, {
        chart:{backgroundColor:bg,height:390,marginTop:72},
        title:{text:null},
        credits:{enabled:false},
        xAxis:{
          type:'datetime',
          tickInterval:3*3600*1000,
          plotLines,
          labels:{
            format:'{value:%H}',
            style:{color:textColor,fontSize:'11px'}
          },
          gridLineWidth:1,
          gridLineColor:gridColor,
          lineColor:gridColor
        },
        yAxis:[{
          title:{text:'°C',rotation:0,align:'high',y:-18,style:{color:textColor}},
          labels:{style:{color:textColor}},
          gridLineColor:gridColor
        },{
          title:{text:'mm',rotation:0,align:'high',y:-18,style:{color:textColor}},
          labels:{style:{color:textColor}},
          opposite:true,
          min:0,
          gridLineWidth:0
        }],
        legend:{
          align:'left',
          verticalAlign:'bottom',
          itemStyle:{color:textColor}
        },
        tooltip:{
          shared:true,
          xDateFormat:'%A %e. %b kl. %H:%M'
        },
        series:[{
          name:'Temperatur',
          type:'spline',
          data:tempData,
          lineWidth:2,
          marker:{enabled:false},
          tooltip:{valueSuffix:' °C'},
          yAxis:0,
          zIndex:2
        },{
          name:'Nedbør',
          type:'column',
          data:rainData,
          maxPointWidth:22,
          borderWidth:0,
          tooltip:{valueSuffix:' mm'},
          yAxis:1,
          zIndex:1
        }]
      }, chart => {
        const sampleEvery = 2;
        hours.forEach((h,i) => {
          if (i % sampleEvery !== 0) return;
          const x = chart.xAxis[0].toPixels(Date.parse(h.time));
          const html = '<div class="forecast-chart-weather-icon">' + svg(h.weather, h.time) + '</div>';
          chart.renderer.label(html, x - 19, chart.plotTop - 56, null, null, null, true)
            .attr({zIndex:7})
            .add();
        });
      });

      Highcharts.chart(windContainer, {
        chart:{backgroundColor:bg,height:220},
        title:{text:null},
        credits:{enabled:false},
        xAxis:{
          type:'datetime',
          tickInterval:3*3600*1000,
          labels:{format:'{value:%H}',style:{color:textColor,fontSize:'11px'}},
          gridLineWidth:1,
          gridLineColor:gridColor,
          lineColor:gridColor
        },
        yAxis:{
          title:{text:'m/s',rotation:0,align:'high',y:-12,style:{color:textColor}},
          labels:{style:{color:textColor}},
          min:0,
          gridLineColor:gridColor
        },
        legend:{enabled:false},
        tooltip:{xDateFormat:'%A %e. %b kl. %H:%M',valueSuffix:' m/s'},
        series:[{
          name:'Vind',
          type:'spline',
          data:windData,
          lineWidth:2,
          marker:{enabled:false}
        }]
      });

      window.__forecastCharts = [chart];
    });
  };

  const render = data => {
    const content = root.querySelector('[data-forecast-content]');
    if (!content) return;

    const now = Date.now();
    const hours = (data.hours || []).filter(h => {
      const t = Date.parse(h.time);
      return Number.isFinite(t) && t > now;
    });
    const days = summarizeDays(hours);
    const current = hours[0] || {};
    const lat = Number(data.location?.latitude);
    const lon = Number(data.location?.longitude);

    const dayName = date => new Intl.DateTimeFormat('da-DK', {weekday:'long'}).format(new Date(date + 'T12:00:00'));
    const dayDate = date => new Intl.DateTimeFormat('da-DK', {day:'2-digit', month:'short'}).format(new Date(date + 'T12:00:00'));
    const hoursForDay = date => hours.filter(h => h.time.slice(0,10) === date);

    const nextRain = Number(current.rainMm || 0);
    const rainNotice = nextRain >= 0.1
      ? `<div class="forecast-rain-notice"><span class="forecast-rain-drop" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 2C9 7 6 10.5 6 15a6 6 0 0 0 12 0c0-4.5-3-8-6-13Z"/></svg></span>Der forventes <strong>${nextRain.toFixed(1)} mm</strong> nedbør frem mod kl. ${fmtHour(current.time)}.</div>`
      : '';

    content.innerHTML = `
      <div class="forecast-head">
        <div>
          <h2>Vejrudsigt for ${esc(data.location?.name || state.selectedName)}</h2>
        </div>
        <div class="forecast-updated">Opdateret ${data.source?.generated ? fmtGenerated(data.source.generated) : '–'}</div>
      </div>

      <section class="forecast-current forecast-current--met">
        <div class="forecast-current-main">
          <div class="forecast-current-icon">${svg(current.weather, current.time)}</div>
          <div class="forecast-current-reading">
            <div class="forecast-current-temp">${current.temperature == null ? '–' : Number(current.temperature).toFixed(1) + '°'}</div>
            <div class="forecast-current-label">${esc(current.weatherLabel || '')}</div>
            <div class="forecast-current-time">${current.time ? 'Prognose kl. ' + fmtHour(current.time) : ''}</div>
          </div>
        </div>

        <div class="forecast-current-facts">
          <span><b>Vind</b> ${current.wind == null ? '–' : Number(current.wind).toFixed(1) + ' m/s'} ${esc(current.windDirectionText || '')}</span>
          <span><b>Lufttryk</b> ${current.pressure == null ? '–' : Number(current.pressure).toFixed(1) + ' hPa'}</span>
          <span><b>Nedbør</b> ${current.rainMm == null ? '–' : Number(current.rainMm).toFixed(1) + ' mm'}</span>
          <span><b>Luftfugtighed</b> ${current.humidity == null ? '–' : Math.round(current.humidity) + '%'}</span>
        </div>
      </section>

      ${rainNotice}

      <section class="forecast-meteogram-card">
        <div class="forecast-chart-tabs">
          <span class="active">Meteogram – de næste 3 døgn</span>
        </div>
        <div id="forecastMeteogram" class="forecast-meteogram"></div>
        <div class="forecast-wind-heading">Vind</div>
        <div id="forecastWindChart" class="forecast-wind-chart"></div>
      </section>

      <section class="forecast-days-detail">
        <h3>Detaljeret dagsoversigt</h3>

        <div class="forecast-day-list">
          ${days.map((d, dayIndex) => {
            const dh = hoursForDay(d.date);
            const rise = Number.isFinite(lat) && Number.isFinite(lon) ? sunTime(d.date, lat, lon, true) : null;
            const set = Number.isFinite(lat) && Number.isFinite(lon) ? sunTime(d.date, lat, lon, false) : null;
            return `
              <article class="forecast-day-row ${dayIndex === 0 ? 'is-open' : ''}" data-day-row>
                <button type="button" class="forecast-day-summary" data-day-toggle aria-expanded="${dayIndex === 0 ? 'true' : 'false'}">
                  <span class="forecast-day-date">
                    <strong>${esc(dayName(d.date))}</strong>
                    <small>${esc(dayDate(d.date))}</small>
                  </span>

                  <span class="forecast-day-symbol">${svg(d.weather, d.date + 'T12:00:00')}</span>

                  <span class="forecast-day-range">
                    <strong>${d.temperatureMin == null ? '–' : Number(d.temperatureMin).toFixed(1) + '°'} / ${d.temperatureMax == null ? '–' : Number(d.temperatureMax).toFixed(1) + '°'}</strong>
                  </span>

                  <span class="forecast-day-metric">
                    <small>NEDBØR</small>
                    <strong>${d.rainMm == null ? '–' : Number(d.rainMm).toFixed(1) + ' mm'}</strong>
                  </span>

                  <span class="forecast-day-metric">
                    <small>VIND</small>
                    <strong>${d.windAvg == null ? '–' : Number(d.windAvg).toFixed(1) + ' m/s'} ${esc(d.windDirectionText || '')}</strong>
                  </span>

                  <span class="forecast-day-metric">
                    <small>LUFTFUGTIGHED</small>
                    <strong>${d.humidityAvg == null ? '–' : d.humidityAvg + '%'}</strong>
                  </span>

                  <span class="forecast-day-chevron" aria-hidden="true"></span>
                </button>

                <div class="forecast-day-hours" ${dayIndex === 0 ? '' : 'hidden'}>
                  <div class="forecast-sun-info">
                    <span class="forecast-sunrise"><span class="forecast-sun-mark forecast-sunrise-mark" aria-hidden="true"></span>${formatSunTime(rise)}</span>
                    <span class="forecast-sunset"><span class="forecast-sun-mark forecast-sunset-mark" aria-hidden="true"></span>${formatSunTime(set)}</span>
                    <span>${esc(dayLengthText(rise,set))}</span>
                  </div>
                  <div class="forecast-hours-table-wrap">
                    <table class="forecast-hours-table">
                      <thead>
                        <tr>
                          <th>Tid</th>
                          <th>Vejr</th>
                          <th>Temperatur</th>
                          <th>Nedbør</th>
                          <th>Vind</th>
                          <th>Luftfugtighed</th>
                        </tr>
                      </thead>
                      <tbody>
                        ${dh.map(h => `
                          <tr>
                            <td>${fmtHour(h.time)}</td>
                            <td><span class="forecast-table-icon">${svg(h.weather, h.time)}</span></td>
                            <td>${h.temperature == null ? '–' : Number(h.temperature).toFixed(1) + '°'}</td>
                            <td>${h.rainMm == null ? '–' : Number(h.rainMm).toFixed(1) + ' mm'}</td>
                            <td>
                              ${h.wind == null ? '–' : Number(h.wind).toFixed(1) + ' m/s'}
                              ${h.windDirectionText ? '<small>' + esc(h.windDirectionText) + '</small>' : ''}
                            </td>
                            <td>${h.humidity == null ? '–' : Math.round(h.humidity) + '%'}</td>
                          </tr>
                        `).join('')}
                      </tbody>
                    </table>
                  </div>
                </div>
              </article>
            `;
          }).join('')}
        </div>
      </section>
    `;

    content.querySelectorAll('[data-day-toggle]').forEach(btn => {
      btn.addEventListener('click', () => {
        const row = btn.closest('[data-day-row]');
        const details = row?.querySelector('.forecast-day-hours');
        if (!row || !details) return;

        const isOpen = row.classList.toggle('is-open');
        btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        details.hidden = !isOpen;
      });
    });

    renderMeteogram(hours);
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

  const GEONAMES_USER = 'sorenknudsen';
  const GEONAMES_BASE = 'https://secure.geonames.org';
  const POSTCODE_API = 'https://dawa.companydata.dk';

  const postcodeReverseFallback = async (lat, lon) => {
    const url =
      POSTCODE_API + '/postnumre/reverse' +
      '?x=' + encodeURIComponent(lon) +
      '&y=' + encodeURIComponent(lat);
    const r = await fetch(url);
    if (!r.ok) throw new Error(`Postnummer reverse HTTP ${r.status}`);
    const item = await r.json();
    return item?.navn || 'Din position';
  };

  const reversePlaceName = async (lat, lon) => {
    const params = new URLSearchParams({
      lat:String(lat),
      lng:String(lon),
      username:GEONAMES_USER,
      country:'DK',
      radius:'20',
      maxRows:'10'
    });

    const r = await fetch(GEONAMES_BASE + '/findNearbyPlaceNameJSON?' + params.toString());
    if (!r.ok) throw new Error(`GeoNames reverse HTTP ${r.status}`);
    const data = await r.json();

    if (data?.status) {
      throw new Error(`GeoNames: ${data.status.message || data.status.value}`);
    }

    const places = Array.isArray(data?.geonames) ? data.geonames : [];
    if (places.length) {
      const best = places
        .filter(p => p?.name && Number.isFinite(Number(p?.lat)) && Number.isFinite(Number(p?.lng)))
        .sort((a,b) => Number(a.distance ?? 9999) - Number(b.distance ?? 9999))[0];
      if (best?.name) return best.name;
    }

    return postcodeReverseFallback(lat, lon);
  };

  const searchPlaces = async query => {
    const params = new URLSearchParams({
      name_startsWith:query,
      username:GEONAMES_USER,
      country:'DK',
      featureClass:'P',
      maxRows:'12',
      style:'FULL',
      orderby:'relevance'
    });

    const r = await fetch(GEONAMES_BASE + '/searchJSON?' + params.toString());
    if (!r.ok) throw new Error(`GeoNames search HTTP ${r.status}`);
    const data = await r.json();

    if (data?.status) {
      throw new Error(`GeoNames: ${data.status.message || data.status.value}`);
    }

    return (Array.isArray(data?.geonames) ? data.geonames : [])
      .filter(p => p?.name && Number.isFinite(Number(p?.lat)) && Number.isFinite(Number(p?.lng)));
  };

  const setupSearch = () => {
    const input = root.querySelector('[data-city-search]');
    const box = root.querySelector('[data-city-suggestions]');
    let timer = null;
    let currentSuggestions = [];
    let searchSerial = 0;

    const showSuggestions = rows => {
      currentSuggestions = rows;
      box.innerHTML = rows.map((p,i) => {
        const name = p?.name || '';
        return `<button type="button" data-suggestion-index="${i}"><strong>${esc(name)}</strong></button>`;
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
          const rows = await searchPlaces(q);
          if (serial !== searchSerial) return;
          showSuggestions(rows.slice(0,8));
        } catch (err) {
          console.error('Bysøgning:', err);
          if (serial === searchSerial) {
            box.hidden = true;
            currentSuggestions = [];
          }
        }
      }, 220);
    });

    box.addEventListener('click', async e => {
      const btn = e.target.closest('[data-suggestion-index]');
      if (!btn) return;

      const place = currentSuggestions[Number(btn.dataset.suggestionIndex)];
      box.hidden = true;
      input.value = place?.name || '';

      const lat = Number(place?.lat);
      const lon = Number(place?.lng);
      const name = place?.name || 'Valgt sted';

      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
        status('Kunne ikke finde koordinater for stedet.');
        return;
      }

      try {
        await loadForecastForCoords(lat, lon, name);
      } catch (err) {
        console.error('Valg af sted:', err);
        status('Kunne ikke hente vejrudsigten for stedet.');
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
          console.warn('Kunne ikke finde stednavn for position:', err);
          try {
            name = await postcodeReverseFallback(lat, lon);
          } catch (fallbackErr) {
            console.warn('Kunne heller ikke finde postnummernavn:', fallbackErr);
          }
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