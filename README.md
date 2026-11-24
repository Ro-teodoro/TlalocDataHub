# TLALOC Data Hub

Plataforma web local para explorar estaciones climatológicas y descargar sus registros diarios.

## Ejecutar

```powershell
py -m pip install -r requirements.txt
py src/app.py
```

Abrir `http://127.0.0.1:5000`.

El catálogo se lee de `data/sources/EstacionesClimatologicas.kmz`.

La estación `8311` usa el archivo local `data/sources/dia08311.txt`.
Las demás estaciones se descargan bajo demanda desde el servicio SMN y se guardan en `data/cache/`.

## Estructura

```text
src/app.py
templates/
static/
data/
  sources/
  cache/
requirements.txt
```
