"""Enrutado de herramientas: el modelo propone una secuencia MCP simulada para una petición.

Cada vuelta son tres preguntas tipadas y una regla:

    ¿ya está cubierta? (noul) → ¿qué servidor? (choice) → ¿qué herramienta? (choice) → prerrequisitos (regla)

En una suite anterior con Laya, un `choice` sobre 20 herramientas acertaba 1 de 8 rutas. El
servidor y la herramienta se eligen por separado. Si falta un dato, las reglas proponen antes
una herramienta que lo produciría. Ninguna llamada se ejecuta en esta demo.
"""
import math
import time

MAX_PROMPT = 300
MAX_TURNS = 4  # Vueltas de decisión; cada una puede añadir varias llamadas encadenadas.
STOP_THRESHOLD = .35  # Umbral histórico de la suite anterior; los casos actuales exponen los fallos de parada.
SCENARIO = ("Faro es una empresa B2B ficticia. El equipo usa CRM para clientes y oportunidades, "
            "correo y agenda para coordinación, archivos internos, SQL para ventas facturadas, "
            "soporte para incidencias y web para fuentes públicas. Esta demo solo propone rutas; no ejecuta acciones.")
WRITE_TOOLS = {"crear_evento", "enviar_correo", "registrar_nota", "mover_oportunidad", "crear_documento", "crear_ticket"}

# Lo que una herramienta deja disponible: sería el argumento de las siguientes.
DATA = {"eventos": "los eventos de la agenda", "hueco": "un hueco libre", "contacto": "la ficha de un contacto",
        "correos": "una lista de correos", "texto_correo": "el texto de un correo",
        "oportunidades": "las oportunidades del cliente", "documento": "un documento localizado",
        "texto_documento": "el texto de un documento", "tabla": "una tabla de datos",
        "metricas": "métricas calculadas", "grafica": "una gráfica", "tickets": "incidencias de soporte",
        "enlaces": "enlaces de una búsqueda", "pagina": "el contenido de una página"}

# Criterios de servidor en inglés: con los mismos criterios en español, el servidor elegido acertaba
# el primer paso en 3 de 8 peticiones en lugar de 5. La página los muestra siempre en español.
SERVERS = {
    "agenda": ("Agenda", "calendar: meetings, appointments, free slots, what is on my schedule"),
    "correo": ("Correo", "email: inbox, reading a message, writing or sending an email"),
    "crm": ("CRM", "crm: customers, company records, sales opportunities, pipeline, customer notes"),
    "archivos": ("Archivos", "files: documents, contracts, reports stored on the shared drive"),
    "datos": ("Datos", "data: business figures, sales, revenue, database queries, totals and charts"),
    "soporte": ("Soporte", "support: incidents, tickets, reported technical problems"),
    "web": ("Web", "web: internet search, public pages, competitors, news"),
}

TOOLS = [
    {"id": "ver_agenda", "servidor": "agenda", "necesita": [], "produce": ["eventos"],
     "descripcion": "Lee disponibilidad y eventos del equipo en un intervalo; no reserva horas ni invita personas.",
     "parametros": ["rango de fechas", "asistentes"], "devuelve": "eventos y tramos ocupados",
     "criterio": "agenda: mi calendario, qué tengo, eventos de un día o una semana"},
    {"id": "buscar_hueco", "servidor": "agenda", "necesita": ["eventos"], "produce": ["hueco"],
     "descripcion": "Cruza eventos de los asistentes y propone franjas libres en el rango pedido; no crea citas.",
     "parametros": ["eventos", "duración", "rango de fechas"], "devuelve": "hueco común propuesto",
     "criterio": "hueco: encontrar una hora en la que todos estén libres"},
    {"id": "crear_evento", "servidor": "agenda", "necesita": ["hueco", "contacto"], "produce": [],
     "descripcion": "Propone registrar una reunión con contacto, hora y asistentes; requiere autorización explícita del usuario.",
     "parametros": ["contacto", "hueco", "asunto", "asistentes"], "devuelve": "propuesta de evento, sin ejecutarlo",
     "criterio": "agendar: crear una reunión o cita con asistentes"},
    {"id": "listar_correos", "servidor": "correo", "necesita": [], "produce": ["correos"],
     "descripcion": "Filtra la bandeja por remitente, asunto o fecha y lista metadatos; no lee cuerpos ni envía mensajes.",
     "parametros": ["remitente o asunto", "rango de fechas"], "devuelve": "IDs, remitentes y asuntos",
     "criterio": "bandeja: correos recientes, quién escribió, últimos mensajes"},
    {"id": "leer_correo", "servidor": "correo", "necesita": ["correos"], "produce": ["texto_correo"],
     "descripcion": "Lee el cuerpo de un correo previamente localizado; no responde, reenvía ni crea tickets.",
     "parametros": ["ID de correo"], "devuelve": "cuerpo del mensaje",
     "criterio": "leer correo: el contenido de un mensaje, qué dice"},
    {"id": "enviar_correo", "servidor": "correo", "necesita": ["contacto"], "produce": [],
     "descripcion": "Propone enviar un correo a un contacto identificado solo cuando el usuario lo pide; nunca lo envía en la demo.",
     "parametros": ["destinatario", "asunto", "cuerpo"], "devuelve": "propuesta de envío, sin ejecutarlo",
     "criterio": "enviar correo: escribir y mandar un mensaje a alguien"},
    {"id": "buscar_cliente", "servidor": "crm", "necesita": [], "produce": ["contacto"],
     "descripcion": "Busca una cuenta o persona por nombre en el CRM y devuelve su ficha e identificador; no consulta ventas.",
     "parametros": ["nombre de cuenta o persona"], "devuelve": "ficha e ID de contacto",
     "criterio": "ficha de cliente: encontrar una persona o empresa en el CRM por su nombre"},
    {"id": "ver_oportunidades", "servidor": "crm", "necesita": ["contacto"], "produce": ["oportunidades"],
     "descripcion": "Lista oportunidades abiertas, etapa e importe de una cuenta; no son ventas facturadas.",
     "parametros": ["ID de cuenta"], "devuelve": "oportunidades abiertas con etapa e importe",
     "criterio": "oportunidades: negocios abiertos de un cliente, importe del embudo"},
    {"id": "registrar_nota", "servidor": "crm", "necesita": ["contacto"], "produce": [],
     "descripcion": "Propone guardar una nota en la ficha de un cliente; requiere una instrucción de registro, no basta con pedir un resumen.",
     "parametros": ["ID de cuenta", "texto de la nota"], "devuelve": "propuesta de nota, sin guardarla",
     "criterio": "nota: dejar información escrita en la ficha del cliente"},
    {"id": "mover_oportunidad", "servidor": "crm", "necesita": ["oportunidades"], "produce": [],
     "descripcion": "Propone cambiar la etapa de una oportunidad identificada; no se usa para leer el embudo ni cambia datos en la demo.",
     "parametros": ["ID de oportunidad", "etapa destino"], "devuelve": "propuesta de cambio, sin ejecutarlo",
     "criterio": "etapa: mover una oportunidad a otra fase del embudo"},
    {"id": "buscar_archivo", "servidor": "archivos", "necesita": [], "produce": ["documento"],
     "descripcion": "Encuentra documentos internos por nombre, cuenta o tema; devuelve referencias, no el contenido de cada archivo.",
     "parametros": ["nombre, cuenta o tema"], "devuelve": "IDs y títulos de documentos",
     "criterio": "buscar archivo: documentos, contratos, informes de la unidad compartida"},
    {"id": "leer_documento", "servidor": "archivos", "necesita": ["documento"], "produce": ["texto_documento"],
     "descripcion": "Lee el contenido de un documento localizado, incluidas cláusulas; no crea ni comparte archivos.",
     "parametros": ["ID de documento"], "devuelve": "texto del documento",
     "criterio": "leer archivo: el texto dentro de un documento"},
    {"id": "crear_documento", "servidor": "archivos", "necesita": [], "produce": ["documento"],
     "descripcion": "Propone crear un documento interno cuando el usuario pide conservar información; no lo comparte ni lo crea en la demo.",
     "parametros": ["título", "contenido", "carpeta"], "devuelve": "propuesta de documento, sin guardarlo",
     "criterio": "archivo nuevo: guardar un informe o documento"},
    {"id": "consultar_sql", "servidor": "datos", "necesita": [], "produce": ["tabla"],
     "descripcion": "Consulta ventas facturadas e ingresos del almacén SQL por cuenta y periodo; no devuelve oportunidades del CRM.",
     "parametros": ["cuenta", "periodo", "métrica"], "devuelve": "filas de ventas facturadas",
     "criterio": "base de datos: ventas, ingresos, cifras del almacén de datos"},
    {"id": "resumir_metricas", "servidor": "datos", "necesita": ["tabla"], "produce": ["metricas"],
     "descripcion": "Calcula total, promedio o variación sobre filas de SQL ya obtenidas; no vuelve a consultar la base.",
     "parametros": ["tabla", "operación", "periodo de comparación"], "devuelve": "métricas calculadas",
     "criterio": "totales: suma, media y variación de una tabla"},
    {"id": "graficar", "servidor": "datos", "necesita": ["tabla"], "produce": ["grafica"],
     "descripcion": "Prepara una visualización de filas consultadas; no calcula por sí misma totales o variaciones.",
     "parametros": ["tabla", "ejes", "tipo de gráfica"], "devuelve": "gráfica",
     "criterio": "gráfica: dibujar una tabla"},
    {"id": "buscar_ticket", "servidor": "soporte", "necesita": [], "produce": ["tickets"],
     "descripcion": "Busca incidencias existentes por cuenta, estado o fecha; no abre tickets nuevos ni consulta correos.",
     "parametros": ["cuenta", "estado o fecha"], "devuelve": "tickets existentes",
     "criterio": "incidencias: tickets de soporte existentes de un cliente"},
    {"id": "crear_ticket", "servidor": "soporte", "necesita": ["contacto"], "produce": [],
     "descripcion": "Propone abrir una incidencia nueva para un contacto identificado y un problema descrito; no la crea en la demo.",
     "parametros": ["ID de contacto", "descripción del problema", "prioridad"], "devuelve": "propuesta de ticket, sin crearlo",
     "criterio": "ticket nuevo: abrir una incidencia de soporte"},
    {"id": "buscar_web", "servidor": "web", "necesita": [], "produce": ["enlaces"],
     "descripcion": "Busca fuentes públicas sobre competidores, noticias u ofertas; no accede a contratos ni datos internos.",
     "parametros": ["consulta", "fecha opcional"], "devuelve": "enlaces y extractos públicos",
     "criterio": "buscar en internet: qué se dice en la red, competencia, información pública"},
    {"id": "abrir_pagina", "servidor": "web", "necesita": ["enlaces"], "produce": ["pagina"],
     "descripcion": "Lee una página pública ya encontrada para comprobar sus detalles; no toma el extracto de búsqueda como prueba completa.",
     "parametros": ["URL de resultado"], "devuelve": "contenido de página pública",
     "criterio": "abrir enlace: el contenido de una página encontrada"},
]
CATALOG = {t["id"]: t for t in TOOLS}

QUESTIONS = {
    "cubierta": "Do the tools already called fully cover the `peticion`?",
    "servidor": "Which tool server must serve the first thing the `peticion` needs?",
    "herramienta": "Which of these tools does the `peticion` need?",
}

# Casos sintéticos de operaciones B2B. La referencia evalúa la ruta, nunca entra al estado del modelo.
EXAMPLES = [
    {"titulo": "Renovación sin correo", "texto": "Nordia pidió aclarar la renovación. Localiza su contrato en archivos, lee la cláusula de plazo y deja un resumen en su ficha del CRM. No envíes correo ni cambies la oportunidad.",
     "referencia": ["buscar_archivo", "leer_documento", "buscar_cliente", "registrar_nota"]},
    {"titulo": "QBR: ventas, no embudo", "texto": "Para la revisión trimestral de Nordia, consulta ventas facturadas del último trimestre, calcula total y variación frente al anterior y muéstralos en una gráfica. No uses oportunidades abiertas del CRM.",
     "referencia": ["consultar_sql", "resumir_metricas", "graficar"]},
    {"titulo": "Incidencia desde correo", "texto": "En el último correo de Nordia con asunto 'VPN caída' describen un bloqueo. Lee ese mensaje, identifica al cliente y abre un ticket de soporte con el problema. No respondas el correo.",
     "referencia": ["listar_correos", "leer_correo", "buscar_cliente", "crear_ticket"]},
    {"titulo": "Competencia y conclusión", "texto": "Busca la nueva oferta pública de Vértice, abre la fuente y contrástala con las ventas facturadas de Nordia este mes. Calcula el total y deja una nota con la comparación en la ficha de Nordia; no mandes nada fuera.",
     "referencia": ["buscar_web", "abrir_pagina", "consultar_sql", "resumir_metricas", "buscar_cliente", "registrar_nota"]},
    {"titulo": "Hueco, sin cita", "texto": "Nordia quiere reunirse la próxima semana. Consulta la agenda y encuentra un hueco común para proponerlo; todavía no crees el evento ni envíes invitación.",
     "referencia": ["ver_agenda", "buscar_hueco"]},
    {"titulo": "Cita autorizada", "texto": "La responsable de Nordia confirmó que quiere una reunión la próxima semana. Localiza su contacto, consulta agenda, busca un hueco común y prepara la creación del evento con asistentes.",
     "referencia": ["buscar_cliente", "ver_agenda", "buscar_hueco", "crear_evento"]},
    {"titulo": "Pipeline e incidencias", "texto": "Antes de llamar a Nordia, revisa sus oportunidades abiertas en el CRM y los tickets de soporte existentes. Solo necesito contexto; no cambies etapas ni abras incidencias.",
     "referencia": ["buscar_cliente", "ver_oportunidades", "buscar_ticket"]},
    {"titulo": "Mover una oportunidad", "texto": "Nordia autorizó pasar su oportunidad 'Piloto Q4' a negociación. Busca al cliente, identifica esa oportunidad y prepara el cambio de etapa; no envíes correo.",
     "referencia": ["buscar_cliente", "ver_oportunidades", "mover_oportunidad"]},
    {"titulo": "Resumen por correo", "texto": "Consulta ingresos facturados de Nordia este mes, calcula el total, localiza a su contacto y prepara el envío de ese resumen por correo. El envío debe quedar como propuesta visible.",
     "referencia": ["consultar_sql", "resumir_metricas", "buscar_cliente", "enviar_correo"]},
    {"titulo": "Informe interno", "texto": "Busca el contrato de Nordia y revisa la cláusula de renovación. Crea un documento interno con el resumen para el equipo; no lo envíes al cliente.",
     "referencia": ["buscar_archivo", "leer_documento", "crear_documento"]},
]


def public(example):
    return {k: v for k, v in example.items() if k != "referencia"}


def catalog():
    """El catálogo como lo ve la página: en español y con sus dependencias en texto."""
    return [{"id": t["id"], "servidor": t["servidor"], "servidor_nombre": SERVERS[t["servidor"]][0],
             "descripcion": t["descripcion"], "parametros": t["parametros"], "devuelve": t["devuelve"],
             "modo": "propuesta" if t["id"] in WRITE_TOOLS else "consulta",
             "necesita": [DATA[d] for d in t["necesita"]], "produce": [DATA[d] for d in t["produce"]]}
            for t in TOOLS]


def servers():
    return {k: name for k, (name, _) in SERVERS.items()}


def distribution(answer, keys):
    """El modelo devuelve la distribución en el orden de los criterios; se empareja por posición."""
    values = list(answer["probabilities"].values())
    if len(values) != len(keys) or any(not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1
                                       for p in values):
        raise ValueError("Distribución inválida")
    if abs(sum(values) - 1) > .02:
        raise ValueError("La distribución no suma 1")
    if answer["choice"] not in keys:
        raise ValueError(f"Respuesta fuera de las opciones: {answer['choice']}")
    confidence = answer["confidence"]
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Confianza inválida")
    return {k: round(v, 4) for k, v in sorted(zip(keys, values), key=lambda kv: -kv[1])}


def probability(answer):
    value = answer["noul"]
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Probabilidad fuera de 0–1")
    return value


class Route:
    """La petición, lo que ya se llamó y la ruta de llamadas construida hasta ahora."""

    def __init__(self, prompt=""):
        prompt = " ".join((prompt or "").split())
        if len(prompt) > MAX_PROMPT:
            raise ValueError(f"La petición no puede pasar de {MAX_PROMPT} caracteres.")
        self.prompt = prompt
        self.called, self.data, self.history = [], [], []
        self.done = not prompt
        self.reason = "Escribe una petición" if not prompt else ""

    def state(self):
        """Exactamente lo que lee el modelo antes de decidir."""
        return {"entorno": SCENARIO, "peticion": self.prompt,
                "ya_hecho": [t for t in self.called] or ["nada todavía"],
                "ya_tienes": [DATA[d] for d in self.data] or ["nada todavía"]}

    def chain(self, tool, extra=None, depth=0):
        """Regla: delante de una herramienta van las que producen lo que le falta.

        El modelo elige qué hacer; encadenar argumentos se resuelve con la regla existente.
        """
        added, data = [], list(self.data) + list(extra or [])
        if depth > 3:
            return added
        for need in tool["necesita"]:
            if need in data:
                continue
            options = [t for t in TOOLS if need in t["produce"]
                       and t["id"] not in self.called and t["id"] not in [a["id"] for a in added]]
            if not options:
                continue
            cheapest = min(options, key=lambda t: sum(n not in data for n in t["necesita"]))
            for step in self.chain(cheapest, [d for a in added for d in CATALOG[a["id"]]["produce"]], depth + 1):
                added.append(step)
                data += CATALOG[step["id"]]["produce"]
            added.append({"id": cheapest["id"], "porque": DATA[need]})
            data += cheapest["produce"]
        return added

    def turn(self, predict):
        """Una vuelta: ¿ya basta? → servidor → herramienta → prerrequisitos.

        Cada herramienta llega con un criterio corto y su descripción completa. El catálogo
        mostrado en la página añade el contrato de entrada y resultado para poder juzgar la ruta.
        """
        if self.done:
            raise LookupError("La ruta ya está trazada; escribe otra petición para empezar.")
        state = self.state()
        started = time.perf_counter()
        stop = None
        if self.called:
            covered = probability(predict(state, {"cubierta": {"type": "noul", "instructions": QUESTIONS["cubierta"]}})
                                  ["answers"]["cubierta"])
            stop = {"probabilidad": round(100 * covered, 1), "umbral": round(100 * STOP_THRESHOLD),
                    "para": covered > STOP_THRESHOLD}
            if stop["para"]:
                return self.finish("El modelo da la petición por cubierta", state, stop, started)
        keys = [key for key in SERVERS if any(t["servidor"] == key and t["id"] not in self.called for t in TOOLS)]
        if not keys:
            return self.finish("No quedan herramientas", state, stop, started)
        answer = predict(state, {"servidor": {"type": "choice", "instructions": QUESTIONS["servidor"],
                                              "criteria": {k: SERVERS[k][1] for k in keys}}})["answers"]["servidor"]
        probabilities = distribution(answer, keys)  # Valida antes de usar la respuesta.
        server = {"elegido": answer["choice"], "nombre": SERVERS[answer["choice"]][0],
                  "confianza": round(100 * answer["confidence"], 1), "probabilidades": probabilities}
        inside = [t for t in TOOLS if t["servidor"] == server["elegido"] and t["id"] not in self.called]
        answer = predict(state, {"herramienta": {"type": "choice", "instructions": QUESTIONS["herramienta"],
                                                 "criteria": {t["id"]: f"{t['criterio']}. {t['descripcion']}" for t in inside}}})["answers"]["herramienta"]
        ids = [t["id"] for t in inside]
        probabilities = distribution(answer, ids)
        tool = CATALOG[answer["choice"]]
        chosen = {"id": tool["id"], "confianza": round(100 * answer["confidence"], 1),
                  "probabilidades": probabilities}
        added = self.chain(tool)
        calls = [{**step, "regla": True} for step in added] + [{"id": tool["id"], "regla": False}]
        for call in calls:
            self.called.append(call["id"])
            self.data += [d for d in CATALOG[call["id"]]["produce"] if d not in self.data]
        record = self.record(state, stop, started, server, chosen, calls)
        if len(self.history) >= MAX_TURNS:
            self.done, self.reason = True, "Demasiadas vueltas"
        elif not [t for t in TOOLS if t["id"] not in self.called]:
            self.done, self.reason = True, "No quedan herramientas"
        return record

    def finish(self, reason, state, stop, started, server=None):
        self.done, self.reason = True, reason
        return self.record(state, stop, started, server, None, [])

    def record(self, state, stop, started, server, chosen, calls):
        record = {"vuelta": len(self.history) + 1, "estado": state, "parar": stop, "servidor": server,
                  "herramienta": chosen, "llamadas": calls, "elapsed": time.perf_counter() - started,
                  "fin": chosen is None}
        self.history.append(record)
        return record

    def view(self):
        example = next((case for case in EXAMPLES if case["texto"] == self.prompt), None)
        evaluation = None
        if self.done and example and self.history:
            expected = example["referencia"]
            evaluation = {"esperadas": expected,
                          "faltantes": [tool for tool in expected if tool not in self.called],
                          "de_mas": [tool for tool in self.called if tool not in expected]}
        return {"peticion": self.prompt, "done": self.done, "reason": self.reason,
                "evaluacion": evaluation,
                "llamadas": [{"id": call["id"], "regla": call["regla"], "porque": call.get("porque"),
                              "vuelta": record["vuelta"]}
                             for record in self.history for call in record["llamadas"]],
                "datos": [{"id": d, "nombre": DATA[d]} for d in self.data],
                "estado": self.state(), "history": self.history}
