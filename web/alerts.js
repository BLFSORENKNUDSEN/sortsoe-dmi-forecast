(() => {
  const section = document.querySelector('[data-weather-alerts]');
  if (!section) return;

  const WIND_URL = window.STRANDVEJR_WIND_ALERT_URL ||
    'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/data/sortsoe.json';

  const WATER_URL = window.STRANDVEJR_WATER_ALERT_URL ||
    'https://raw.githubusercontent.com/BLFSORENKNUDSEN/Vandstand/main/data/waterlevel-tiles/metadata.json';

  const fmt1 = value => value == null ? null : Number(value).toLocaleString('da-DK', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  });

  const fmtTime = iso => {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return new Intl.DateTimeFormat('da-DK', {
      weekday:'long',
      day:'numeric',
      month:'short',
      hour:'2-digit',
      minute:'2-digit',
      timeZone:'Europe/Copenhagen'
    }).format(d);
  };

  const windCard = alert => {
    if (!alert?.active) return '';

    const bits = [];
    if (alert.maxWindMs != null) {
      bits.push(`middelvind op til <strong>${fmt1(alert.maxWindMs)} m/s</strong>`);
    }
    if (alert.maxGustMs != null) {
      bits.push(`vindstød op til <strong>${fmt1(alert.maxGustMs)} m/s</strong>`);
    }

    const first = fmtTime(alert.firstTime);
    const when = first ? ` Første overskridelse ventes ${first}.` : '';

    return `
      <article class="sv-alert-card sv-alert-card--wind">
        <div class="sv-alert-card__icon" aria-hidden="true">
          <svg viewBox="0 0 40 40">
            <path d="M4 14h20c4.5 0 7-2.2 7-5.5S28.5 3 25.5 3c-2.2 0-4.1 1.2-5.1 3"/>
            <path d="M4 21h27c3.6 0 5.5 1.8 5.5 4.5S34.5 30 32 30c-1.8 0-3.2-.8-4-2"/>
            <path d="M4 28h15"/>
          </svg>
        </div>
        <div class="sv-alert-card__content">
          <strong class="sv-alert-card__title">Varsel om kraftig vind</strong>
          <div class="sv-alert-card__text">
            Prognosen viser ${bits.join(' og ')}.${when}
          </div>
        </div>
      </article>
    `;
  };

  const waterCard = metadata => {
    if (!metadata) return '';

    const local = Array.isArray(metadata.localForecasts)
      ? metadata.localForecasts.find(item => item.id === 'sortsoe_groensund')
      : null;

    const alert = local?.alert || metadata.highWaterAlert;
    if (!alert?.active || alert.peakCm == null || !alert.peakTime) return '';

    const place = local?.name || 'de danske farvande';
    const peak = Math.round(Number(alert.peakCm));
    const time = fmtTime(alert.peakTime);

    return `
      <article class="sv-alert-card sv-alert-card--water">
        <div class="sv-alert-card__icon" aria-hidden="true">
          <svg viewBox="0 0 40 40">
            <path d="M3 14c4-3 8-3 12 0s8 3 12 0 8-3 10-1"/>
            <path d="M3 22c4-3 8-3 12 0s8 3 12 0 8-3 10-1"/>
            <path d="M3 30c4-3 8-3 12 0s8 3 12 0 8-3 10-1"/>
          </svg>
        </div>
        <div class="sv-alert-card__content">
          <strong class="sv-alert-card__title">Varsel om høj vandstand</strong>
          <div class="sv-alert-card__text">
            ${place}: Prognosen viser op til <strong>${peak} cm</strong> over daglig vande. Vandstanden ventes at toppe ${time}.
          </div>
        </div>
      </article>
    `;
  };

  Promise.all([
    fetch(WIND_URL + '?v=' + Date.now(), {cache:'no-store'}).then(r => {
      if (!r.ok) throw new Error('Wind HTTP ' + r.status);
      return r.json();
    }),
    fetch(WATER_URL + '?v=' + Date.now(), {cache:'no-store'}).then(r => {
      if (!r.ok) throw new Error('Water HTTP ' + r.status);
      return r.json();
    })
  ])
    .then(([windData, waterData]) => {
      const cards = [
        waterCard(waterData),
        windCard(windData?.windAlert)
      ].filter(Boolean);

      if (!cards.length) {
        section.hidden = true;
        return;
      }

      section.innerHTML = `
        <div class="sv-alerts__head">
          <h2>Varsler</h2>
        </div>
        <div class="sv-alerts__list">
          ${cards.join('')}
        </div>
      `;
      section.hidden = false;
    })
    .catch(err => {
      console.error('Weather alerts:', err);
      section.hidden = true;
    });
})();