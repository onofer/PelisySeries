# Panel de novedades de streaming

Netflix, Prime Video, Disney+ y HBO Max en España, en un solo panel.

## Puesta en marcha (todo gratis)

1. Saca tus claves:
   - **Streaming Availability API** (obligatoria): regístrate en su Developers Platform (developers.movieofthenight.com), usa el plan gratuito y copia la clave del panel.
   - **TMDB** (opcional): pósters, fotos del reparto, tráiler y textos en español.
   - **OMDb** (opcional): nota de Rotten Tomatoes.
2. Crea un repositorio público en GitHub y sube estos archivos.
3. En el repositorio: Settings, Secrets and variables, Actions, y crea los secretos
   `SA_API_KEY`, `TMDB_API_KEY` y `OMDB_API_KEY`. Nunca pongas las claves dentro de los archivos.
4. En la pestaña Actions, ejecuta "Actualizar datos" con "Run workflow". Se creará `data.json`.
5. En Settings, Pages, publica la rama principal desde la raíz. El panel quedará en la dirección que te indique GitHub.

A partir de ahí se actualiza solo cada 6 horas.

## Comprobar que todo encaja (en tu ordenador)

    export SA_API_KEY=tu_clave
    python actualizar_datos.py --servicios   # confirma los ids de los 4 servicios en España
    python actualizar_datos.py --debug       # enseña un cambio de ejemplo de la API
    python actualizar_datos.py               # genera data.json
    python -m http.server                    # abre http://localhost:8000

Si algún servicio no sale, ajusta los ids del diccionario SERVICIOS al principio del script.

## Notas

- El script usa unas 8 consultas a Streaming Availability por ejecución; comprueba el límite de tu plan gratuito en su panel.
- Si tu clave viene de RapidAPI en vez de la Developers Platform, define también la variable `SA_PLATAFORMA=rapidapi`.
- Si GitHub deja de ejecutar el workflow por inactividad del repositorio, reactívalo desde Actions.
- Datos de Streaming Availability API, TMDB (este producto usa la API de TMDB pero no está avalado ni certificado por TMDB) y OMDb.
