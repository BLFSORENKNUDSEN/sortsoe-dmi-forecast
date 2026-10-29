(() => {
  const root = document.querySelector('[data-winter-outlook]');
  if (!root) return;

  const BASE = window.STRANDVEJR_WINTER_BASE ||
    'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/gfs/winter_output';
  const MANIFEST_URL = BASE + '/winter_manifest.json';

  const state = {
    manifest: null,
    layer: 'temperature_2m',
    index: 0,
    timer: null
  };

  const layerLabels = {
    temperature_2m: 'Temperatur 2 m',
    temperature_850: 'Temperatur 850 hPa',
    precip_type: 'Nedbørstype',
    snow_depth: 'Snedybde'
  };

  const fmtValid = iso => new Intl.DateTimeFormat('da-DK', {
    weekday:'short',
    day:'numeric',
    month:'short',
    hour:'2-digit',
    minute:'2-digit',
    timeZone:'Europe/Copenhagen'
  }).format(new Date(iso));

  const fmtRun = iso => new Intl.DateTimeFormat('da-DK', {
    day:'numeric',
    month:'short',
    hour:'2-digit',
    minute:'2-digit',
    timeZone:'Europe/Copenhagen'
  }).format(new Date(iso));

  const products = () => state.manifest?.layers?.[state.layer]?.products || [];

  const stop = () => {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
    const btn = root.querySelector('[data-play]');
    if (btn) btn.textContent = '▶';
  };

  const renderFrame = () => {
    const list = products();
    if (!list.length) return;
    state.index = Math.max(0, Math.min(state.index, list.length - 1));
    const item = list[state.index];

    const img = root.querySelector('[data-map]');
    const slider = root.querySelector('[data-slider]');
    const label = root.querySelector('[data-valid]');
    const step = root.querySelector('[data-step]');
    const uncertainty = root.querySelector('[data-uncertainty]');

    img.src = BASE + '/' + item.file + '?v=' + encodeURIComponent(state.manifest.generated_utc || '');
    img.alt = layerLabels[state.layer] + ' – ' + fmtValid(item.valid_utc);
    slider.max = Math.max(0, list.length - 1);
    slider.value = state.index;
    label.textContent = fmtValid(item.valid_utc);
    step.textContent = '+' + item.step_hours + ' timer';

    if (item.step_hours <= 120) {
      uncertainty.textContent = 'Kort sigt · 6-timers intervaller';
    } else if (item.step_hours <= 240) {
      uncertainty.textContent = 'Mellemlang sigt · stigende usikkerhed';
    } else {
      uncertainty.textContent = 'Lang sigt · betydelig usikkerhed';
    }
  };

  const setLayer = layer => {
    stop();
    state.layer = layer;
    state.index = 0;
    root.querySelectorAll('[data-layer]').forEach(btn => {
      const active = btn.dataset.layer === layer;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    renderFrame();
  };

  const build = () => {
    root.innerHTML = `
      <div class="winter-tabs">
        ${Object.entries(layerLabels).map(([key,label]) =>
          `<button type="button" data-layer="${key}" aria-pressed="${key === state.layer}">${label}</button>`
        ).join('')}
      </div>

      <div class="winter-map-shell">
        <div class="winter-map-meta">
          <div>
            <strong data-valid>–</strong>
            <span data-step>–</span>
          </div>
          <span data-uncertainty>–</span>
        </div>

        <div class="winter-map-stage">
          <img data-map alt="" loading="eager">
        </div>

        <div class="winter-controls">
          <button type="button" data-prev aria-label="Forrige tidspunkt">◀</button>
          <button type="button" data-play aria-label="Afspil prognosen">▶</button>
          <button type="button" data-next aria-label="Næste tidspunkt">▶|</button>
          <input type="range" min="0" value="0" step="1" data-slider aria-label="Prognosetidspunkt">
        </div>
      </div>

      <div class="winter-source">
        NOAA GFS 0,25° · modelkørsel <span data-run>–</span>.
        Kortene viser modelberegninger. Usikkerheden vokser markant længere frem i prognosen.
      </div>
    `;

    root.querySelector('[data-run]').textContent = fmtRun(state.manifest.run_utc);

    root.querySelectorAll('[data-layer]').forEach(btn => {
      btn.addEventListener('click', () => setLayer(btn.dataset.layer));
    });

    root.querySelector('[data-slider]').addEventListener('input', e => {
      stop();
      state.index = Number(e.target.value);
      renderFrame();
    });

    root.querySelector('[data-prev]').addEventListener('click', () => {
      stop();
      const list = products();
      state.index = (state.index - 1 + list.length) % list.length;
      renderFrame();
    });

    root.querySelector('[data-next]').addEventListener('click', () => {
      stop();
      const list = products();
      state.index = (state.index + 1) % list.length;
      renderFrame();
    });

    root.querySelector('[data-play]').addEventListener('click', e => {
      if (state.timer) {
        stop();
        return;
      }
      e.currentTarget.textContent = '❚❚';
      state.timer = setInterval(() => {
        const list = products();
        state.index = (state.index + 1) % list.length;
        renderFrame();
      }, 850);
    });

    setLayer(state.layer);
  };

  root.innerHTML = '<div class="winter-loading">Henter vinterudsigten…</div>';

  fetch(MANIFEST_URL + '?v=' + Date.now(), {cache:'no-store'})
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(data => {
      state.manifest = data;
      build();
    })
    .catch(err => {
      console.error('Winter outlook:', err);
      root.innerHTML = '<div class="winter-error">Vinterudsigten kan ikke hentes lige nu.</div>';
    });
})();