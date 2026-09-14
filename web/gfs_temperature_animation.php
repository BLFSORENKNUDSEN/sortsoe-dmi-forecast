<?php
/**
 * Selvstændig GFS kortafspiller til strandvejr.dk.
 *
 * Filen kan inkluderes direkte i en eksisterende PHP side. Sæt eventuelt
 * manifestadresserne før include, hvis data skal hentes fra andre adresser.
 */
$gfsManifestUrl = isset($gfsManifestUrl)
    ? $gfsManifestUrl
    : 'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/gfs/output/manifest.json';
$gfsPressureManifestUrl = isset($gfsPressureManifestUrl)
    ? $gfsPressureManifestUrl
    : 'https://raw.githubusercontent.com/BLFSORENKNUDSEN/sortsoe-dmi-forecast/main/gfs/output/pressure_precipitation_manifest.json';
?>

<section class="gfs_player"
    data-gfs-player
    data-temperature-manifest-url="<?php echo htmlspecialchars($gfsManifestUrl, ENT_QUOTES, 'UTF-8'); ?>"
    data-pressure-manifest-url="<?php echo htmlspecialchars($gfsPressureManifestUrl, ENT_QUOTES, 'UTF-8'); ?>">
    <div class="gfs_map_choices" role="group" aria-label="Vælg vejrkort">
        <button type="button" class="gfs_choice is_active" data-gfs-choice="temperature" aria-pressed="true">Temperatur</button>
        <button type="button" class="gfs_choice" data-gfs-choice="pressure" aria-pressed="false">Lufttryk og nedbør</button>
    </div>

    <div class="gfs_stage">
        <img class="gfs_image" data-gfs-image alt="GFS prognosekort over Europa">
        <div class="gfs_loading" data-gfs-loading>Henter vejrkort…</div>
        <div class="gfs_error" data-gfs-error hidden></div>
    </div>

    <div class="gfs_status" aria-live="polite">
        <strong data-gfs-valid>Temperaturprognose</strong>
        <span data-gfs-position></span>
    </div>

    <div class="gfs_controls">
        <button type="button" class="gfs_button" data-gfs-previous aria-label="Forrige kort">&#10094;</button>
        <button type="button" class="gfs_button gfs_play" data-gfs-play aria-label="Start animation">Afspil</button>
        <button type="button" class="gfs_button" data-gfs-next aria-label="Næste kort">&#10095;</button>
        <input class="gfs_range" data-gfs-range type="range" min="0" max="0" value="0" step="1" aria-label="Vælg prognosetidspunkt">
    </div>
</section>

<style>
.gfs_player {
    --gfs_accent: #1676b8;
    --gfs_surface: #ffffff;
    --gfs_text: #17212b;
    --gfs_muted: #647382;
    width: 100%;
    max-width: 1120px;
    margin: 0 auto;
    color: var(--gfs_text);
    font-family: Arial, Helvetica, sans-serif;
}

.gfs_player [hidden] {
    display: none !important;
}

.gfs_map_choices {
    display: flex;
    gap: 8px;
    margin-bottom: 10px;
}

.gfs_choice {
    min-height: 40px;
    padding: 8px 16px;
    border: 1px solid #b8c4cc;
    border-radius: 7px;
    background: var(--gfs_surface);
    color: var(--gfs_text);
    cursor: pointer;
    font-size: 15px;
}

.gfs_choice.is_active {
    border-color: var(--gfs_accent);
    background: var(--gfs_accent);
    color: #ffffff;
}

.gfs_stage {
    position: relative;
    overflow: hidden;
    min-height: 220px;
    background: #eef3f6;
    border-radius: 10px;
}

.gfs_image {
    display: block;
    width: 100%;
    height: auto;
    opacity: 0;
    transition: opacity 160ms ease;
}

.gfs_image.is_ready {
    opacity: 1;
}

.gfs_loading,
.gfs_error {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    text-align: center;
}

.gfs_error {
    color: #9c2020;
    background: #fff2f2;
}

.gfs_status {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    padding: 10px 2px 7px;
    font-size: 15px;
}

.gfs_status span {
    color: var(--gfs_muted);
    white-space: nowrap;
}

.gfs_controls {
    display: grid;
    grid-template-columns: 42px 86px 42px minmax(120px, 1fr);
    gap: 8px;
    align-items: center;
}

.gfs_button {
    min-height: 40px;
    border: 1px solid #b8c4cc;
    border-radius: 7px;
    background: var(--gfs_surface);
    color: var(--gfs_text);
    cursor: pointer;
    font-size: 15px;
}

.gfs_button:hover,
.gfs_button:focus-visible {
    border-color: var(--gfs_accent);
    outline: 2px solid color-mix(in srgb, var(--gfs_accent) 25%, transparent);
}

.gfs_play {
    border-color: var(--gfs_accent);
    background: var(--gfs_accent);
    color: #ffffff;
}

.gfs_range {
    width: 100%;
    accent-color: var(--gfs_accent);
    cursor: pointer;
}

@media (max-width: 620px) {
    .gfs_stage {
        min-height: 150px;
        border-radius: 6px;
    }

    .gfs_map_choices {
        display: grid;
        grid-template-columns: 1fr 1fr;
    }

    .gfs_status {
        display: block;
        font-size: 14px;
    }

    .gfs_status span {
        display: block;
        margin-top: 3px;
    }

    .gfs_controls {
        grid-template-columns: 42px 1fr 42px;
    }

    .gfs_range {
        grid-column: 1 / -1;
        grid-row: 1;
        margin-bottom: 4px;
    }
}
</style>

<script>
(function () {
    'use strict';

    var players = document.querySelectorAll('[data-gfs-player]');

    function initialise(player) {
        var manifestUrls = {
            temperature: player.getAttribute('data-temperature-manifest-url'),
            pressure: player.getAttribute('data-pressure-manifest-url')
        };
        var image = player.querySelector('[data-gfs-image]');
        var loading = player.querySelector('[data-gfs-loading]');
        var error = player.querySelector('[data-gfs-error]');
        var valid = player.querySelector('[data-gfs-valid]');
        var position = player.querySelector('[data-gfs-position]');
        var previous = player.querySelector('[data-gfs-previous]');
        var play = player.querySelector('[data-gfs-play]');
        var next = player.querySelector('[data-gfs-next]');
        var range = player.querySelector('[data-gfs-range]');
        var choices = player.querySelectorAll('[data-gfs-choice]');
        var manifests = {};
        var activeType = 'temperature';
        var products = [];
        var current = 0;
        var timer = null;
        var baseUrl = '';

        function formatDanishTime(isoTime) {
            return new Intl.DateTimeFormat('da-DK', {
                weekday: 'short',
                day: 'numeric',
                month: 'short',
                hour: '2-digit',
                minute: '2-digit',
                timeZone: 'Europe/Copenhagen'
            }).format(new Date(isoTime));
        }

        function stop() {
            if (timer !== null) {
                window.clearInterval(timer);
                timer = null;
            }
            play.textContent = 'Afspil';
            play.setAttribute('aria-label', 'Start animation');
        }

        function show(index) {
            if (!products.length) {
                return;
            }
            current = (index + products.length) % products.length;
            var product = products[current];
            image.classList.remove('is_ready');
            image.src = baseUrl + product.file + '?v=' + encodeURIComponent(product.valid_utc);
            image.alt = (activeType === 'temperature' ? 'GFS temperaturkort gyldigt ' : 'GFS kort med lufttryk og nedbør gyldigt ') + formatDanishTime(product.valid_utc);
            valid.textContent = 'Gyldig ' + formatDanishTime(product.valid_utc);
            position.textContent = 'Prognosetime +' + product.step_hours + ' · ' + (current + 1) + ' af ' + products.length;
            range.value = String(current);

            var following = products[(current + 1) % products.length];
            var preload = new Image();
            preload.src = baseUrl + following.file + '?v=' + encodeURIComponent(following.valid_utc);
        }

        function selectMapType(type) {
            if (!manifests[type]) {
                return;
            }
            stop();
            activeType = type;
            products = manifests[type].products;
            baseUrl = manifestUrls[type].substring(0, manifestUrls[type].lastIndexOf('/') + 1);
            range.max = String(products.length - 1);
            error.hidden = true;
            loading.hidden = false;
            loading.textContent = 'Henter vejrkort…';

            for (var choiceIndex = 0; choiceIndex < choices.length; choiceIndex += 1) {
                var isActive = choices[choiceIndex].getAttribute('data-gfs-choice') === type;
                choices[choiceIndex].classList.toggle('is_active', isActive);
                choices[choiceIndex].setAttribute('aria-pressed', isActive ? 'true' : 'false');
            }
            show(0);
        }

        image.addEventListener('load', function () {
            loading.hidden = true;
            image.classList.add('is_ready');
        });

        image.addEventListener('error', function () {
            loading.hidden = true;
            error.hidden = false;
            error.textContent = 'Vejrkortet kunne ikke hentes. Prøv at genindlæse siden.';
            stop();
        });

        previous.addEventListener('click', function () {
            stop();
            show(current - 1);
        });

        next.addEventListener('click', function () {
            stop();
            show(current + 1);
        });

        play.addEventListener('click', function () {
            if (timer !== null) {
                stop();
                return;
            }
            play.textContent = 'Pause';
            play.setAttribute('aria-label', 'Sæt animation på pause');
            timer = window.setInterval(function () {
                show(current + 1);
            }, 850);
        });

        range.addEventListener('input', function () {
            stop();
            show(parseInt(range.value, 10));
        });

        for (var choiceIndex = 0; choiceIndex < choices.length; choiceIndex += 1) {
            choices[choiceIndex].addEventListener('click', function () {
                selectMapType(this.getAttribute('data-gfs-choice'));
            });
        }

        function fetchManifest(url) {
            return fetch(url + '?v=' + Date.now(), { cache: 'no-store' }).then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.json();
            });
        }

        Promise.all([
            fetchManifest(manifestUrls.temperature),
            fetchManifest(manifestUrls.pressure)
        ])
            .then(function (loaded) {
                if (!loaded[0].products || !loaded[0].products.length || !loaded[1].products || !loaded[1].products.length) {
                    throw new Error('Et manifest indeholder ingen kort');
                }
                manifests.temperature = loaded[0];
                manifests.pressure = loaded[1];
                selectMapType('temperature');
            })
            .catch(function () {
                loading.hidden = true;
                error.hidden = false;
                error.textContent = 'GFS prognosen kunne ikke indlæses. Prøv igen senere.';
            });
    }

    for (var index = 0; index < players.length; index += 1) {
        initialise(players[index]);
    }
}());
</script>
