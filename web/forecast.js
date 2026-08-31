(() => {
  const DATA_URL = window.SORTSOE_FORECAST_URL || 'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/data/sortsoe.json';
  const root = document.querySelector('[data-sortsoe-forecast]');
  if (!root) return;

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtHour = iso => new Intl.DateTimeFormat('da-DK', {hour:'2-digit', minute:'2-digit'}).format(new Date(iso));
  const fmtDayShort = iso => new Intl.DateTimeFormat('da-DK', {weekday:'short'}).format(new Date(iso));
  const fmtDay = iso => new Intl.DateTimeFormat('da-DK', {weekday:'long', day:'numeric', month:'short'}).format(new Date(`${iso}T12:00:00`));
  const fmtGenerated = iso => new Intl.DateTimeFormat('da-DK', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}).format(new Date(iso));

  const icon = (code, time) => {
    const hour = new Date(time).getHours();
    const night = hour < 6 || hour >= 21;
    const map = {
      clear: night ? '🌙' : '☀️',
      partly_cloudy: night ? '☁️' : '🌤️',
      cloudy: '☁️',
      overcast: '☁️',
      light_rain: '🌦️',
      rain: '🌧️',
      heavy_rain: '🌧️'
    };
    return map[code] || '🌤️';
  };

  const weatherText = data => {
    const days = data.days || [];
    if (!days.length) return '';
    const first = days[0];
    const second = days[1];
    let text = first.summary || '';
    if (second) text += ` I morgen: ${second.summary}`;
    return text;
  };

  fetch(`${DATA_URL}?v=${Date.now()}`, {cache: 'no-store'})
    .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(data => {
      const hours = data.hours || [];
      const days = data.days || [];
      const current = hours[0] || data.currentForecast || {};
      root.innerHTML = `
        <section class="forecast-block">
          <div class="forecast-head">
            <div>
              <div class="forecast-kicker">DMI HARMONIE</div>
              <h2>Vejrudsigt for ${esc(data.location?.name || 'Sortsø Strand')}</h2>
            </div>
            <div class="forecast-updated">Opdateret ${data.source?.generated ? fmtGenerated(data.source.generated) : '–'}</div>
          </div>

          <div class="forecast-current">
            <div class="forecast-current-icon">${icon(current.weather, current.time)}</div>
            <div>
              <div class="forecast-current-temp">${current.temperature == null ? '–' : Math.round(current.temperature) + '°'}</div>
              <div class="forecast-current-label">${esc(current.weatherLabel || '')}</div>
            </div>
            <div class="forecast-current-facts">
              <span>Vind <strong>${current.wind == null ? '–' : current.wind.toFixed(1)} m/s ${esc(current.windDirectionText || '')}</strong></span>
              ${current.gust == null ? '' : `<span>Vindstød <strong>${current.gust.toFixed(1)} m/s</strong></span>`}
              <span>Nedbør <strong>${current.rainMm == null ? '–' : current.rainMm.toFixed(1)} mm</strong></span>
              <span>Skydække <strong>${current.cloudCover == null ? '–' : current.cloudCover + '%'}</strong></span>
            </div>
          </div>

          <div class="forecast-text">${esc(weatherText(data))}</div>

          <h3>De kommende 60 timer</h3>
          <div class="forecast-hours">
            ${hours.map((h, i) => `
              <article class="forecast-hour">
                <div class="forecast-hour-day">${i === 0 || new Date(h.time).getDate() !== new Date(hours[i-1]?.time || h.time).getDate() ? esc(fmtDayShort(h.time)) : ''}</div>
                <div class="forecast-hour-time">${fmtHour(h.time)}</div>
                <div class="forecast-icon">${icon(h.weather, h.time)}</div>
                <div class="forecast-temp">${h.temperature == null ? '–' : Math.round(h.temperature) + '°'}</div>
                <div class="forecast-hour-label">${esc(h.weatherLabel)}</div>
                <div class="forecast-rain">💧 ${h.rainMm == null ? '–' : h.rainMm.toFixed(1)} mm</div>
                <div class="forecast-wind">💨 ${h.wind == null ? '–' : h.wind.toFixed(1)} m/s ${esc(h.windDirectionText || '')}</div>
              </article>`).join('')}
          </div>

          <h3>Døgnoversigt</h3>
          <div class="forecast-days">
            ${days.map(d => `
              <article class="forecast-day">
                <div class="forecast-day-name">${fmtDay(d.date)}</div>
                <div class="forecast-icon">${icon(d.weather, `${d.date}T12:00:00`)}</div>
                <div class="forecast-day-temp"><strong>${d.temperatureMax == null ? '–' : Math.round(d.temperatureMax) + '°'}</strong> / ${d.temperatureMin == null ? '–' : Math.round(d.temperatureMin) + '°'}</div>
                <div>${esc(d.weatherLabel)}</div>
                <div>💧 ${d.rainMm == null ? '–' : d.rainMm.toFixed(1)} mm</div>
                <div>💨 ${d.windAvg == null ? '–' : d.windAvg.toFixed(1)} m/s ${esc(d.windDirectionText || '')}</div>
              </article>`).join('')}
          </div>

          <div class="forecast-meta">Modelkørsel: ${esc(data.source?.modelRun || '–')} · modelpunkt ${data.location?.modelPoint?.distanceKm == null ? '–' : data.location.modelPoint.distanceKm.toFixed(1)} km fra Sortsø Strand</div>
        </section>`;
    })
    .catch(err => {
      root.innerHTML = `<div class="forecast-error">Vejrudsigten kunne ikke hentes lige nu.</div>`;
      console.error('Sortsø forecast:', err);
    });
})();
