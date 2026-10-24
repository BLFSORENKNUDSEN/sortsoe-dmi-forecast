(() => {
  const el = document.querySelector('[data-wind-alert]');
  if (!el) return;

  const DATA_URL = window.STRANDVEJR_WIND_ALERT_URL ||
    'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/data/sortsoe.json';

  const fmt = value => value == null ? null : Number(value).toLocaleString('da-DK', {
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

  fetch(DATA_URL + '?v=' + Date.now(), {cache:'no-store'})
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(data => {
      const alert = data?.windAlert;
      if (!alert?.active) {
        el.hidden = true;
        return;
      }

      const parts = [];
      if (alert.maxWindMs != null) {
        parts.push(`middelvind op til <strong>${fmt(alert.maxWindMs)} m/s</strong>`);
      }
      if (alert.maxGustMs != null) {
        parts.push(`vindstød op til <strong>${fmt(alert.maxGustMs)} m/s</strong>`);
      }

      const first = fmtTime(alert.firstTime);
      const detail = parts.length
        ? `Prognosen viser ${parts.join(' og ')}.`
        : 'Prognosen viser kraftig vind.';
      const when = first ? ` Første overskridelse ventes ${first}.` : '';

      el.innerHTML = `
        <div class="sv-wind-alert__icon" aria-hidden="true">
          <svg viewBox="0 0 40 40">
            <path d="M4 14h20c4.5 0 7-2.2 7-5.5S28.5 3 25.5 3c-2.2 0-4.1 1.2-5.1 3"/>
            <path d="M4 21h27c3.6 0 5.5 1.8 5.5 4.5S34.5 30 32 30c-1.8 0-3.2-.8-4-2"/>
            <path d="M4 28h15"/>
          </svg>
        </div>
        <div class="sv-wind-alert__content">
          <strong class="sv-wind-alert__title">Varsel om kraftig vind</strong>
          <div class="sv-wind-alert__text">${detail}${when}</div>
        </div>
      `;
      el.hidden = false;
    })
    .catch(err => {
      console.error('Wind alert:', err);
      el.hidden = true;
    });
})();