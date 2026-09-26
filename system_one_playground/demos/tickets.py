"""Mesa de ayuda de TI: el modelo decide categoría y prioridad; la categoría decide el experto."""
import math

# Criterios cortos, con palabras clave y en inglés; el contexto rico va en el ticket. Medido con Laya sobre los
# tickets actuales: criterios largos con reglas de desempate daban 10/19 en categoría; estos, 13/19. En inglés la
# prioridad ya acertaba más que en español (11/20 frente a 7/20 con los tickets anteriores).
CATEGORIES = {
    "hardware": ("Hardware", "lucia", "hardware: laptops, screens, printers, peripherals, buying equipment"),
    "software": ("Software", "diego", "software: business apps (ERP, CRM), installing programs, licenses, app errors"),
    "redes": ("Redes", "sofia", "network: wifi, VPN, internet, slow or down network, offices offline"),
    "accesos": ("Accesos", "andres", "access: passwords, locked account, new users, folder permissions"),
    "correo": ("Correo y colaboración", "valeria", "email and collaboration: Outlook, missing emails, calendars, Teams calls"),
    "seguridad": ("Seguridad", "tomas", "security: phishing, viruses, trojans, unauthorized account use, fraud"),
}
# De menor a mayor: es una escala, así que Laya la puntúa como «score» y se redondea al nivel más cercano.
PRIORITIES = {
    "baja": ("Baja", "low: optional improvement, cosmetic defect or planned purchase; a usable workaround exists and no near deadline is stated"),
    "media": ("Media", "medium: one person or team is inconvenienced, but the core task can continue; routine access or onboarding request with time to prepare"),
    "alta": ("Alta", "high: one person cannot perform essential work, a deadline is imminent, customer work is being lost, or a credible security warning needs prompt investigation"),
    "critica": ("Crítica", "critical: many people or a key business process is stopped, or malware, unauthorized access or fraud may be active; immediate coordinated response"),
}
# Cada categoría tiene un responsable, como en una mesa de ayuda real: así el experto nunca contradice
# a la categoría (preguntarlo aparte daba «Hardware» asignado a ciberseguridad).
EXPERTS = {
    "lucia": ("Lucía Romero", "Puestos de trabajo e impresión"),
    "diego": ("Diego Martín", "Aplicaciones de negocio"),
    "sofia": ("Sofía Herrera", "Redes y conectividad"),
    "andres": ("Andrés Castillo", "Identidad y accesos"),
    "valeria": ("Valeria Núñez", "Correo y colaboración"),
    "tomas": ("Tomás Ibarra", "Ciberseguridad"),
}
EXPERT_DETAILS = {
    "lucia": {"especialidad": "Diagnóstico de equipos, periféricos e impresión", "atiende": "Portátiles que no arrancan, monitores, impresoras y compra o sustitución de equipos.", "deriva": "Si el equipo funciona pero falla una aplicación, deriva a Diego; si falla la conexión, a Sofía."},
    "diego": {"especialidad": "Aplicaciones de negocio y licencias", "atiende": "ERP, CRM, errores de programas, instalaciones, configuración y licenciamiento.", "deriva": "Si varias aplicaciones fallan por la red, deriva a Sofía; permisos y cuentas corresponden a Andrés."},
    "sofia": {"especialidad": "Conectividad y servicios de red", "atiende": "Wi-Fi, VPN, internet, caídas de oficina y lentitud generalizada entre servicios.", "deriva": "Si solo falla una aplicación con la red estable, deriva a Diego."},
    "andres": {"especialidad": "Identidad, altas y permisos", "atiende": "Contraseñas, cuentas bloqueadas, altas de usuarios y acceso a carpetas compartidas.", "deriva": "Si hay señales de suplantación o uso no autorizado, deriva a Tomás."},
    "valeria": {"especialidad": "Correo, calendarios y colaboración", "atiende": "Entrega y sincronización de correo, Outlook, calendarios y llamadas de Teams.", "deriva": "Un mensaje sospechoso o un enlace de phishing corresponde a Tomás."},
    "tomas": {"especialidad": "Incidentes de ciberseguridad", "atiende": "Phishing, malware, credenciales expuestas, actividad no autorizada y fraude.", "deriva": "Una falla ordinaria de correo sin indicios de ataque corresponde a Valeria."},
}
QUESTIONS = {
    "categoria": {"type": "choice", "instructions": "Which IT support team should handle the problem described in the `ticket`? Focus on the cause the requester describes, not on every system they mention.",
                  "criteria": {k: crit for k, (_, _, crit) in CATEGORIES.items()}},
    "prioridad": {"type": "score", "instructions": "How urgent and impactful is the `ticket`?",
                  "criteria": [crit for _, crit in PRIORITIES.values()]},
}
# Frases que delatan la respuesta en una descripción; los tickets (y los generados para entrenar) no las usan.
LEAK_HINTS = ("no es un", "no se trata de", "no hay indicios", "corresponde a", "categoría")
# Semáforo sobre la confianza de la asignación (categoría → experto).
LIGHTS = {"verde": "Asignado sin revisión", "amarillo": "Un humano confirma", "rojo": "Un humano decide"}

# «referencia» es la respuesta que daría un técnico y «bloquea» dice si alguien no puede trabajar ahora;
# ninguna de las dos se envía a la página ni al modelo. Cada ticket está escrito como lo escribiría quien
# lo pide: síntomas, mensajes literales, qué probó e impacto, sin nombrar al equipo que debe atenderlo.
TICKETS = [
    {"id": "T-1001", "titulo": "El portátil no enciende", "solicitante": "Marta Gil", "area": "Finanzas",
     "descripcion": "Esta mañana llegué a las 8:00 y mi portátil Lenovo ThinkPad no arranca: al pulsar el botón no se enciende ninguna luz, no suena el ventilador y la pantalla sigue negra. Lo dejé conectado al cargador media hora, probé con el cargador de un compañero y en otro enchufe, y nada. Ayer por la tarde funcionaba normal y lo apagué como siempre. Tengo en ese equipo el informe de cierre trimestral que debo entregar a Dirección hoy a las 17:00 y no tengo otro ordenador asignado.",
     "referencia": ("hardware", "alta", "lucia"), "bloquea": True},
    {"id": "T-1002", "titulo": "No conecta la VPN desde casa", "solicitante": "Jorge Peña", "area": "Ventas",
     "descripcion": "Hoy trabajo en remoto y el cliente de VPN (FortiClient) se queda en «Conectando… 40 %» y luego muestra «Error -121: el servidor remoto no responde». Desde ayer por la tarde pasa lo mismo. En casa internet va bien: puedo ver vídeos, entrar a Gmail y hacer videollamadas. Reinicié el router y el portátil y reinstalé FortiClient, sin cambios. Sin la VPN no llego al CRM ni a la carpeta de pedidos, y tengo tres clientes esperando cotización antes del mediodía.",
     "referencia": ("redes", "alta", "sofia"), "bloquea": True},
    {"id": "T-1003", "titulo": "Correo raro pidiendo mi contraseña", "solicitante": "Lorena Vidal", "area": "Recursos Humanos",
     "descripcion": "Me llegó un correo con el logo del Banco Nacional, remitente «notificaciones@banconacional-seguro.co», que dice que mi cuenta de nóminas será suspendida en 24 horas si no confirmo mi usuario y contraseña en un enlace. El banco que usamos escribe desde otro dominio y nunca pide contraseñas. No hice clic en nada. Dos compañeras del área recibieron el mismo mensaje esta mañana y una no está segura de si llegó a abrir el enlace. Les pedí que no lo toquen hasta que alguien lo revise.",
     "referencia": ("seguridad", "alta", "tomas"), "bloquea": False},
    {"id": "T-1004", "titulo": "Acceso a la carpeta de Finanzas", "solicitante": "Pablo Ríos", "area": "Dirección",
     "descripcion": "Necesito permiso de lectura en la carpeta compartida \\\\fs01\\Finanzas\\Presupuesto 2026 para preparar la reunión de revisión del presupuesto del próximo martes. Al abrirla, Windows muestra «No tiene permiso para acceder a esta carpeta. Póngase en contacto con el administrador». Las demás carpetas del servidor las abro sin problema y mi sesión funciona bien. La directora financiera, Ana Beltrán, ya aprobó por correo que tenga acceso de solo lectura.",
     "referencia": ("accesos", "media", "andres"), "bloquea": False},
    {"id": "T-1005", "titulo": "Outlook no sincroniza el calendario", "solicitante": "Elena Sanz", "area": "Marketing",
     "descripcion": "Desde el jueves pasado las reuniones que creo en Outlook del ordenador no aparecen en el calendario del iPhone de empresa. Las antiguas sí se ven, y en el móvil el buzón recibe mensajes nuevos con normalidad. Borré la cuenta del iPhone y la volví a añadir, pero sigue igual. En el ordenador veo toda la agenda, así que me voy organizando desde ahí, aunque la semana que viene tengo visitas a clientes y necesito ver las citas en el móvil.",
     "referencia": ("correo", "media", "valeria"), "bloquea": False},
    {"id": "T-1006", "titulo": "El ERP falla en el cierre contable", "solicitante": "Raúl Ortega", "area": "Finanzas",
     "descripcion": "Al lanzar el proceso de cierre de mes en SAP Business One, en el paso «Asientos de periodificación» aparece «Error 3021: violación de clave en tabla OJDT» y el proceso se cancela. Lo intentamos cuatro personas del equipo contable desde distintos equipos y a todos nos pasa lo mismo desde las 9:30. El resto de SAP y el correo funcionan. Sin el cierre no podemos contabilizar nada del mes y la declaración a Hacienda vence mañana a las 14:00. Somos ocho personas paradas.",
     "referencia": ("software", "critica", "diego"), "bloquea": True},
    {"id": "T-1007", "titulo": "La impresora imprime con rayas", "solicitante": "Nuria Campos", "area": "Operaciones",
     "descripcion": "La impresora HP LaserJet de la planta 3 (junto a la sala de reuniones) saca todas las hojas con dos rayas grises verticales en el margen izquierdo desde que cambiamos el tóner el lunes. Probamos a sacar el tóner, agitarlo y limpiar el cristal, y las rayas siguen. Los documentos se leen bien y mientras tanto imprimimos lo importante en la de la planta 2. Lo dejo avisado para cuando puedan pasar.",
     "referencia": ("hardware", "baja", "lucia"), "bloquea": False},
    {"id": "T-1008", "titulo": "Sin wifi en la oficina de Monterrey", "solicitante": "Iván Soto", "area": "Operaciones",
     "descripcion": "Desde las 9:15 nadie en la oficina de Monterrey puede conectarse a la red «CORP-MTY»: los portátiles la ven pero dan «No se puede conectar a esta red», y los que estaban conectados perdieron internet. El equipo del rack de la sala de servidores tiene luces naranjas parpadeando. Los teléfonos IP tampoco tienen línea. Somos 40 personas; almacén no puede registrar entregas y el turno de atención a clientes no puede entrar al sistema. Algunos están compartiendo datos del móvil, pero no alcanza.",
     "referencia": ("redes", "critica", "sofia"), "bloquea": True},
    {"id": "T-1009", "titulo": "Alta de usuario para nueva empleada", "solicitante": "Carmen León", "area": "Recursos Humanos",
     "descripcion": "El lunes 6 se incorpora Sara Molina como analista de Ventas, reportando a Diego Serrano. Necesita usuario de red, cuenta de correo, acceso de lectura y escritura al CRM con el perfil «Comercial» y acceso a la carpeta compartida de Ventas. El contrato ya está firmado y adjunto el formulario de alta aprobado por su responsable. El portátil ya lo tiene preparado el área de sistemas. Nos gustaría que el lunes a primera hora pueda iniciar sesión.",
     "referencia": ("accesos", "media", "andres"), "bloquea": False},
    {"id": "T-1010", "titulo": "El antivirus detectó un troyano", "solicitante": "Sergio Molina", "area": "Logística",
     "descripcion": "Hace diez minutos abrí un adjunto llamado «Factura_Proveedor_0925.zip» que venía de un transportista con el que trabajamos. Al descomprimirlo, Windows Defender mostró «Amenaza encontrada: Trojan:Win32/Emotet. Estado: activo. Acción recomendada: aislar el dispositivo». Poco después el portátil empezó a ir muy lento y vi ventanas negras que se abrían y cerraban. Desconecté el cable de red y el wifi por si acaso y no lo he vuelto a usar. En ese equipo tengo acceso a las carpetas compartidas de Logística y Compras.",
     "referencia": ("seguridad", "critica", "tomas"), "bloquea": True},
    {"id": "T-1011", "titulo": "Licencia de Adobe Acrobat", "solicitante": "Beatriz Luna", "area": "Marketing",
     "descripcion": "Quisiera que me instalen Adobe Acrobat Pro con licencia en mi portátil. En los próximos proyectos tendré que editar textos y combinar varios PDF de proveedores para los catálogos. De momento me apaño con el visor gratuito para leer y firmar, y cuando necesito editar le pido el favor a un compañero que sí tiene licencia. No hay prisa: el primer catálogo empieza a prepararse a finales del mes que viene. Mi jefa ya dio el visto bueno al gasto.",
     "referencia": ("software", "baja", "diego"), "bloquea": False},
    {"id": "T-1012", "titulo": "No llegan correos de clientes", "solicitante": "Hugo Navarro", "area": "Ventas",
     "descripcion": "Desde ayer a las 16:00 no me llega ningún mensaje de fuera de la empresa: los de compañeros sí entran, pero dos clientes me llamaron para decirme que me enviaron pedidos a hugo.navarro@empresa.com y a uno le rebotó con «550 5.1.1 Recipient rejected». Revisé la carpeta de correo no deseado y las reglas de Outlook y no hay nada raro. A mis compañeros de Ventas sí les llegan los correos externos. Mientras tanto estoy llamando a los clientes uno por uno para que me dicten los pedidos, pero así ya perdí uno.",
     "referencia": ("correo", "alta", "valeria"), "bloquea": False},
    {"id": "T-1013", "titulo": "Cuenta bloqueada", "solicitante": "Alicia Ramos", "area": "Logística",
     "descripcion": "Esta mañana puse varias veces la contraseña antigua, porque la cambié el viernes, y ahora al iniciar sesión en Windows sale «La cuenta a la que se hace referencia está bloqueada y no se puede iniciar sesión». No puedo entrar ni al ordenador, ni al sistema de inventario, ni a mi correo. Escribo desde el portátil de un compañero. Hoy tengo que registrar las salidas de 60 envíos antes de las 13:00 para que el camión salga a tiempo, y nadie más en el turno tiene mis permisos del inventario.",
     "referencia": ("accesos", "alta", "andres"), "bloquea": True},
    {"id": "T-1014", "titulo": "La pantalla externa parpadea", "solicitante": "Óscar Prieto", "area": "Dirección",
     "descripcion": "El monitor Dell de 27 pulgadas de mi escritorio se apaga uno o dos segundos más o menos cada media hora y luego vuelve. Cambié el cable HDMI por uno nuevo y lo conecté a otro puerto de la base, pero sigue pasando. La pantalla del portátil nunca parpadea, así que cuando me molesta mucho trabajo solo con ella. No tengo presentaciones próximamente; cuando puedan, revisen el monitor o cámbienmelo.",
     "referencia": ("hardware", "baja", "lucia"), "bloquea": False},
    {"id": "T-1015", "titulo": "Teams se congela en llamadas", "solicitante": "Rosa Delgado", "area": "Ventas",
     "descripcion": "En casi todas mis videollamadas de Teams con clientes, a los pocos minutos la imagen se congela, el audio se entrecorta y aparece «Tu conexión de red es inestable», aunque en ese mismo momento las demás aplicaciones funcionan bien y los compañeros que están a mi lado hacen llamadas de Teams sin problema. Ya actualicé Teams y borré la caché. Cuando se corta, continúo la reunión por teléfono. La próxima demostración importante con un cliente es el lunes.",
     "referencia": ("correo", "media", "valeria"), "bloquea": False},
    {"id": "T-1016", "titulo": "El CRM no carga y la red va lenta", "solicitante": "Manuel Cruz", "area": "Ventas",
     "descripcion": "Desde las 10:00 el CRM tarda tres o cuatro minutos en abrir cada ficha de cliente y a veces da «Tiempo de espera agotado». Pero no es solo el CRM: Gmail, las páginas web y las descargas también van lentísimas en toda la planta 2, y un test de velocidad me marca 0,8 Mbps cuando normalmente pasa de 200. Los cinco comerciales de la planta estamos igual; los de la sede de Guadalajara trabajan normal en el mismo CRM. Estamos sacando las cotizaciones de hoy con mucho retraso.",
     "referencia": ("redes", "alta", "sofia"), "bloquea": False},
    {"id": "T-1017", "titulo": "Cambiar el fondo de pantalla", "solicitante": "Laura Fuentes", "area": "Marketing",
     "descripcion": "Para la campaña de otoño queremos que los 12 ordenadores del área de Marketing tengan como fondo de escritorio la nueva imagen de la campaña, y que no se pueda cambiar hasta que termine en diciembre. Adjunto la imagen en 1920×1080 y en 2560×1440. La campaña arranca el día 1 del mes que viene, así que cualquier momento antes nos sirve. Si es más fácil aplicarlo a todos a la vez con una directiva, mejor.",
     "referencia": ("software", "baja", "diego"), "bloquea": False},
    {"id": "T-1018", "titulo": "Alguien aprobó un pago con mi usuario", "solicitante": "Andrea Vega", "area": "Finanzas",
     "descripcion": "Revisando la bandeja de pagos del ERP vi uno de 48.900 € a un proveedor que no conozco, «Suministros Iberlux SL», aprobado con mi usuario hoy a las 02:14. A esa hora yo estaba durmiendo y no he aprobado nada fuera del horario. El historial de sesiones muestra un inicio de sesión desde una IP de otro país. Llamé al banco y todavía pueden retener la transferencia hasta las 12:00. Mi usuario sigue teniendo permiso para aprobar pagos y hay otros tres pendientes en la cola.",
     "referencia": ("seguridad", "critica", "tomas"), "bloquea": False},
    {"id": "T-1019", "titulo": "Portátiles para el equipo de ventas", "solicitante": "Diego Serrano", "area": "Ventas",
     "descripcion": "El mes que viene se incorporan cinco comerciales nuevos y necesitamos cinco portátiles con el mismo modelo que usa el resto del equipo (ThinkPad T14), con cargador, mochila y base para el escritorio. El presupuesto ya está aprobado por Dirección. Las incorporaciones son el día 3, así que nos gustaría hacer el pedido esta semana para que haya tiempo de recibirlos y prepararlos.",
     "referencia": ("hardware", "media", "lucia"), "bloquea": False},
    {"id": "T-1020", "titulo": "Ayuda urgente", "solicitante": "Pedro Vargas", "area": "Operaciones",
     "descripcion": "No me funciona nada desde esta mañana y no puedo avanzar con mi trabajo. Necesito que alguien me llame lo antes posible, es urgente.",
     "referencia": (None, "alta", None), "bloquea": True},  # Sin datos para saber categoría ni experto: debería salir en rojo.
]


def ticket_state(ticket):
    return {"ticket": f"{ticket['titulo']}. {ticket['descripcion']} (Solicitante: {ticket['solicitante']}, área de {ticket['area']}.)"}


def public(ticket):
    return {k: v for k, v in ticket.items() if k not in ("referencia", "bloquea")}


def light(confidence):
    """Verde por encima de 80, amarillo de 60 a 80 (ambos incluidos), rojo por debajo de 60 (en %)."""
    color = "verde" if confidence > 80 else "amarillo" if confidence >= 60 else "rojo"
    return color, LIGHTS[color]


def _probabilities(answer, keys):
    values = list(answer["probabilities"].values())
    if len(values) != len(keys) or not all(isinstance(p, (int, float)) and math.isfinite(p) and 0 <= p <= 1 for p in values):
        raise ValueError("Probabilidades inválidas")
    return dict(zip(keys, values))


def assign(ticket, predict):
    """Una inferencia responde categoría y prioridad; el semáforo usa la confianza de la categoría."""
    answers = predict(ticket_state(ticket), QUESTIONS)["answers"]
    category, priority = answers["categoria"], answers["prioridad"]
    if category["choice"] not in CATEGORIES:
        raise ValueError("Categoría desconocida")
    levels = list(PRIORITIES)
    score = priority["score"]
    if not isinstance(score, (int, float)) or not math.isfinite(score):
        raise ValueError("Prioridad inválida")
    confidence = round(100 * category["confidence"], 1)
    color, attention = light(confidence)
    return {"id": ticket["id"],
            "categoria": {"choice": category["choice"], "confidence": confidence,
                          "probabilities": _probabilities(category, list(CATEGORIES))},
            "prioridad": {"choice": levels[min(len(levels) - 1, max(0, round(score)))], "score": round(score, 2),
                          "confidence": round(100 * priority["confidence"], 1),
                          "probabilities": _probabilities(priority, levels)},
            "experto": CATEGORIES[category["choice"]][1],
            "confianza": confidence, "semaforo": color, "atencion": attention}
