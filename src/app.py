import io
import math
import re
import zipfile
from datetime import date
from statistics import mean
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from flask import Flask, jsonify, render_template, request, send_file


PROJECT_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = PROJECT_DIR
DATA_DIR = PROJECT_DIR / "data"
KMZ_PATH = DATA_DIR / "sources" / "EstacionesClimatologicas.kmz"
SAMPLE_DATA_PATH = DATA_DIR / "sources" / "dia08311.txt"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

app = Flask(
    __name__,
    template_folder=str(PROJECT_DIR / "templates"),
    static_folder=str(PROJECT_DIR / "static"),
)
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}


def load_stations():
    with zipfile.ZipFile(KMZ_PATH) as kmz:
        kml_name = next(name for name in kmz.namelist() if name.lower().endswith(".kml"))
        kml = kmz.read(kml_name)

    root = ET.fromstring(kml)
    stations = []
    for placemark in root.findall(".//k:Placemark", KML_NS):
        simple_data = {
            node.attrib.get("name"): (node.text or "").strip()
            for node in placemark.findall(".//k:ExtendedData//k:SimpleData", KML_NS)
        }
        point = placemark.find(".//k:Point/k:coordinates", KML_NS)
        if point is None or not point.text:
            continue
        lon, lat, *rest = (float(value) for value in point.text.strip().split(","))
        altitude = rest[0] if rest else simple_data.get("ALTITUD")

        clave = simple_data.get("CLAVE") or (placemark.find("k:name", KML_NS).text if placemark.find("k:name", KML_NS) is not None else "")
        if not clave:
            continue
        stations.append({
            "clave": clave,
            "nombre": simple_data.get("NOMBRE") or clave,
            "estado": simple_data.get("ESTADO", ""),
            "municipio": simple_data.get("MUNICIPIO", ""),
            "situacion": simple_data.get("SITUACION", ""),
            "tipo": simple_data.get("TIPO_EST", ""),
            "inicio": simple_data.get("INICIO", ""),
            "mas_reciente": simple_data.get("MAS_RECIENTE", ""),
            "altitud": altitude,
            "lat": lat,
            "lon": lon,
            "diarios_url": simple_data.get("DIARIOS", ""),
            "mensuales_url": simple_data.get("MENSUALES", ""),
            "extremos_url": simple_data.get("EXTREMOS", ""),
        })
    return stations


STATIONS = load_stations()
STATIONS_BY_CLAVE = {station["clave"]: station for station in STATIONS}


def fetch_daily_text(clave):
    cache_path = CACHE_DIR / f"dia{clave.zfill(5)}.txt"
    station = STATIONS_BY_CLAVE.get(clave)
    if clave == "8311" and SAMPLE_DATA_PATH.exists():
        return SAMPLE_DATA_PATH.read_text(encoding="utf-8")
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    if not station or not station["diarios_url"]:
        return None
    response = requests.get(station["diarios_url"], timeout=30)
    response.raise_for_status()
    text = response.content.decode("utf-8-sig", errors="replace")
    cache_path.write_text(text, encoding="utf-8")
    return text


def parse_daily_text(text):
    metadata = {}
    rows = []
    in_table = False
    for line in text.splitlines():
        match = re.match(r"\s*([A-ZÁÉÍÓÚÜÑ .-]+?)\s*:\s*(.*?)\s*$", line, re.UNICODE)
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            if key in {"ESTACIÓN", "NOMBRE", "ESTADO", "MUNICIPIO", "SITUACIÓN",
                       "LATITUD", "LONGITUD", "ALTITUD"}:
                metadata[key] = value

        parts = line.split("\t")
        if len(parts) >= 5 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0].strip()):
            in_table = True
            fecha, precip, evap, tmax, tmin = [part.strip() for part in parts[:5]]
            rows.append({
                "fecha": fecha,
                "precip": precip,
                "evap": evap,
                "tmax": tmax,
                "tmin": tmin,
            })
    return metadata, rows


def numeric_values(rows, field):
    values = []
    for row in rows:
        value = row[field]
        try:
            if value.upper() != "NULO":
                values.append(float(value))
        except (AttributeError, ValueError):
            continue
    return values


def calculate_statistics(rows):
    precip = numeric_values(rows, "precip")
    evap = numeric_values(rows, "evap")
    tmax = numeric_values(rows, "tmax")
    tmin = numeric_values(rows, "tmin")

    def average(values):
        return round(sum(values) / len(values), 2) if values else None

    def null_count(field):
        return sum(
            1 for row in rows
            if str(row[field]).strip().upper() == "NULO"
        )

    def variable_statistics(values, field, include_total=False, include_minimum=False):
        nulos = null_count(field)
        total = len(rows)
        porcentaje = round((nulos / total) * 100, 2) if total else 0
        result = {
            "observaciones": len(values),
            "nulos": nulos,
            "porcentaje_nulos": porcentaje,
        }
        if include_total:
            result["total"] = round(sum(values), 2)
            result["promedio"] = average(values)
            result["maximo"] = max(values) if values else None
        if include_minimum:
            result["promedio"] = average(values)
            result["minimo"] = min(values) if values else None
        return result

    dates = [row["fecha"] for row in rows if re.match(r"^\d{4}-\d{2}-\d{2}$", row["fecha"])]
    dates.sort()
    inicio = dates[0] if dates else None
    fin = dates[-1] if dates else None
    dias = None
    if inicio and fin:
        dias = (date.fromisoformat(fin) - date.fromisoformat(inicio)).days + 1

    return {
        "periodo": {
            "inicio": inicio,
            "fin": fin,
            "dias": dias,
            "registros": len(rows),
        },
        "precip": variable_statistics(precip, "precip", include_total=True),
        "evap": variable_statistics(evap, "evap", include_total=True),
        "tmax": {
            **variable_statistics(tmax, "tmax"),
            "promedio": average(tmax),
            "maximo": max(tmax) if tmax else None,
        },
        "tmin": {
            **variable_statistics(tmin, "tmin"),
            "promedio": average(tmin),
            "minimo": min(tmin) if tmin else None,
        },
    }


FIELD_NAMES = {
    "precip": "PRECIP",
    "evap": "EVAP",
    "tmax": "TMAX",
    "tmin": "TMIN",
}
TIME_SERIES_MODELS = {}


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def solve_linear_system(matrix, vector):
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row != column:
                factor = augmented[row][column]
                augmented[row] = [
                    augmented[row][index] - factor * augmented[column][index]
                    for index in range(size + 1)
                ]
    return [augmented[row][-1] for row in range(size)]


def predict_time_series(rows, field, target_date):
    cache_key = (
        field,
        len(rows),
        rows[0]["fecha"] if rows else "",
        rows[-1]["fecha"] if rows else "",
    )
    model = TIME_SERIES_MODELS.get(cache_key)
    if model is not None:
        intercept, slope, ordinal_origin, month_effect = model
        base_prediction = intercept + slope * (target_date.toordinal() - ordinal_origin)
        return round(base_prediction + month_effect.get(target_date.month, 0), 2)

    valid = []
    for row in rows:
        try:
            value = float(row[field])
            if str(row[field]).strip().upper() != "NULO":
                valid.append((date.fromisoformat(row["fecha"]), value))
        except (ValueError, KeyError):
            continue

    if len(valid) < 36:
        return None

    ordinal_origin = valid[0][0].toordinal()
    x_values = [record_date.toordinal() - ordinal_origin for record_date, _ in valid]
    y_values = [value for _, value in valid]
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return y_mean

    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values)) / denominator
    intercept = y_mean - slope * x_mean
    base_prediction = intercept + slope * (target_date.toordinal() - ordinal_origin)

    month_values = {}
    for (record_date, value), x in zip(valid, x_values):
        residual = value - (intercept + slope * x)
        month_values.setdefault(record_date.month, []).append(residual)
    month_effect = {
        month: mean(residuals)
        for month, residuals in month_values.items()
    }
    TIME_SERIES_MODELS[cache_key] = (intercept, slope, ordinal_origin, month_effect)
    month_effect = month_effect.get(target_date.month, 0)
    return round(base_prediction + month_effect, 2)


def nearest_station_prediction(station, rows, field, target_date):
    if not station:
        return None

    nearby = []
    for candidate in STATIONS:
        if candidate["clave"] == station["clave"] or candidate["estado"] != station["estado"]:
            continue
        distance = haversine_km(
            station["lat"], station["lon"], candidate["lat"], candidate["lon"]
        )
        if 0 < distance <= 300:
            nearby.append((distance, candidate))
    nearby.sort(key=lambda item: item[0])

    target_key = target_date.isoformat()
    weighted_values = []
    for distance, candidate in nearby[:8]:
        if distance > 300:
            break
        try:
            text = fetch_daily_text(candidate["clave"])
            if not text:
                continue
            _, candidate_rows = parse_daily_text(text)
            exact = next((row for row in candidate_rows if row["fecha"] == target_key), None)
            if exact:
                value = exact[field]
                if str(value).strip().upper() != "NULO":
                    weighted_values.append((float(value), max(distance, 1)))
        except (requests.RequestException, ValueError, TypeError, KeyError):
            continue

    if not weighted_values:
        month_values = [
            float(row[field])
            for row in rows
            if str(row[field]).strip().upper() != "NULO"
            and row["fecha"].startswith(target_key[:4] + "-" + target_key[5:7])
            and row["fecha"] != target_key
        ]
        return round(mean(month_values), 2) if month_values else None

    weight_total = sum(1 / distance for _, distance in weighted_values)
    estimate = sum(value / distance for value, distance in weighted_values) / weight_total
    return round(estimate, 2)


METHOD_NAMES = {
    "auto": "Automático",
    "serie_tiempo": "Serie de tiempo",
    "estaciones_cercanas": "Estaciones cercanas",
    "promedio_estacional": "Promedio estacional",
    "interpolacion": "Interpolación temporal",
}


def recommend_completion_method(rows, field):
    valid_count = sum(
        1 for row in rows
        if str(row[field]).strip().upper() != "NULO"
        and re.match(r"^-?\d+(?:[.,]\d+)?$", str(row[field]).strip())
    )
    total = len(rows)
    null_percentage = ((total - valid_count) / total * 100) if total else 100
    dates = [
        date.fromisoformat(row["fecha"])
        for row in rows
        if re.match(r"^\d{4}-\d{2}-\d{2}$", row["fecha"])
    ]
    span_days = (max(dates) - min(dates)).days if dates else 0

    if valid_count >= 36 and span_days >= 365 * 3:
        return "serie_tiempo", (
            "Se recomienda serie de tiempo porque la variable tiene suficientes observaciones "
            "válidas y una cobertura temporal mayor a tres años."
        )
    if null_percentage <= 15 and valid_count >= 12:
        return "interpolacion", (
            "Se recomienda interpolación temporal porque faltan pocos registros y las brechas "
            "se pueden estimar con datos cercanos en el calendario."
        )
    if valid_count >= 12:
        return "promedio_estacional", (
            "Se recomienda promedio estacional porque la serie es corta o irregular, "
            "pero conserva suficientes observaciones para estimar el patrón mensual."
        )
    return "estaciones_cercanas", (
        "Se recomienda usar estaciones cercanas porque la serie propia tiene muy pocos "
        "datos válidos para modelar una tendencia confiable."
    )


def interpolation_prediction(rows, field, target_date):
    observations = []
    for row in rows:
        try:
            value = float(str(row[field]).replace(",", "."))
            if str(row[field]).strip().upper() != "NULO":
                observations.append((date.fromisoformat(row["fecha"]), value))
        except (ValueError, AttributeError):
            continue
    observations.sort(key=lambda item: item[0])

    before = [item for item in observations if item[0] < target_date]
    after = [item for item in observations if item[0] > target_date]
    if before and after:
        x0, y0 = before[-1]
        x1, y1 = after[0]
        span = (x1 - x0).days
        if span == 0:
            return round(y0, 2)
        fraction = (target_date - x0).days / span
        return round(y0 + (y1 - y0) * fraction, 2)
    if before:
        return round(before[-1][1], 2)
    if after:
        return round(after[0][1], 2)
    return None


def seasonal_prediction(rows, field, target_date):
    values = [
        float(str(row[field]).replace(",", "."))
        for row in rows
        if str(row[field]).strip().upper() != "NULO"
        and row["fecha"][5:7] == target_date.strftime("%m")
    ]
    return round(mean(values), 2) if values else None


def complement_rows(station, rows, field, method="auto"):
    complemented = []
    valid_count = sum(
        1 for row in rows
        if str(row[field]).strip().upper() != "NULO"
        and re.match(r"^-?\d+(?:[.,]\d+)?$", str(row[field]).strip())
    )
    valid_dates = [
        date.fromisoformat(row["fecha"])
        for row in rows
        if re.match(r"^\d{4}-\d{2}-\d{2}$", row["fecha"])
    ]
    span_days = (
        (max(valid_dates) - min(valid_dates)).days
        if valid_dates else 0
    )
    recommended_method, _ = recommend_completion_method(rows, field)
    selected_method = recommended_method if method == "auto" else method
    for row in rows:
        raw_value = row[field]
        if str(raw_value).strip().upper() != "NULO":
            try:
                float(str(raw_value).replace(",", "."))
                complemented.append({
                    "fecha": row["fecha"],
                    "valor": str(raw_value).replace(",", "."),
                    "tipo": "observado",
                })
                continue
            except ValueError:
                pass

        try:
            target_date = date.fromisoformat(row["fecha"])
        except ValueError:
            complemented.append({"fecha": row["fecha"], "valor": "NULO", "tipo": "sin_dato"})
            continue

        if selected_method == "serie_tiempo":
            prediction = predict_time_series(rows, field, target_date)
            method = "serie_tiempo"
        elif selected_method == "estaciones_cercanas":
            prediction = nearest_station_prediction(station, rows, field, target_date)
            method = "estaciones_cercanas"
        elif selected_method == "promedio_estacional":
            prediction = seasonal_prediction(rows, field, target_date)
            method = "promedio_estacional"
        else:
            prediction = interpolation_prediction(rows, field, target_date)
            method = "interpolacion"
        complemented.append({
            "fecha": row["fecha"],
            "valor": str(prediction) if prediction is not None else "NULO",
            "tipo": "complementado" if prediction is not None else "sin_dato",
            "metodo": method if prediction is not None else "",
        })
    return complemented


def get_completion_method(station, rows, field, requested_method="auto"):
    if requested_method != "auto" and requested_method in METHOD_NAMES:
        return requested_method
    recommended_method, _ = recommend_completion_method(rows, field)
    return recommended_method


def calculate_completion_metrics(station, rows, field, method):
    observed = []
    for row in rows:
        try:
            value = float(str(row[field]).replace(",", "."))
            if str(row[field]).strip().upper() != "NULO":
                observed.append((row, value))
        except (ValueError, AttributeError):
            continue

    if len(observed) < 10:
        return {
            "mae": None,
            "rmse": None,
            "bias": None,
            "r2": None,
            "prueba": "Insuficiente",
            "observaciones": len(observed),
        }

    step = max(1, len(observed) // 30)
    holdout = observed[::step][:30]
    holdout_dates = {row["fecha"] for row, _ in holdout}
    training = [
        row for row in rows
        if row["fecha"] not in holdout_dates
    ]
    actual = []
    predicted = []

    for row, value in holdout:
        target_date = date.fromisoformat(row["fecha"])
        if method == "serie_tiempo":
            estimate = predict_time_series(training, field, target_date)
        elif method == "estaciones_cercanas":
            estimate = nearest_station_prediction(station, training, field, target_date)
        elif method == "promedio_estacional":
            estimate = seasonal_prediction(training, field, target_date)
        else:
            estimate = interpolation_prediction(training, field, target_date)
        if estimate is not None:
            actual.append(value)
            predicted.append(float(estimate))

    if len(actual) < 3:
        return {
            "mae": None,
            "rmse": None,
            "bias": None,
            "r2": None,
            "prueba": "Sin suficientes predicciones",
            "observaciones": len(actual),
        }

    errors = [predicted[index] - actual[index] for index in range(len(actual))]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error ** 2 for error in errors) / len(errors))
    bias = sum(errors) / len(errors)
    actual_mean = mean(actual)
    ss_res = sum((actual[index] - predicted[index]) ** 2 for index in range(len(actual)))
    ss_tot = sum((value - actual_mean) ** 2 for value in actual)
    r2 = 1 - ss_res / ss_tot if ss_tot else None
    return {
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "bias": round(bias, 3),
        "r2": round(r2, 3) if r2 is not None else None,
        "prueba": "Validación cruzada temporal",
        "observaciones": len(actual),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stations")
def stations():
    query = (request.args.get("q") or "").strip().lower()
    state = (request.args.get("estado") or "").strip().lower()
    situation = (request.args.get("situacion") or "").strip().lower()
    result = STATIONS
    if query:
        result = [
            station for station in result
            if query in station["nombre"].lower()
            or query in station["clave"].lower()
            or query in station["municipio"].lower()
        ]
    if state:
        result = [station for station in result if state in station["estado"].lower()]
    if situation:
        result = [station for station in result if station["situacion"].lower() == situation]
    return jsonify(result)


@app.route("/api/stations/<clave>")
def station_detail(clave):
    station = STATIONS_BY_CLAVE.get(clave)
    if not station:
        return jsonify({"error": "Estación no encontrada"}), 404
    return jsonify(station)


@app.route("/api/stations/<clave>/preview")
def station_preview(clave):
    try:
        text = fetch_daily_text(clave)
        if text is None:
            return jsonify({"error": "No se encontró el archivo diario"}), 404
        metadata, rows = parse_daily_text(text)
        limit = max(1, min(int(request.args.get("limit", 100)), 1000))
        return jsonify({
            "metadata": metadata,
            "count": len(rows),
            "statistics": calculate_statistics(rows),
            "rows": list(reversed(rows[-limit:])),
        })
    except requests.RequestException as exc:
        return jsonify({"error": f"No se pudo descargar la fuente: {exc}"}), 502
    except ValueError:
        return jsonify({"error": "Parámetro inválido"}), 400


@app.route("/api/stations/<clave>/download")
def station_download(clave):
    try:
        text = fetch_daily_text(clave)
        if text is None:
            return jsonify({"error": "No se encontró el archivo diario"}), 404
        filename = f"dia{clave.zfill(5)}.txt"
        return send_file(
            io.BytesIO(text.encode("utf-8")),
            mimetype="text/plain; charset=utf-8",
            as_attachment=True,
            download_name=filename,
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"No se pudo descargar la fuente: {exc}"}), 502


@app.route("/api/stations/<clave>/completion-summary")
def station_completion_summary(clave):
    field = (request.args.get("variable") or "").lower()
    mode = (request.args.get("mode") or "raw").lower()
    requested_method = (request.args.get("method") or "auto").lower()
    if field not in FIELD_NAMES:
        return jsonify({"error": "Variable no válida"}), 400
    if mode not in {"raw", "complemented"}:
        return jsonify({"error": "Modo no válido"}), 400
    if requested_method not in METHOD_NAMES:
        return jsonify({"error": "Método no válido"}), 400

    try:
        text = fetch_daily_text(clave)
        if text is None:
            return jsonify({"error": "No se encontró el archivo diario"}), 404
        _, rows = parse_daily_text(text)
        station = STATIONS_BY_CLAVE.get(clave)
        recommended_method, recommendation_reason = recommend_completion_method(rows, field)
        complementary = complement_rows(station, rows, field, requested_method) if mode == "complemented" else None

        observed = sum(
            1 for row in rows
            if str(row[field]).strip().upper() != "NULO"
            and re.match(r"^-?\d+(?:[.,]\d+)?$", str(row[field]).strip())
        )
        nulls = len(rows) - observed
        if mode == "raw":
            return jsonify({
                "variable": field,
                "nombre_variable": FIELD_NAMES[field],
                "modo": "Datos crudos",
                "total_registros": len(rows),
                "observados": observed,
                "nulos": nulls,
                "porcentaje_nulos": round(nulls / len(rows) * 100, 2) if rows else 0,
                "complementados": 0,
                "sin_completar": nulls,
                "metodo": "Sin complementación",
                "precision": None,
            })

        complementados = sum(
            1 for row in complementary
            if row["tipo"] == "complementado"
        )
        sin_completar = sum(
            1 for row in complementary
            if row["tipo"] == "sin_dato"
        )
        method = get_completion_method(station, rows, field, requested_method)
        metrics = calculate_completion_metrics(station, rows, field, method)
        return jsonify({
            "variable": field,
            "nombre_variable": FIELD_NAMES[field],
            "modo": "Datos complementados",
            "total_registros": len(rows),
            "observados": observed,
            "nulos": nulls,
            "porcentaje_nulos": round(nulls / len(rows) * 100, 2) if rows else 0,
            "complementados": complementados,
            "sin_completar": sin_completar,
            "metodo": METHOD_NAMES[method],
            "metodo_sugerido": METHOD_NAMES[recommended_method],
            "razon_sugerencia": recommendation_reason,
            "metodo_seleccionado": requested_method,
            "precision": metrics,
        })
    except requests.RequestException as exc:
        return jsonify({"error": f"No se pudo descargar la fuente: {exc}"}), 502


@app.route("/api/stations/<clave>/download-completion-report")
def station_completion_report(clave):
    field = (request.args.get("variable") or "").lower()
    mode = (request.args.get("mode") or "complemented").lower()
    method = (request.args.get("method") or "auto").lower()
    if field not in FIELD_NAMES:
        return jsonify({"error": "Variable no válida"}), 400
    summary_response = station_completion_summary(clave)
    if isinstance(summary_response, tuple):
        return summary_response
    summary = summary_response.get_json()

    lines = [
        "RESUMEN DE COMPLEMENTACIÓN DE DATOS",
        f"Estación: {clave}",
        f"Variable: {summary['nombre_variable']}",
        f"Modo: {summary['modo']}",
        f"Total de registros: {summary['total_registros']}",
        f"Observados: {summary['observados']}",
        f"Nulos: {summary['nulos']}",
        f"Porcentaje de nulos: {summary['porcentaje_nulos']} %",
        f"Complementados: {summary['complementados']}",
        f"Sin completar: {summary['sin_completar']}",
        f"Método: {summary['metodo']}",
        f"Método sugerido: {summary.get('metodo_sugerido', 'N/D')}",
        f"Razón de la sugerencia: {summary.get('razon_sugerencia', 'No aplica')}",
    ]
    if summary["precision"]:
        metrics = summary["precision"]
        lines.extend([
            f"Validación: {metrics['prueba']}",
            f"Observaciones de prueba: {metrics['observaciones']}",
            f"MAE: {metrics['mae'] if metrics['mae'] is not None else 'N/D'}",
            f"RMSE: {metrics['rmse'] if metrics['rmse'] is not None else 'N/D'}",
            f"Sesgo: {metrics['bias'] if metrics['bias'] is not None else 'N/D'}",
            f"R2: {metrics['r2'] if metrics['r2'] is not None else 'N/D'}",
        ])
    content = "\n".join(lines) + "\n"
    return send_file(
        io.BytesIO(content.encode("utf-8-sig")),
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name=f"{field}_{clave}_reporte_complementacion.txt",
    )


@app.route("/api/stations/<clave>/download-variable")
def station_variable_download(clave):
    field = (request.args.get("variable") or "").lower()
    mode = (request.args.get("mode") or "raw").lower()
    output_format = (request.args.get("format") or "csv").lower()
    method = (request.args.get("method") or "auto").lower()
    if field not in FIELD_NAMES:
        return jsonify({"error": "Variable no válida"}), 400
    if mode not in {"raw", "complemented"}:
        return jsonify({"error": "Modo no válido"}), 400
    if output_format not in {"csv", "txt"}:
        return jsonify({"error": "Formato no válido"}), 400
    if method not in METHOD_NAMES:
        return jsonify({"error": "Método no válido"}), 400

    try:
        text = fetch_daily_text(clave)
        if text is None:
            return jsonify({"error": "No se encontró el archivo diario"}), 404
        _, rows = parse_daily_text(text)
        station = STATIONS_BY_CLAVE.get(clave)

        if mode == "raw":
            data_rows = [
                {
                    "fecha": row["fecha"],
                    "valor": row[field],
                    "tipo": "observado" if str(row[field]).strip().upper() != "NULO" else "nulo",
                }
                for row in rows
            ]
        else:
            data_rows = complement_rows(station, rows, field, method)

        if output_format == "csv":
            lines = [
                "FECHA," + FIELD_NAMES[field]
                + (",TIPO,COMPLEMENTADO,METODO" if mode == "complemented" else "")
            ]
            for row in data_rows:
                if mode == "complemented":
                    marcado = "SI" if row["tipo"] == "complementado" else "NO"
                    extra = "," + row["tipo"] + "," + marcado + "," + row.get("metodo", "")
                else:
                    extra = ""
                lines.append(f'{row["fecha"]},{row["valor"]}{extra}')
            content = "\n".join(lines) + "\n"
            mimetype = "text/csv; charset=utf-8"
            extension = "csv"
        else:
            lines = [
                "FECHA\t" + FIELD_NAMES[field]
                + ("\tTIPO\tCOMPLEMENTADO\tMETODO" if mode == "complemented" else "")
            ]
            for row in data_rows:
                if mode == "complemented":
                    marcado = "SI" if row["tipo"] == "complementado" else "NO"
                    extra = "\t" + row["tipo"] + "\t" + marcado + "\t" + row.get("metodo", "")
                else:
                    extra = ""
                lines.append(f'{row["fecha"]}\t{row["valor"]}{extra}')
            content = "\n".join(lines) + "\n"
            mimetype = "text/plain; charset=utf-8"
            extension = "txt"

        suffix = "complementado" if mode == "complemented" else "crudo"
        filename = f"{field}_{clave}_{suffix}.{extension}"
        return send_file(
            io.BytesIO(content.encode("utf-8-sig")),
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"No se pudo descargar la fuente: {exc}"}), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
