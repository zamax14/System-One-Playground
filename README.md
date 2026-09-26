<div align="center">

# System One Playground

**Benchmark de modelos de toma de decisiones sobre texto, con cinco demos para verlos decidir.** La plataforma se llama Pondera.

El selector alterna entre [Jev 1.13](https://openrouter.ai/typesafe/jev-1.13), GPT-5.6 Luna
(ambos vía [OpenRouter](https://openrouter.ai)) y el modelo local
[Laya Multilingual](https://huggingface.co/convaiinnovations/laya-multilingual). Cada uno conserva
su propio estado en las demos. La primera prueba del playground de herramientas compara Jev y Luna.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-6c4ee3?logo=python&logoColor=white)](#empezar)
[![Modelos: Jev, Luna y Laya](https://img.shields.io/badge/modelos-Jev%20%7C%20Luna%20%7C%20Laya-ffc53d)](#modelos-y-preguntas)
[![GPU opcional](https://img.shields.io/badge/GPU-opcional%20·%2018×-76b900?logo=nvidia&logoColor=white)](#con-gpu)
[![Frontend sin build](https://img.shields.io/badge/frontend-sin%20build-4fa8f0)](#cómo-está-hecho)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-2fbf94)](LICENSE)

</div>

## Modelos y preguntas

Cada modelo recibe un estado (un ticket, un correo, un JSON) y preguntas tipadas de tres tipos:

| Tipo | Qué responde | Ejemplo en estas demos |
|---|---|---|
| `choice` | una opción entre varias, con probabilidad para cada una | ¿Qué categoría tiene este ticket? |
| `score` | un nivel en una escala ordenada | ¿Qué prioridad tiene? |
| `noul` | sí o no, con su probabilidad | ¿Encaja esta cocina con «comida picante»? |

El resultado común contiene la opción o puntuación y su distribución de probabilidades.
Laya es **no autorregresivo** y responde estas preguntas en una pasada; Jev usa System One y Luna
devuelve JSON estructurado. Las probabilidades de Luna son autodeclaradas, sin logprobs de la API.
El checkpoint local de Laya es **multilingüe** (mmBERT-base, 322 M de parámetros), en CPU o GPU;
es de [ConvAI Innovations](https://huggingface.co/convaiinnovations/laya-multilingual), con licencia Apache-2.0.

```python
questions = {
    "categoria": {"type": "choice", "instructions": "Which IT category does the problem in the `ticket` belong to?",
                  "criteria": {"redes": "network: wifi, VPN, internet...", "accesos": "access: passwords, locked account..."}},
    "prioridad": {"type": "score", "instructions": "How urgent and impactful is the `ticket`?",
                  "criteria": ["low: ...", "medium: ...", "high: ...", "critical: ..."]},
}
agent.predict({"ticket": "No conecta la VPN desde casa. Trabajo en remoto y..."}, questions)
# {"answers": {"categoria": {"choice": "redes", "confidence": 0.945, "probabilities": {...}},
#              "prioridad": {"score": 1.67, "probabilities": {...}, ...}}}
```

## Las demos

Las cinco tienen dos modos, y el que elijas se recuerda al cambiar de demo:

- **Real-Time**: cada decisión aparece en cuanto el modelo la toma, y al terminar un indicador muestra
  los milisegundos por decisión y si corrió en GPU, CPU o vía API.
- **Paso a paso**: la misma inferencia, reproducida a ritmo de lectura para seguir cada decisión.

Las cifras de rendimiento de estas demos corresponden a mediciones previas del checkpoint base
en una RTX 4050; la comparación del modelo reentrenado sigue pendiente.

| En Real-Time, RTX 4050 | Tanda completa | Por decisión |
|---|---|---|
| Mesa de ayuda: 20 tickets | 0,4 s | 20 ms |
| Ruta: 7 cursos encadenados | 0,6 s | 19 ms |
| Herramientas: una ruta de 4 llamadas | 0,4 s | 33 ms por vuelta |
| Atlas: 176 países | 2,4 s | 13 ms |
| City: un viaje de 19 decisiones | 3,1 s con el taxi animado | 31 ms |

### Mesa de ayuda

20 tickets de TI esperan en la cola. El modelo seleccionado los toma uno a uno: categoría, prioridad,
el experto responsable y un **semáforo** que dice cuánta atención humana necesita la asignación.
La demo también ofrece el modo Paso a paso.

| Semáforo | Confianza | Qué significa | Aciertos medidos |
|---|---|---|---|
| 🟢 Verde | más de 80 % | Asignado sin revisión | 4 de 6 |
| 🟡 Amarillo | de 60 a 80 % | Un humano confirma | 5 de 6 |
| 🔴 Rojo | menos de 60 % | Un humano decide | 3 de 7 |

El semáforo es la gracia de la demo: Laya acierta la categoría en 12 de 19 tickets, y lo dudoso se
concentra en rojo. «Ayuda urgente, no me funciona nada» sale en rojo, como debe. Cada ticket está
escrito como lo escribiría quien lo pide (síntomas, mensajes de error literales, qué probó, impacto y
plazos), sin pistas de la respuesta: un test lo comprueba.

<img src="docs/tickets.png" alt="Mesa de ayuda con el tablero agrupado por experto y un ticket en revisión" width="880">

### Ruta

Un estudiante, un objetivo y un catálogo de 17 cursos. El modelo no escribe la ruta de una vez: en cada
paso las reglas filtran los cursos cuyos prerrequisitos ya cumple y el modelo reparte probabilidad
entre esos candidatos; el curso elegido actualiza sus habilidades y el estado vuelve a entrar. Es
una política `P(acción | estado)` con el bucle a la vista: estado → candidatos → decisión → curso →
estado nuevo.

Cada curso de la ruta dice qué habilidad aporta, y el que no hacía falta queda marcado. Con los
tres objetivos y los tres estudiantes, Laya llega al objetivo en las 9 rutas y 55 de los 59 cursos
que elige aportan algo, contando los que desbloquean a otro.

<img src="docs/ruta.png" alt="Ruta: el estado del estudiante, los candidatos, las probabilidades y los siete cursos elegidos" width="880">

### Herramientas

El playground propone rutas entre 20 herramientas ficticias agrupadas en siete servidores MCP
simulados para una empresa B2B.
Cada ficha indica parámetros, resultado y si es consulta o propuesta de una acción con efecto. Las
herramientas **no se ejecutan**: los datos disponibles en la ruta son supuestos del plan, no respuestas
de un CRM, correo o SQL real. Cada vuelta usa tres preguntas tipadas y una regla:

| | Pregunta | Tipo |
|---|---|---|
| 1 | ¿Lo ya llamado cubre la petición? | `noul` |
| 2 | ¿A qué servidor hay que pedirle lo siguiente? | `choice` entre 7 |
| 3 | ¿Qué herramienta de ese servidor? | `choice` entre 2 y 4 |
| 4 | ¿Le falta algún argumento? | regla: delante van las que lo producen |

Hay diez casos sintéticos con varias etapas, dependencias y restricciones explícitas como «no envíes
correo». Al terminar uno, la página muestra la ruta de referencia aparte del estado que recibe el
modelo y señala pasos faltantes y de más. Se aceptan otros órdenes entre pasos independientes.

Una primera corrida de esos diez casos con el mismo catálogo y la misma regla, el 26 de septiembre
de 2026, dio este resultado. Es una sola corrida por modelo y las referencias son criterios de la
demo, no una medida de capacidad general:

| Modelo | Pasos esperados incluidos | Pasos de más | Casos sin faltantes ni extras |
|---|---:|---:|---:|
| Jev 1.13 | 29/36 | 11 | 3/10 |
| GPT-5.6 Luna | 34/36 | 7 | 4/10 |

<img src="docs/herramientas.png" alt="Playground con Jev: herramientas, ruta propuesta y revisión frente a la referencia" width="880">

#### Dónde se rompe

La primera prueba muestra que cubrir casi todos los pasos no basta: Jev propuso `enviar_correo` en
«Incidencia desde correo» pese a «no respondas», y Luna añadió herramientas después de cubrir
«Mover una oportunidad». Las acciones con efecto siguen siendo propuestas para revisión humana.
También hay peticiones que quedan incompletas al alcanzar el límite de vueltas o cuando el modelo
declara cubierta la petición antes de elegir la última herramienta. La comparación de la página
permite ver el fallo caso por caso.

### Atlas

Escribe qué te apetece comer («comida picante», «fácil para vegetarianos») y el modelo puntúa la
cocina de los 176 países del mapa, que se colorea mientras llegan los resultados. Cada país tiene
una ficha de cocina en español, y al tocarlo ves exactamente el texto que leyó. En Paso a
paso el mapa avanza país a país, con el panel siguiendo el país que el modelo está leyendo.

<img src="docs/atlas.png" alt="Atlas coloreado para «comida picante», con Indonesia seleccionada" width="880">

### City

El modelo conduce un taxi por una ciudad con calles de un sentido, semáforos y STOP. En cada turno
reparte probabilidad entre siete acciones y la ciudad corrige lo que viole las reglas, y lo dice.
**Sortear** cambia de sitio el taxi, al pasajero y el destino. En Real-Time el taxi recorre cada
calle en 120 ms; en Paso a paso, en 700 ms y con una pausa para leer cada turno.

<img src="docs/city.png" alt="City: el taxi de camino a recoger a Alex, con las probabilidades de cada acción" width="880">

## Empezar

Para probar Jev y Luna, guarda una llave de [OpenRouter](https://openrouter.ai/keys) en
`OPENROUTER_API_KEY` o en un archivo `openrouter` en la raíz. Después, con Python 3.10 o superior:

```bash
git clone https://github.com/zamax14/System-One-Playground.git
cd System-One-Playground
python3 server.py --remote-only
```

Este modo usa solo la biblioteca estándar de Python. Abre `http://127.0.0.1:8000` y muestra
Jev y Luna en el selector. Las llamadas a OpenRouter tienen costo; ninguna herramienta simulada
se ejecuta de verdad.

Para incluir también Laya local:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

La primera vez descarga el checkpoint de Hugging Face (~650 MB);
después funciona sin internet. Los pesos quedan en `.model-cache/huggingface/` dentro del proyecto.
`--port 8001` cambia el puerto y `--no-browser` no abre el navegador.

Si Laya se queda sin memoria en plena inferencia pasa a CPU, y la barra superior lo dice.

### Probar Jev y GPT vía OpenRouter

El archivo `openrouter` está en `.gitignore`, igual que `HF_TOKEN`. Sin llave, esos modelos salen
deshabilitados con el motivo.

- **Jev 1.13** (`typesafe/jev-1.13`) habla System One en
  `POST https://openrouter.ai/api/v1/systemone`.
- **GPT-5.6 Luna** (`openai/gpt-5.6-luna`) responde con salida estructurada: un JSON Schema generado
  a partir de las preguntas le impide salirse de las opciones. OpenRouter no da logprobs para este
  modelo, así que sus probabilidades son **autodeclaradas** y la interfaz lo marca. Va con
  `reasoning.effort: none`: ~1,4 s por ticket frente a ~3,1 s con `minimal`.

`remote.py` deja cada respuesta en el formato común, así las cinco demos funcionan igual con
cualquiera. La barra superior muestra lo gastado en la sesión y el Atlas lanza 8 países a la vez
con los modelos por API, porque 176 llamadas en serie tardan minutos.

### Benchmark

**Benchmark** hace tres preguntas por ticket: categoría (`choice`), prioridad (`score`) y bloqueo del
trabajo (`noul`). Las corridas de Jev y Luna se hicieron una sola vez por API; Laya se midió con el
checkpoint base `82d57fc4` y con la reentrenada de
[Laya-Finetune](https://github.com/zamax14/Laya-Finetune), las dos en la misma GPU (RTX 4050 de portátil). La primera medición local en CPU también se conserva en
[`web/results/`](web/results/). La página muestra las respuestas remotas guardadas y permite volver a
medir Laya localmente. Solo compara resultados con la misma huella de tickets, preguntas y referencias
(`tickets-v2`, `676cc9872e85`).

| Métrica | Laya base · GPU | Laya reentrenada · GPU | Jev 1.13 · API | GPT-5.6 Luna · API |
|---|---:|---:|---:|---:|
| Categoría | 12/19 | **17/19** | 19/19 | 19/19 |
| Prioridad exacta (a ±1 nivel) | 10/20 (20/20) | 12/20 (20/20) | 13/20 (20/20) | 15/20 (20/20) |
| Bloqueo, acierto y Brier | 15/20 · 0,178 | **19/20 · 0,042** | 19/20 · 0,048 | 19/20 · 0,052 |
| Aciertos en verde | 4/6 | 15/17 | 18/18 | 18/18 |
| Latencia p50 (p95) | 31 (33) ms | 32 (34) ms | 305 (418) ms | 1946 (2655) ms |
| Costo de API, calentamiento y 20 tickets | $0 | $0 | $0,000708 | $0,006040 |

Las gráficas usan las mismas corridas y el estilo del repositorio de referencia:

<img src="assets/benchmark/accuracy.png" width="760" alt="Acierto por categoría, prioridad y bloqueo de Laya base, Laya reentrenada, Jev y Luna">

<img src="assets/benchmark/latency.png" width="760" alt="Latencia p50, media y p95 de Laya base, Laya reentrenada, Jev y Luna en milisegundos">

<img src="assets/benchmark/cost.png" width="760" alt="Costo de API en dólares: las dos Laya cero, Jev y Luna de pago">

Para regenerar los SVG y PNG desde los JSON guardados:
`.venv/bin/python scripts/plot_benchmark.py --png` (requiere Chrome para los PNG). La Laya
reentrenada entra en las gráficas si existe su corrida (`--ajustada`, por defecto
`web/results/laya-reentrenada.json`); `--ajustada none` las dibuja sin ella. Para grabar la corrida de
otro checkpoint reentrenado:
`.venv/bin/python scripts/record_benchmark.py laya --device cuda --checkpoint .model-cache/laya-mesa-de-ayuda`.

#### Contexto largo

`scripts/benchmark_largo.py` pone cada ticket al inicio de un hilo de correo de 1k, 2k, 4k y 8k tokens de relleno de
oficina, sin ningún problema de TI, y repite las tres preguntas. Laya admite 8.192 tokens, pero se entrenó con textos
cortos. La reentrenada sostiene la categoría y el bloqueo, y la prioridad cae en las dos. La latencia pasa de 11 ms a
~545 ms con 8k tokens en una RTX 4070 Ti SUPER, casi lo mismo que Jev.

<img src="assets/benchmark/largo-bloqueo.png" width="760" alt="Bloqueo según la longitud del contexto: la base cae al 35 % y la reentrenada se mantiene entre 80 y 85 %">

<img src="assets/benchmark/largo-categoria.png" width="760" alt="Categoría según la longitud del contexto, Laya base frente a la reentrenada">

<img src="assets/benchmark/largo-prioridad.png" width="760" alt="Prioridad exacta según la longitud del contexto: las dos caen con relleno">

<img src="assets/benchmark/largo-latencia.png" width="760" alt="Latencia según la longitud del contexto: de 11 ms a unos 545 ms con 8k tokens">

Resultados en [`web/results/largo.json`](web/results/largo.json). Para repetirlo:
`.venv/bin/python scripts/benchmark_largo.py` (con `--modelos` para medir solo algunos).

Para guardar una corrida nueva después de modificar el conjunto o el modelo, usa
`.venv/bin/python scripts/record_benchmark.py jev` o `gpt-luna`. Si la corrida ya está completa,
el comando sale sin llamar a la API. Si cambian la huella o el checkpoint, exige una ruta nueva
para conservar el resultado anterior. La latencia local en GPU y la latencia remota con red miden
entornos distintos. Los $0 de Laya significan cero gasto de API; hardware y electricidad no se
calcularon. El benchmark hace tres preguntas por ticket, frente a las dos de la demo de Mesa de
ayuda. Las referencias son
criterios de esta demo y 20 tickets no miden precisión general.

### Añadir otro modelo de Hugging Face

1. Fija el ID y la revisión del repositorio de HF. Descarga los archivos con
   [`snapshot_download(repo_id, revision=...)`](https://huggingface.co/docs/huggingface_hub/guides/download).
   `fastload.py` muestra cómo usar la caché local y limitar los archivos descargados.
2. Crea un adaptador con `name`, `checkpoint`, `device`, `status` y
   `predict(state, questions)`. Devuelve `{"answers": ...}` con el contrato común:
   `choice` tiene `choice`, `confidence` y `probabilities`; `score` tiene `score` y
   `probabilities`; `noul` tiene `noul` como probabilidad entre 0 y 1. Consulta
   `fastload.SharedModel` y la normalización de `remote.py`.
3. Añade una instancia al diccionario `apps` de `server.py`, con clave estable y `App(model)`.
   Aparecerá en el selector y recibirá las mismas cinco demos. Si usa GPU, implementa
   `release()` para que el servidor pueda liberar sus pesos al cambiar de modelo.
4. Prueba una respuesta de cada tipo y ejecuta el benchmark con la misma suite. Guarda el ID,
   revisión, huella y métricas junto a sus filas; separa resultados de otros checkpoints.

### Ajuste fino

El reentrenamiento de Laya para la Mesa de ayuda vive en su propio repo,
[Laya-Finetune](https://github.com/zamax14/Laya-Finetune): generador de tickets sintéticos, entrenamiento RLCD con
Jev como profesor, notebooks y resultados. `scripts/benchmark_largo.py` acepta el checkpoint que produce
(`.model-cache/laya-mesa-de-ayuda/`) para compararlo aquí con Jev y GPT.

### Con GPU

Con una GPU NVIDIA, instala torch con CUDA en lugar del de CPU:

```bash
.venv/bin/pip install -r requirements-gpu.txt
.venv/bin/python server.py                # usa la GPU si torch la ve
.venv/bin/python server.py --device cpu   # para comparar
```

La terminal dice dónde cargó Laya («Laya lista en CUDA en 2,9 s») y la barra superior de la página
lo indica. Medido en una RTX 4050 de portátil frente a su propia CPU, con el mismo código:

| | CPU | GPU | Mejora |
|---|---|---|---|
| Atlas: un barrido de 176 países | 15,9 s | 1,9 s | **8,4×** |
| City: una decisión | 429 ms | 24 ms | **18×** |
| Mesa de ayuda: 20 tickets | 3,9 s | 0,7 s | **5,9×** |
| Ruta: 7 cursos encadenados | 1,3 s | 0,15 s | **8,5×** |
| Herramientas: 8 peticiones | 3,7 s | 0,7 s | **5,6×** |
| Carga del modelo | 4,3 s | 2,9 s | 1,5× |

En GPU Laya calcula en bf16, y aun así las decisiones son las mismas. Los 20 tickets reciben la
misma categoría, prioridad y semáforo, con 1,4 puntos de confianza de diferencia como mucho. El
Atlas da el mismo top 10 en cinco consultas, City toma las mismas 19 decisiones y la Ruta elige los
mismos cursos en el mismo orden, y el enrutador traza las mismas ocho rutas de llamadas. Usa
1,5 GB de memoria de vídeo.

## Cómo está hecho

```mermaid
flowchart LR
    B["Navegador<br/>HTML + CSS + JS"] -- "JSON y streaming SSE" --> S["server.py<br/>http.server"]
    S --> T["tickets.py"]
    S --> R["courses.py"]
    S --> H["tools.py"]
    S --> A["atlas.py"]
    S --> C["city.py"]
    T & R & H & A & C --> M["Modelo seleccionado"]
    M --> L["fastload.py<br/>Laya"]
    M --> O["remote.py<br/>Jev y GPT vía OpenRouter"]
    S --> BM["benchmark.py"] --> M
```

- **Frontend sin build.** Las páginas se sirven directamente, sin paso de compilación.
- **Resultados en streaming.** El Atlas, la Mesa de ayuda y el benchmark reciben cada resultado por
  SSE en cuanto sale. Una consulta nueva cancela la anterior en el servidor, y cerrar la pestaña del
  benchmark detiene las llamadas pendientes.
- **Un contrato para todos.** Cada modelo expone `predict(state, questions)` y `normalize` en
  `remote.py` adapta las respuestas remotas al formato común.
- **Un estado por modelo.** Las cinco demos usan el modelo seleccionado y conservan sus estados
  por separado. Laya comprueba el contexto antes de inferir porque lo truncaría en silencio.

## Lo que aprendimos

Cada decisión de diseño salió de medir con el modelo real:

- **De 23 s a 5,7 s de carga.** Laya crea el encoder con pesos aleatorios (13,9 s en CPU) justo
  antes de sobrescribirlos con el checkpoint. `no_init_weights()` se salta ese paso, con logits
  idénticos bit a bit.
- **Laya dice «sí» a lo que menciona el tema.** Con fichas etiquetadas («Picante: bajo» en todas),
  121 de 176 países salían a 1,00 para «comida picante». Ahora el texto solo nombra un rasgo cuando
  el país lo tiene.
- **Algunos países dicen «sí» a todo.** El Atlas resta a cada país su «sí» medio en 8 consultas de
  calibración. El acierto medio en el top 10 pasa de 3,3 a 8,3 sobre 10.
- **No toda confianza sirve.** La de la categoría de un ticket predice bien si acierta; la de la
  prioridad no (daba 93 % al ticket más vago). El semáforo usa solo la primera.
- **Las decisiones dependientes se derivan.** Preguntar el experto aparte daba «Hardware» asignado
  a ciberseguridad; ahora el experto es el responsable de la categoría.
- **El estado más completo no es el mejor.** En la Ruta, darle también el objetivo escrito y la
  descripción del estudiante subía de 16 a 26 (de unos 60) los cursos elegidos que no enseñaban
  ninguna habilidad del objetivo; las horas libres, otros 5. El estado son tres listas y las horas
  libres las usan solo las reglas, para estimar las semanas.
- **Laya no planifica dos pasos.** Elige bien el curso siguiente, pero nunca tomaba Git, y sin Git
  no llegaba a «Modelos en producción»: 4 de las 9 rutas se quedaban sin objetivo. Encadenar
  prerrequisitos es una regla; decidir cuál toca, del modelo.
- **Un `choice` de 20 opciones no discrimina.** En una suite anterior de ocho casos con Laya, elegir
  entre las 20 herramientas de golpe daba 1 de 8 rutas. Preguntando primero el servidor y luego la
  herramienta, el servidor elegido pertenecía a la ruta correcta en 7 de 8 peticiones.
- **Cómo preguntes el «ya basta» decide la ruta.** En esa suite anterior, «¿queda algo por hacer?»
  daba 1 de 8 rutas clavadas; «¿lo ya llamado cubre la petición?» daba 3 de 8.
- **Una ruta propuesta no es una acción ejecutada.** Los modelos pueden añadir pasos que el usuario
  prohibió o detenerse antes del último paso. Las herramientas que escriben requieren revisión humana.
- **Las instrucciones en inglés clasifican mejor**, aunque el ticket esté en español: la prioridad
  acierta 11/20 frente a 7/20.
- **El contexto rico va en el estado, no en la pregunta.** Con tickets detallados, unos criterios de
  categoría largos con reglas de desempate daban 10/19; los cortos con palabras clave, 13/19. Lo mismo
  en las otras demos: alargar las preguntas del enrutador bajaba de 15 a 12 las llamadas acertadas, y
  describir cada acción de City bajaba del 30 % al 24 % las acciones legales. Lo que sí ayudó fue
  darle a cada herramienta su descripción completa como opción: 4 llamadas de más en lugar de 6.
- **Un benchmark que dice la respuesta no mide nada.** Una versión de los tickets traía frases como
  «no es un fallo de monitores»; un test rechaza ahora esas pistas y el nombre de la propia categoría.
- **Torch solo CPU por defecto.** El entorno pasa de 5,6 GB a 1,2 GB, a la misma velocidad en CPU.
- **GPU sin compilar nada.** torch 2.14 manda una operación del encoder a Triton, que necesita
  `Python.h` para compilar. Con su interruptor oficial `TORCH_DISABLE_NATIVE_JIT=1` usa la operación
  normal de torch, así que no hace falta instalar `python3-dev`. Torch lo lee al importarse, por eso
  `fastload.py` lo activa antes.

Donde no llega, también se cuenta. El Atlas confunde el vino de uva con el vino de palma, «a la
parrilla» queda enterrado en el texto libre, y el enrutador de herramientas tiene su propia
sección de costuras más arriba.

## Estructura

```
├── server.py        servidor y API
├── fastload.py      carga rápida y compartida de Laya, en CPU o GPU, y lectura de llaves
├── remote.py        Jev y GPT vía OpenRouter, y la normalización de respuestas
├── benchmark.py     suite de tickets, métricas y eventos del benchmark
├── scripts/         herramientas de benchmark
├── tickets.py       Mesa de ayuda: tickets, preguntas y semáforo
├── courses.py       Ruta: catálogo, objetivos, prerrequisitos y bucle de decisión
├── tools.py         Herramientas: catálogo MCP, preguntas por vuelta y encadenado de argumentos
├── atlas.py         Atlas: fichas, calibración por país y barridos cancelables
├── city.py          City: mapa, reglas, protección y sorteo
├── assets/          mapa, fichas de cocina y calibración
├── web/             páginas, estilos y tipografía
├── tests/           pruebas sin descargar el modelo
└── docs/            capturas de este README
```

## Pruebas

Sin descargar el modelo:

```bash
python3 -m unittest discover -s tests -t .
node --test tests/test_web.mjs
```

Cubren el semáforo y el reparto de tickets, el catálogo y el bucle de la Ruta (prerrequisitos,
final garantizado y respuestas fuera de los candidatos), el enrutado de herramientas (encadenado de
argumentos, parada y respuestas inválidas), las fichas y la calibración del Atlas, las reglas de
City (también con conductores que eligen mal y viajes sorteados), la API con un modelo
falso (streaming, cancelación, errores del modelo, benchmark y liberación de GPU), los adaptadores de
OpenRouter sin red (esquema, normalización, costo) y la proyección y los colores del mapa.

## Créditos

- **[Laya Multilingual](https://huggingface.co/convaiinnovations/laya-multilingual)** de ConvAI Innovations, Apache-2.0. Los
  pesos no se incluyen: se descargan de Hugging Face.
- **Jev** de TypeSafe vía OpenRouter.
- **Mapa** de [Natural Earth](https://www.naturalearthdata.com/), dominio público.
- **Tipografía** [Nunito](https://github.com/googlefonts/nunito), SIL Open Font License 1.1.
- **Fichas de cocina, tickets, cursos y herramientas** redactados con Claude: simplifican y son
  ficticios. Las fichas, detalladas en [assets/README.md](assets/README.md); lo demás vive en
  `tickets.py`, `courses.py` y `tools.py`.
- **Código** bajo licencia [MIT](LICENSE).
