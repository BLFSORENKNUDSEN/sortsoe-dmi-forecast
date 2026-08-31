(() => {
  const DATA_URL = window.SORTSOE_FORECAST_URL || './data/sortsoe.json';
  const root = document.querySelector('[data-sortsoe-forecast]');
  if (!root) return;

  const icon = (code) => ({
    clear: '☀️', partly_cloudy: '🌤️', cloudy: '☁️', overcast: '☁️',
    light_rain: '🌦️', rain: '🌧️', heavy_rain: '🌧️', thunder: '⛈️',
    snow: '🌨️', sleet: '🌨️', freezing_rain: '🌧️'
  }[code] || '🌤️');

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtHour = iso => new Intl.DateTimeFormat('da-DK', {hour:'2-digit', minute:'2-digit'}).format(new Date(iso));
  const fmtDay = iso => new Intl.DateTimeFormat('da-DK', {weekday:'long', day:'numeric', month:'short'}).format(new Date(`${iso}T12:00:00`));

  fetch(`${DATA_URL}?v=${Date.now()}`, {cache: 'no-store'})
    .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(data => {
      const hours = (data.hours || []).slice(0, 24);
      const days = data.days || [];
      root.innerHTML = `
        <section class="forecast-block">
          <div class="forecast-head">
            <div><strong>Vejrudsigt for ${esc(data.location?.name || 'Sortsø Strand')}</strong></div>
            <div class="forecast-source">DMI HARMONIE</div>
          </div>
          <div class="forecast-hours">
            ${hours.map(h => `
              <article class="forecast-hour">
                <div>${fmtHour(h.time)}</div>
                <div class="forecast-icon">${icon(h.weather)}</div>
                <div class="forecast-temp">${h.temperature == null ? '–' : Math.round(h.temperature) + '°'}</div>
                <div>${esc(h.weatherLabel)}</div>
                <div>💧 ${h.rainMmH == null ? '–' : h.rainMmH.toFixed(1)} mm</div>
                <div>💨 ${h.wind == null ? '–' : h.wind.toFixed(1)} m/s ${esc(h.windDirectionText || '')}</div>
              </article>`).join('')}
          </div>
          <div class="forecast-days">
            ${days.map(d => `
              <article class="forecast-day">
                <div class="forecast-day-name">${fmtDay(d.date)}</div>
                <div class="forecast-icon">${icon(d.weather)}</div>
                <div><strong>${d.temperatureMax == null ? '–' : Math.round(d.temperatureMax) + '°'}</strong> / ${d.temperatureMin == null ? '–' : Math.round(d.temperatureMin) + '°'}</div>
                <div>${esc(d.weatherLabel)}</div>
                <div>💧 ${d.rainMm ?? 0} mm</div>
                <div>💨 ${d.windAvg == null ? '–' : d.windAvg.toFixed(1)} m/s ${esc(d.windDirectionText || '')}</div>
              </article>`).join('')}
          </div>
          <p class="forecast-summary">${esc(days[0]?.summary || '')}</p>
        </section>`;
    })
    .catch(err => {
      root.innerHTML = `<p>Vejrudsigten kunne ikke hentes lige nu.</p>`;
      console.error('Sortsø forecast:', err);
    });
})();
