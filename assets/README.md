# Datos

- `world.geojson`: Natural Earth, Admin 0 Countries, escala 1:110m, versión 5.1.2, descargado el
  2026-09-22. Fuente: https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_110m_admin_0_countries.geojson
  Dominio público: https://www.naturalearthdata.com/about/terms-of-use/
  Su escala omite países pequeños y muchas islas. La Antártida no se evalúa.
- `gastronomia.jsonl`: una ficha de cocina por país del mapa, redactada por Claude a partir de
  conocimiento general, sin verificar. Simplifica y puede tener errores. El campo opcional
  `nombre` corrige el nombre de Natural Earth cuando está anticuado (Taiwán, Esuatini).
- `gastronomia_prior.json`: el «sí» medio de Laya para cada país en las consultas de calibración.
  Lo genera `python3 -m pondera.demos.atlas calibrar`; depende de las fichas, de la pregunta y del modelo.

Las puntuaciones son inferencias de Laya; no provienen de estas bases.
