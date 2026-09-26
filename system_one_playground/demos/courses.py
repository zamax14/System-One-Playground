"""Ruta de aprendizaje: el modelo elige, paso a paso, el siguiente curso del estudiante.

El bucle es una política P(acción | estado). Nadie le pide la ruta entera de una vez: las reglas
filtran los cursos cuyos prerrequisitos ya cumple, el modelo reparte probabilidad entre esos candidatos,
el curso elegido actualiza sus habilidades y el estado nuevo vuelve a entrar.
"""
import math
import time

SKILLS = {
    "fundamentos": "Fundamentos de programación",
    "python": "Python",
    "git": "Git y control de versiones",
    "sql": "SQL",
    "estadistica": "Estadística",
    "pandas": "Análisis con pandas",
    "visualizacion": "Visualización de datos",
    "ml": "Machine learning",
    "deep": "Deep learning",
    "mlops": "Modelos en producción",
    "html": "HTML y CSS",
    "js": "JavaScript",
    "react": "React",
    "backend": "APIs y backend",
    "nube": "Nube y despliegue",
    "seguridad": "Seguridad informática",
}
LEVELS = ("básico", "intermedio", "avanzado")
MAX_STEPS = 12  # Tope de seguridad: con este catálogo ninguna ruta razonable pasa de 7 cursos.

# Catálogo compartido por todos los objetivos: parte de los candidatos de cada turno no lleva al
# objetivo, y eso es justo lo que tiene que descartar el modelo.
COURSES = [
    {"id": "programacion-cero", "nombre": "Programación desde cero", "nivel": "básico", "horas": 20,
     "descripcion": "Variables, condicionales, bucles y funciones con ejercicios guiados.",
     "ensena": ["fundamentos"], "requisitos": []},
    {"id": "python-basico", "nombre": "Python para principiantes", "nivel": "básico", "horas": 25,
     "descripcion": "Sintaxis de Python, estructuras de datos, archivos y librerías estándar.",
     "ensena": ["python"], "requisitos": ["fundamentos"]},
    {"id": "git-github", "nombre": "Git y GitHub", "nivel": "básico", "horas": 10,
     "descripcion": "Commits, ramas, resolución de conflictos y trabajo en equipo sobre un repositorio.",
     "ensena": ["git"], "requisitos": ["fundamentos"]},
    {"id": "sql-datos", "nombre": "SQL para datos", "nivel": "básico", "horas": 18,
     "descripcion": "Consultas, uniones, agregaciones y modelado básico de una base relacional.",
     "ensena": ["sql"], "requisitos": []},
    {"id": "estadistica-aplicada", "nombre": "Estadística aplicada", "nivel": "básico", "horas": 22,
     "descripcion": "Distribuciones, medidas de dispersión, correlación y contraste de hipótesis.",
     "ensena": ["estadistica"], "requisitos": []},
    {"id": "excel-reportes", "nombre": "Excel para reportes", "nivel": "básico", "horas": 12,
     "descripcion": "Tablas dinámicas y gráficos para presentar cifras de negocio.",
     "ensena": ["visualizacion"], "requisitos": []},
    {"id": "pandas-analisis", "nombre": "Análisis de datos con pandas", "nivel": "intermedio", "horas": 30,
     "descripcion": "Limpieza, agrupaciones y uniones de tablas reales con pandas y numpy.",
     "ensena": ["pandas"], "requisitos": ["python"]},
    {"id": "visualizacion-datos", "nombre": "Visualización y storytelling", "nivel": "intermedio", "horas": 16,
     "descripcion": "Gráficos con matplotlib y seaborn, y cómo contar un hallazgo con ellos.",
     "ensena": ["visualizacion"], "requisitos": ["pandas"]},
    {"id": "machine-learning", "nombre": "Machine learning con scikit-learn", "nivel": "intermedio", "horas": 40,
     "descripcion": "Regresión, clasificación, validación cruzada y métricas de error.",
     "ensena": ["ml"], "requisitos": ["pandas", "estadistica"]},
    {"id": "deep-learning", "nombre": "Deep learning con PyTorch", "nivel": "avanzado", "horas": 45,
     "descripcion": "Redes neuronales, entrenamiento por lotes, visión y texto.",
     "ensena": ["deep"], "requisitos": ["ml"]},
    {"id": "mlops-produccion", "nombre": "Modelos en producción", "nivel": "avanzado", "horas": 30,
     "descripcion": "Empaquetado, servicio de predicciones, monitoreo y reentrenamiento.",
     "ensena": ["mlops"], "requisitos": ["ml", "git"]},
    {"id": "nube-despliegue", "nombre": "Despliegue en la nube", "nivel": "intermedio", "horas": 20,
     "descripcion": "Contenedores, variables de entorno y publicación de un servicio en la nube.",
     "ensena": ["nube"], "requisitos": ["git"]},
    {"id": "html-css", "nombre": "HTML y CSS", "nivel": "básico", "horas": 20,
     "descripcion": "Estructura de una página, maquetación responsiva y accesibilidad básica.",
     "ensena": ["html"], "requisitos": []},
    {"id": "javascript-moderno", "nombre": "JavaScript moderno", "nivel": "básico", "horas": 30,
     "descripcion": "DOM, eventos, módulos, promesas y consumo de APIs desde el navegador.",
     "ensena": ["js"], "requisitos": ["html"]},
    {"id": "react-interfaces", "nombre": "Interfaces con React", "nivel": "intermedio", "horas": 35,
     "descripcion": "Componentes, estado, efectos y rutas de una aplicación de una sola página.",
     "ensena": ["react"], "requisitos": ["js"]},
    {"id": "backend-apis", "nombre": "APIs con Node y Express", "nivel": "intermedio", "horas": 30,
     "descripcion": "Rutas, autenticación, validación y conexión de una API con su base de datos.",
     "ensena": ["backend"], "requisitos": ["js", "sql"]},
    {"id": "seguridad-web", "nombre": "Seguridad para aplicaciones", "nivel": "intermedio", "horas": 15,
     "descripcion": "Inyección, sesiones, cifrado y errores frecuentes al publicar una aplicación.",
     "ensena": ["seguridad"], "requisitos": ["html"]},
]
CATALOG = {c["id"]: c for c in COURSES}

GOALS = {
    "data-science": {"nombre": "Aprender Data Science",
                     "descripcion": "analizar datos reales y entrenar mis primeros modelos",
                     "requiere": ["python", "estadistica", "pandas", "visualizacion", "ml"]},
    "ingenieria-ml": {"nombre": "Ser ingeniero de machine learning",
                      "descripcion": "entrenar modelos y dejarlos funcionando en producción",
                      "requiere": ["python", "pandas", "ml", "deep", "mlops"]},
    "desarrollo-web": {"nombre": "Ser desarrollador web",
                       "descripcion": "construir y publicar aplicaciones web completas",
                       "requiere": ["html", "js", "react", "backend", "nube"]},
}

PROFILES = {
    "ana": {"nombre": "Ana", "rol": "Analista de marketing", "horas_semana": 6,
            "descripcion": "Ana lleva tres años en marketing. Usa hojas de cálculo todos los días y acaba de terminar su primer curso de programación.",
            "habilidades": ["fundamentos"], "completados": ["programacion-cero"]},
    "bruno": {"nombre": "Bruno", "rol": "Soporte técnico", "horas_semana": 10,
              "descripcion": "Bruno atiende incidencias de TI. No ha programado nunca, pero tiene diez horas libres a la semana.",
              "habilidades": [], "completados": []},
    "carla": {"nombre": "Carla", "rol": "Desarrolladora junior", "horas_semana": 4,
              "descripcion": "Carla programa en Python en su trabajo, versiona con Git y consulta bases de datos con SQL. Dispone de poco tiempo.",
              "habilidades": ["fundamentos", "python", "git", "sql"],
              "completados": ["programacion-cero", "python-basico", "git-github", "sql-datos"]},
}

# La lista de habilidades da más señal que la prosa adicional (ver medición de las nueve rutas).
INSTRUCTIONS = ("Which course should this student take next to reach the `objetivo`? Prefer a course that "
                "teaches a skill listed in `le_falta`, that fits the student's current level, and that the "
                "student can finish with the time available. Ignore courses unrelated to the goal.")


def describe(course):
    """Criterio compacto para el modelo; la descripción completa queda en el catálogo visible."""
    skills = ", ".join(SKILLS[s] for s in course["ensena"])
    return f"Enseña {skills}. {course['nombre']}, nivel {course['nivel']}, {course['horas']} horas."


def public(course):
    return {**course, "ensena_nombres": [SKILLS[s] for s in course["ensena"]],
            "requisitos_nombres": [SKILLS[s] for s in course["requisitos"]]}


def question_for(candidates):
    return {"siguiente": {"type": "choice", "instructions": INSTRUCTIONS,
                          "criteria": {c["id"]: describe(c) for c in candidates}}}


def probabilities(answer, ids):
    """El modelo devuelve la distribución en el orden de los criterios; se empareja por posición."""
    values = list(answer["probabilities"].values())
    if len(values) != len(ids) or any(not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1
                                      for p in values):
        raise ValueError("Distribución inválida de cursos")
    if abs(sum(values) - 1) > .02:
        raise ValueError("La distribución no suma 1")
    return dict(zip(ids, values))


class Roadmap:
    """Estado del estudiante y ruta construida hasta ahora."""

    def __init__(self, goal="data-science", profile="ana"):
        if goal not in GOALS:
            raise ValueError(f"Objetivo desconocido: {goal}")
        if profile not in PROFILES:
            raise ValueError(f"Perfil desconocido: {profile}")
        self.goal, self.profile = goal, profile
        student = PROFILES[profile]
        self.skills = list(student["habilidades"])
        self.taken = list(student["completados"])
        self.hours = 0
        self.history = []
        self.done, self.reason = False, ""
        self.finish_if_over()

    @property
    def missing(self):
        return [s for s in GOALS[self.goal]["requiere"] if s not in self.skills]

    def required(self):
        """Lo que falta, incluidas las habilidades que solo sirven para desbloquear otra.

        Laya elige bien el curso siguiente, pero no planifica dos pasos: sin esto nunca tomaba Git,
        y sin Git no llegaba a «Modelos en producción» (medido: 4 de las 9 rutas se quedaban sin
        objetivo, frente a 9 de 9). Encadenar prerrequisitos es una regla, no una decisión.
        """
        needed, index = list(self.missing), 0
        while index < len(needed):
            skill, index = needed[index], index + 1
            options = [c for c in COURSES if skill in c["ensena"] and c["id"] not in self.taken]
            if not options:
                continue
            # La vía más barata: el curso al que le faltan menos prerrequisitos.
            cheapest = min(options, key=lambda c: sum(s not in self.skills for s in c["requisitos"]))
            needed += [s for s in cheapest["requisitos"] if s not in self.skills and s not in needed]
        return needed

    def candidates(self):
        return [c for c in COURSES if c["id"] not in self.taken and all(s in self.skills for s in c["requisitos"])]

    def state(self):
        """Habilidades relevantes y progreso; los candidatos llegan por separado."""
        return {"le_falta": [SKILLS[s] for s in self.required()],
                "ya_sabe": [SKILLS[s] for s in self.skills] or ["nada todavía"],
                "cursos_completados": [CATALOG[c]["nombre"] for c in self.taken] or ["ninguno"]}

    def finish_if_over(self):
        if not self.missing:
            self.done, self.reason = True, "Objetivo alcanzado"
        elif not self.candidates():
            self.done, self.reason = True, "No quedan cursos disponibles"
        elif len(self.history) >= MAX_STEPS:
            self.done, self.reason = True, "Demasiados pasos"

    def step(self, predict):
        """Una decisión: estado → candidatos → modelo → curso → estado nuevo."""
        if self.done:
            raise LookupError("La ruta ya está terminada; reiníciala para construir otra.")
        candidates = self.candidates()
        state = self.state()
        started = time.perf_counter()
        answer = predict(state, question_for(candidates))["answers"]["siguiente"]
        elapsed = time.perf_counter() - started
        ids = [c["id"] for c in candidates]
        distribution = probabilities(answer, ids)
        chosen = answer["choice"]
        if chosen not in distribution:
            raise ValueError(f"Curso fuera de los candidatos: {chosen}")
        confidence = answer["confidence"]
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Confianza inválida")
        return self.apply(CATALOG[chosen], state, candidates, distribution, confidence, elapsed)

    def apply(self, course, state, candidates, distribution, confidence, elapsed):
        student = PROFILES[self.profile]
        # Útil incluye desbloquear: «Git y GitHub» no está en ningún objetivo, pero abre «Modelos en producción».
        needed = [s for s in course["ensena"] if s in self.required()]
        self.taken.append(course["id"])
        self.skills += [s for s in course["ensena"] if s not in self.skills]
        self.hours += course["horas"]
        record = {"paso": len(self.history) + 1, "curso": course["id"], "nombre": course["nombre"],
                  "horas": course["horas"], "nivel": course["nivel"],
                  "aporta": [SKILLS[s] for s in needed],
                  "gana": [SKILLS[s] for s in course["ensena"]],
                  "util": bool(needed),
                  "confianza": round(100 * confidence, 1),
                  "probabilidades": {k: round(v, 4) for k, v in
                                     sorted(distribution.items(), key=lambda kv: -kv[1])},
                  "candidatos": [{"id": c["id"], "nombre": c["nombre"], "nivel": c["nivel"], "horas": c["horas"],
                                  "texto": describe(c)} for c in candidates],
                  "estado": state, "elapsed": elapsed,
                  "restante": [SKILLS[s] for s in self.missing],
                  "horas_totales": self.hours,
                  "semanas": round(self.hours / student["horas_semana"], 1)}
        self.history.append(record)
        self.finish_if_over()
        return record

    def view(self):
        """Todo lo que dibuja la interfaz, en tipos que JSON entiende."""
        student = PROFILES[self.profile]
        return {"objetivo": self.goal, "perfil": self.profile,
                "habilidades": [{"id": s, "nombre": SKILLS[s]} for s in self.skills],
                "completados": self.taken, "ruta": [h["curso"] for h in self.history],
                "falta": [{"id": s, "nombre": SKILLS[s]} for s in self.missing],
                "requiere": GOALS[self.goal]["requiere"],
                "horas": self.hours, "semanas": round(self.hours / student["horas_semana"], 1),
                "done": self.done, "reason": self.reason,
                "candidatos": [c["id"] for c in self.candidates()],
                "estado": self.state(), "history": self.history}
