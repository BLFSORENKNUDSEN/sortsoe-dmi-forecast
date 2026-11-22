(() => {
  const root = document.querySelector('[data-winter-outlook]');
  if (!root) return;

  const GFS_BASE = window.STRANDVEJR_WINTER_BASE ||
    'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/gfs/winter_output';

  const DMI_SNOW_BASE = window.STRANDVEJR_DMI_SNOW_BASE ||
    'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/data/dmi_snow';

  const state = {
    gfs: null,
    dmiSnow: null,
    layer: 'temperature_2m',
    index: 0,
    timer: null
  };

  const layerConfigs = {
    temperature_2m: {
      label: 'Temperatur 2 m',
      source: 'gfs'
    },
    temperature_850: {
      label: 'Temperatur 850 hPa',
      source: 'gfs'
    },
    precip_type: {
      label: 'Nedbørstype',
      source: 'gfs'
    },
    dmi_snow_depth: {
      label: 'Snedybde DMI',
      source: 'dmi'
    }
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

  const activeConfig = () => layerConfigs[state.layer];

  const activeManifest = () => {
    const cfg = activeConfig();
    return cfg.source === 'dmi' ? state.dmiSnow : state.gfs;
  };

  const products = () => {
    const cfg = activeConfig();

    if (cfg.source === 'dmi') {
      return state.dmiSnow?.products || [];
    }

    return state.gfs?.layers?.[state.layer]?.products || [];
  };

  const imageBase = () => activeConfig().source === 'dmi' ? DMI_SNOW_BASE : GFS_BASE;

  const stop = () => {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
    const btn = root.querySelector('[data-play]');
    if (btn) btn.textContent = '▶';
  };

  const renderSource = () => {
    const source = root.querySelector('[data-source]');
    if (!source) return;

    const cfg = activeConfig();
    const manifest = activeManifest();

    if (!manifest) {
      source.textContent = '';
      return;
    }

    if (cfg.source === 'dmi') {
      source.innerHTML =
        'DMI HARMONIE DINI · modelkørsel <strong>' +
        fmtRun(manifest.run_utc) +
        '</strong>. Højopløst korttidsprognose for snedybde.';
    } else {
      source.innerHTML =
        'NOAA GFS 0,25° · modelkørsel <strong>' +
        fmtRun(manifest.run_utc) +
        '</strong>. Usikkerheden vokser markant længere frem i prognosen.';
    }
  };

  const renderFrame = () => {
    const list = products();
    if (!list.length) return;

    state.index = Math.max(0, Math.min(state.index, list.length - 1));
    const item = list[state.index];
    const manifest = activeManifest();
    const cfg = activeConfig();

    const img = root.querySelector('[data-map]');
    const slider = root.querySelector('[data-slider]');
    const label = root.querySelector('[data-valid]');
    const step = root.querySelector('[data-step]');
    const uncertainty = root.querySelector('[data-uncertainty]');

    img.src =
      imageBase() + '/' + item.file +
      '?v=' + encodeURIComponent(manifest?.generated_utc || '');

    img.alt = cfg.label + ' – ' + fmtValid(item.valid_utc);
    slider.max = Math.max(0, list.length - 1);
    slider.value = state.index;
    label.textContent = fmtValid(item.valid_utc);
    step.textContent = '+' + item.step_hours + ' timer';

    if (cfg.source === 'dmi') {
      const maxText = item.max_denmark_cm != null
        ? ' · max DK ' + Number(item.max_denmark_cm).toLocaleString('da-DK', {maximumFractionDigits:1}) + ' cm'
        : '';
      uncertainty.textContent = 'DMI HARMONIE · 3-timers intervaller' + maxText;
    } else if (item.step_hours <= 120) {
      uncertainty.textContent = 'Kort sigt · 6-timers intervaller';
    } else if (item.step_hours <= 240) {
      uncertainty.textContent = 'Mellemlang sigt · stigende usikkerhed';
    } else {
      uncertainty.textContent = 'Lang sigt · betydelig usikkerhed';
    }

    renderSource();
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

  const visibleLayers = () => Object.entries(layerConfigs).filter(([key, cfg]) => {
    if (cfg.source === 'dmi') {
      return Boolean(state.dmiSnow?.products?.length);
    }
    return Boolean(state.gfs?.layers?.[key]?.products?.length);
  });

  const build = () => {
    const layers = visibleLayers();

    root.innerHTML = `
      <div class="winter-tabs">
        ${layers.map(([key,cfg]) =>
          `<button type="button" data-layer="${key}" aria-pressed="${key === state.layer}">${cfg.label}</button>`
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

      <div class="winter-source" data-source></div>
    `;

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

    if (!products().length && layers.length) {
      state.layer = layers[0][0];
    }

    setLayer(state.layer);
  };

  root.innerHTML = '<div class="winter-loading">Henter vinterudsigten…</div>';

  Promise.allSettled([
    fetch(GFS_BASE + '/winter_manifest.json?v=' + Date.now(), {cache:'no-store'})
      .then(r => {
        if (!r.ok) throw new Error('GFS HTTP ' + r.status);
        return r.json();
      }),
    fetch(DMI_SNOW_BASE + '/snow_manifest.json?v=' + Date.now(), {cache:'no-store'})
      .then(r => {
        if (!r.ok) throw new Error('DMI snow HTTP ' + r.status);
        return r.json();
      })
  ]).then(results => {
    if (results[0].status === 'fulfilled') {
      state.gfs = results[0].value;
    } else {
      console.error('GFS winter outlook:', results[0].reason);
    }

    if (results[1].status === 'fulfilled') {
      state.dmiSnow = results[1].value;
    } else {
      console.warn('DMI snow depth not available yet:', results[1].reason);
    }

    if (!state.gfs && !state.dmiSnow) {
      throw new Error('No winter forecast source available');
    }

    build();
  }).catch(err => {
    console.error('Winter outlook:', err);
    root.innerHTML = '<div class="winter-error">Vinterudsigten kan ikke hentes lige nu.</div>';
  });
})();