<?php
/**
 * Sortsoe Strand DMI forecast updater
 * PHP 7 compatible
 *
 * Run from cron on strandvejr.dk, for example every 30 minutes.
 * Writes ../data/sortsoe.json relative to this file when deployed with the same structure.
 */

date_default_timezone_set('Europe/Copenhagen');

$lat = 54.9347;
$lon = 11.9889;
$collection = 'harmonie_dini_sf';
$base = 'https://opendataapi.dmi.dk/v1/forecastedr';
$output = dirname(__DIR__) . '/data/sortsoe.json';

$parameters = array(
    'temperature-2m',
    'wind-speed-10m',
    'wind-dir-10m',
    'gust-wind-speed-10m',
    'fraction-of-cloud-cover',
    'rain-precipitation-rate',
    'precipitation-type',
    'probability-of-lightning'
);

function iso_utc($timestamp) {
    return gmdate('Y-m-d\TH:00:00\Z', $timestamp);
}

function fetch_dmi($url, $maxAttempts = 6) {
    $attempt = 0;

    while ($attempt < $maxAttempts) {
        $attempt++;

        $ch = curl_init();
        curl_setopt_array($ch, array(
            CURLOPT_URL => $url,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 15,
            CURLOPT_TIMEOUT => 50,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_HTTPHEADER => array(
                'Accept: application/geo+json, application/json',
                'User-Agent: strandvejr.dk DMI forecast fetcher/2.0'
            ),
            CURLOPT_HEADER => true
        ));

        $response = curl_exec($ch);
        $curlError = curl_error($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $headerSize = (int) curl_getinfo($ch, CURLINFO_HEADER_SIZE);
        curl_close($ch);

        if ($response !== false && $status >= 200 && $status < 300) {
            $body = substr($response, $headerSize);
            $json = json_decode($body, true);
            if (!is_array($json)) {
                throw new Exception('DMI returned invalid JSON');
            }
            return $json;
        }

        if ($status !== 429 && $curlError === '') {
            throw new Exception('DMI returned HTTP ' . $status);
        }

        if ($attempt >= $maxAttempts) {
            throw new Exception($status === 429 ? 'DMI rate limit after retries' : 'DMI request failed: ' . $curlError);
        }

        $wait = min(60, 4 * pow(2, $attempt - 1)) + mt_rand(1, 4);
        error_log('DMI forecast retry ' . $attempt . ' in ' . $wait . ' seconds. HTTP ' . $status . ' ' . $curlError);
        sleep((int) $wait);
    }

    throw new Exception('DMI request failed');
}

function k_to_c($value) {
    return $value === null ? null : round((float) $value - 273.15, 1);
}

function mm_hour($value) {
    return $value === null ? null : round(max(0, (float) $value * 3600), 2);
}

function percent_value($value) {
    if ($value === null) return null;
    $v = (float) $value;
    return (int) round($v <= 1.2 ? $v * 100 : $v);
}

function wind_text($degrees) {
    if ($degrees === null) return null;
    $dirs = array('N', 'NØ', 'Ø', 'SØ', 'S', 'SV', 'V', 'NV');
    $index = ((int) floor(((float) $degrees + 22.5) / 45)) % 8;
    return $dirs[$index];
}

function precipitation_type($value) {
    if ($value === null) return null;
    $map = array(
        0 => 'drizzle',
        1 => 'rain',
        2 => 'sleet',
        3 => 'snow',
        4 => 'freezing_drizzle',
        5 => 'freezing_rain',
        6 => 'graupel',
        7 => 'hail'
    );
    $key = (int) round((float) $value);
    return isset($map[$key]) ? $map[$key] : 'unknown';
}

function classify_weather($cloud, $rain, $ptype, $lightning) {
    $rain = $rain === null ? 0 : $rain;
    $cloud = $cloud === null ? 0 : $cloud;
    $lightning = $lightning === null ? 0 : $lightning;

    if ($lightning >= 25 && $rain >= 0.2) return 'thunder';
    if (($ptype === 'snow' || $ptype === 'graupel') && $rain >= 0.05) return 'snow';
    if ($ptype === 'sleet' && $rain >= 0.05) return 'sleet';
    if (($ptype === 'freezing_drizzle' || $ptype === 'freezing_rain') && $rain >= 0.05) return 'freezing_rain';
    if ($rain >= 4.0) return 'heavy_rain';
    if ($rain >= 0.5) return 'rain';
    if ($rain >= 0.05) return 'light_rain';
    if ($cloud >= 88) return 'overcast';
    if ($cloud >= 60) return 'cloudy';
    if ($cloud >= 25) return 'partly_cloudy';
    return 'clear';
}

function weather_label($code) {
    $labels = array(
        'clear' => 'Klart',
        'partly_cloudy' => 'Let skyet',
        'cloudy' => 'Skyet',
        'overcast' => 'Overskyet',
        'light_rain' => 'Let regn',
        'rain' => 'Regn',
        'heavy_rain' => 'Kraftig regn',
        'thunder' => 'Regn og risiko for torden',
        'snow' => 'Sne',
        'sleet' => 'Slud',
        'freezing_rain' => 'Isslag'
    );
    return isset($labels[$code]) ? $labels[$code] : 'Vejr';
}

function parse_feature($feature) {
    if (!isset($feature['properties']) || !is_array($feature['properties'])) return null;
    $p = $feature['properties'];
    $step = isset($p['step']) ? $p['step'] : (isset($p['time']) ? $p['time'] : null);
    if (!$step) return null;

    $dt = new DateTime($step);
    $dt->setTimezone(new DateTimeZone('Europe/Copenhagen'));

    $cloud = percent_value(isset($p['fraction-of-cloud-cover']) ? $p['fraction-of-cloud-cover'] : null);
    $rain = mm_hour(isset($p['rain-precipitation-rate']) ? $p['rain-precipitation-rate'] : null);
    $ptype = precipitation_type(isset($p['precipitation-type']) ? $p['precipitation-type'] : null);
    $lightning = percent_value(isset($p['probability-of-lightning']) ? $p['probability-of-lightning'] : null);
    $code = classify_weather($cloud, $rain, $ptype, $lightning);

    $windDir = isset($p['wind-dir-10m']) ? (float) $p['wind-dir-10m'] : null;

    return array(
        'time' => $dt->format('c'),
        'temperature' => k_to_c(isset($p['temperature-2m']) ? $p['temperature-2m'] : null),
        'wind' => isset($p['wind-speed-10m']) ? round((float) $p['wind-speed-10m'], 1) : null,
        'windDirection' => $windDir === null ? null : (int) round($windDir),
        'windDirectionText' => wind_text($windDir),
        'gust' => isset($p['gust-wind-speed-10m']) ? round((float) $p['gust-wind-speed-10m'], 1) : null,
        'rainMmH' => $rain,
        'precipitationType' => $ptype,
        'cloudCover' => $cloud,
        'lightningProbability' => $lightning,
        'weather' => $code,
        'weatherLabel' => weather_label($code)
    );
}

function summarize_day($date, $rows) {
    $temps = array();
    $winds = array();
    $gusts = array();
    $rain = 0;
    $codes = array();
    $sin = 0;
    $cos = 0;
    $dirCount = 0;

    foreach ($rows as $r) {
        if ($r['temperature'] !== null) $temps[] = $r['temperature'];
        if ($r['wind'] !== null) $winds[] = $r['wind'];
        if ($r['gust'] !== null) $gusts[] = $r['gust'];
        if ($r['rainMmH'] !== null) $rain += $r['rainMmH'];
        $hour = (int) date('G', strtotime($r['time']));
        if ($hour >= 8 && $hour <= 20) $codes[] = $r['weather'];
        if ($r['windDirection'] !== null) {
            $rad = deg2rad($r['windDirection']);
            $sin += sin($rad);
            $cos += cos($rad);
            $dirCount++;
        }
    }

    if (!$codes) {
        foreach ($rows as $r) $codes[] = $r['weather'];
    }

    $severity = array('thunder','heavy_rain','snow','sleet','freezing_rain','rain','light_rain','overcast','cloudy','partly_cloudy','clear');
    $dominant = 'clear';
    foreach ($severity as $code) {
        if (in_array($code, $codes, true)) {
            $dominant = $code;
            break;
        }
    }

    $meanDir = null;
    if ($dirCount > 0) {
        $meanDir = rad2deg(atan2($sin, $cos));
        if ($meanDir < 0) $meanDir += 360;
    }

    $summary = weather_label($dominant);
    if ($temps) $summary .= ', ' . round(max($temps)) . ' grader';
    if ($rain >= 0.1) $summary .= ', omkring ' . round($rain, 1) . ' mm nedbør';
    if ($winds) $summary .= ', vind ' . wind_text($meanDir) . ' ' . round(array_sum($winds) / count($winds)) . ' m/s';
    $summary .= '.';

    return array(
        'date' => $date,
        'temperatureMin' => $temps ? round(min($temps), 1) : null,
        'temperatureMax' => $temps ? round(max($temps), 1) : null,
        'rainMm' => round($rain, 1),
        'windAvg' => $winds ? round(array_sum($winds) / count($winds), 1) : null,
        'gustMax' => $gusts ? round(max($gusts), 1) : null,
        'windDirection' => $meanDir === null ? null : (int) round($meanDir),
        'windDirectionText' => wind_text($meanDir),
        'weather' => $dominant,
        'weatherLabel' => weather_label($dominant),
        'summary' => $summary
    );
}

try {
    $start = time() - (time() % 3600);
    $end = $start + 60 * 3600;

    $query = http_build_query(array(
        'coords' => 'POINT(' . $lon . ' ' . $lat . ')',
        'crs' => 'crs84',
        'parameter-name' => implode(',', $parameters),
        'datetime' => iso_utc($start) . '/' . iso_utc($end),
        'f' => 'GeoJSON'
    ));

    $url = $base . '/collections/' . $collection . '/position?' . $query;
    $data = fetch_dmi($url);
    $features = isset($data['features']) && is_array($data['features']) ? $data['features'] : array();

    $rows = array();
    foreach ($features as $feature) {
        $row = parse_feature($feature);
        if ($row !== null && strtotime($row['time']) >= $start) $rows[] = $row;
    }

    usort($rows, function($a, $b) {
        return strcmp($a['time'], $b['time']);
    });

    if (!$rows) throw new Exception('DMI returned no future forecast rows');

    $byDay = array();
    foreach ($rows as $row) {
        $day = substr($row['time'], 0, 10);
        if (!isset($byDay[$day])) $byDay[$day] = array();
        $byDay[$day][] = $row;
    }

    $days = array();
    foreach ($byDay as $day => $dayRows) {
        $days[] = summarize_day($day, $dayRows);
    }

    $modelPoint = array('longitude' => null, 'latitude' => null);
    if (isset($features[0]['geometry']['type']) && $features[0]['geometry']['type'] === 'Point' && isset($features[0]['geometry']['coordinates'])) {
        $coords = $features[0]['geometry']['coordinates'];
        if (isset($coords[0])) $modelPoint['longitude'] = $coords[0];
        if (isset($coords[1])) $modelPoint['latitude'] = $coords[1];
    }

    $payload = array(
        'location' => array(
            'name' => 'Sortsø Strand',
            'latitude' => $lat,
            'longitude' => $lon,
            'timezone' => 'Europe/Copenhagen',
            'modelPoint' => $modelPoint
        ),
        'source' => array(
            'provider' => 'DMI',
            'model' => 'HARMONIE DINI surface',
            'collection' => $collection,
            'api' => 'Forecast Data EDR API',
            'generated' => gmdate('c')
        ),
        'currentForecast' => $rows[0],
        'hours' => array_slice($rows, 0, 60),
        'days' => array_slice($days, 0, 3)
    );

    $dir = dirname($output);
    if (!is_dir($dir) && !mkdir($dir, 0775, true)) throw new Exception('Could not create data directory');

    $json = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($json === false) throw new Exception('Could not encode forecast JSON');

    $tmp = $output . '.tmp';
    if (file_put_contents($tmp, $json . PHP_EOL, LOCK_EX) === false) throw new Exception('Could not write temporary forecast file');
    if (!rename($tmp, $output)) throw new Exception('Could not replace forecast file');

    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(array(
        'ok' => true,
        'file' => $output,
        'hours' => count($payload['hours']),
        'days' => count($payload['days']),
        'generated' => $payload['source']['generated']
    ), JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

} catch (Exception $e) {
    http_response_code(500);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(array('ok' => false, 'error' => $e->getMessage()), JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit(1);
}
