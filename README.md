# 👨‍🏫 Panel de Instructores — Sistema Integral de Gestión Pedagógica y Analítica Académica SENA

[![Python Version](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-v3.0%2B-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18%20(Port%205434)-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Memurai%2FRedis-Port%206380-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io)
[![Formato GPFI--F--134](https://img.shields.io/badge/SENA-GPFI--F--134%20Planeaci%C3%B3n-39A900?style=for-the-badge)](https://www.sena.edu.co)
[![Gamification](https://img.shields.io/badge/Gamification-Insignias%20%26%20Rankings-FFD700?style=for-the-badge)](docs/)
[![Architecture](https://img.shields.io/badge/Architecture-Clean%20%2F%20Worker%20Tasks-FF6B6B?style=for-the-badge)](docs/)

> Plataforma tecnológica para instructores del **SENA**, orientada al seguimiento pedagógico integral, planeación curricular oficial (**GPFI-F-134**), sincronización de juicios evaluativos (**SOFIA Plus**), alerta temprana de deserción, observador digital y gamificación motivacional del aula.

---

## 📋 Tabla de Contenido
- [Visión del Sistema](#-visión-del-sistema)
- [Capacidades del Ecosistema](#-capacidades-del-ecosistema)
- [Ciclo de Desarrollo del Software (SDLC)](#-ciclo-de-desarrollo-del-software-sdlc)
  - [Fase 1: Contexto Pedagógico y Marco Normativo SENA](#fase-1-contexto-pedagógico-y-marco-normativo-sena)
  - [Fase 2: Arquitectura del Sistema y Procesamiento Asíncrono](#fase-2-arquitectura-del-sistema-y-procesamiento-asíncrono)
  - [Fase 3: Implementación y Tecnologías](#fase-3-implementación-y-tecnologías)
  - [Fase 4: Aseguramiento de Calidad y Pruebas](#fase-4-aseguramiento-de-calidad-y-pruebas)
  - [Fase 5: Despliegue y Orquestación](#fase-5-despliegue-y-orquestación)
  - [Fase 6: Monitoreo, Alertas y Mantenimiento](#fase-6-monitoreo-alertas-y-mantenimiento)
- [Diagramas del Proyecto](#-diagramas-del-proyecto)
  - [Diagrama de Arquitectura con Worker Asíncrono](#diagrama-de-arquitectura-con-worker-asíncrono)
  - [Diagrama de Secuencia: Ingesta de Reporte SOFIA Plus y Alerta de Deserción](#diagrama-de-secuencia-ingesta-de-reporte-sofia-plus-y-alerta-de-deserción)
  - [Diagrama Entidad-Relación Pedagógico (ERD)](#diagrama-entidad-relación-pedagógico-erd)
- [Estructura del Repositorio](#-estructura-del-repositorio)
- [Guía de Arranque Rápido](#-guía-de-arranque-rápido)
- [Testing y Verificación](#-testing-y-verificación)
- [Licencia Institucional](#-licencia-institucional)

---

## 🎯 Visión del Sistema

La labor del instructor SENA combina la docencia técnica con una alta carga operativa documental: diligenciamiento de la planeación pedagógica (**Formato GPFI-F-134**), registro de novedades en el observador, control de asistencia, seguimiento a compromisos de comités de evaluación y sincronización de juicios evaluativos en **SOFIA Plus**.

El **Panel de Instructores** centraliza y automatiza estas actividades en una suite interactiva:
1. **Ingesta Automática de Juicios**: Procesamiento inteligente de hojas de cálculo exportadas de SOFIA Plus sin necesidad de digitación manual.
2. **Sistema de Alerta Temprana de Deserción**: Algoritmo heurístico que detecta patrones de inasistencia continua, atraso en evidencias críticas y bajo rendimiento antes de que el aprendiz abandone la formación.
3. **Observador Digital del Aprendiz**: Registro inmutable de anotaciones positivas, llamados de atención y actas de compromiso con trazabilidad por corte.
4. **Gamificación y Cultura de Ambiente**: Sistema de insignias al mérito, estrellas de entrega a tiempo y organización de responsabilidades (aseo y cuidado de equipos).

---

## 🌟 Capacidades del Ecosistema

- 📑 **Planeación Pedagógica GPFI-F-134**: Mapeo directo de actividades de aprendizaje, técnicas didácticas activas, ambientes y criterios de evaluación.
- ⚡ **Ingesta Inteligente de Reportes Excel**: Procesador masivo de archivos `.xls`/`.xlsx` de juicios evaluativos de SOFIA Plus con detección de inconsistencias.
- 🚨 **Módulo de Alertas Preventivas**: Semáforo por aprendiz (*Riesgo Bajo*, *Riesgo Medio*, *Riesgo Crítico de Deserción*).
- 🏆 **Gamificación del Aprendizaje**: Ranking del grupo, cuadro de honor e insignias coleccionables para incentivar la excelencia técnica y el trabajo colaborativo.
- 🧹 **Organización y Disciplina de Taller**: Gestión de roles de ambiente (responsables de inventario, orden y aseo por semana).

---

## 🔄 Ciclo de Desarrollo del Software (SDLC)

```mermaid
flowchart LR
    A["1. Requisitos<br/>Guía SENA GPFI-134"] --> B["2. Arquitectura<br/>Flask + Async Worker"]
    B --> C["3. Codificación<br/>Python + Jinja2 + JS"]
    C --> D["4. Verificación<br/>Pytest + Fixtures"]
    D --> E["5. Operación<br/>Windows / Coolify"]
    E --> F["6. Analítica<br/>Prevención Deserción"]
    F -. Ajuste Pedagógico .-> A
```

### Fase 1: Contexto Pedagógico y Marco Normativo SENA
- **Reglamento del Aprendiz (Acuerdo 007 de 2012)**: Tipificación de faltas académicas y disciplinarias, causales de deserción y debido proceso.
- **Formato Oficial GPFI-F-134**: Modelado relacional de la estructura pedagógica de proyectos formativos.
- **Requisitos No Funcionales (NFR)**:
  - Procesamiento en background de archivos Excel de más de 1,000 registros en menos de 5 segundos.
  - Cero fallos silenciosos en el worker de sincronización (`stdout logging` prioritario).

### Fase 2: Arquitectura del Sistema y Procesamiento Asíncrono
- **Arquitectura Híbrida**: Web Server Flask sincrónico + `worker.py` dedicado a tareas pesadas de ingestión y cálculo de rankings.
- **Capa de Dominio y Servicios**: Separación de la lógica de alertas en servicios especializados (`alertas_service.py`, `evaluacion_service.py`).
- **Seguridad**: Prevención estricta de llaves secretas efímeras en producción y hashing de contraseñas con bcrypt.

### Fase 3: Implementación y Tecnologías
- **Backend Core**: Python 3.11, Flask 3.0, SQLAlchemy 2.0.
- **Procesamiento de Datos**: Pandas / OpenPyXL para lectura analítica de planillas institucionales.
- **Persistencia y Mensajería**: PostgreSQL 18 local (puerto `5434`), Memurai/Redis (puerto `6380`).

### Fase 4: Aseguramiento de Calidad y Pruebas
- Pruebas unitarias de cálculo de horas de inasistencia acumuladas.
- Pruebas de integración sobre simulación de reportes reales de juicios evaluativos (`Reporte de Juicios Evaluativos.xls`).

### Fase 5: Despliegue y Orquestación
- Compatibilidad dual: Scripts para Windows nativo (`start-windows.ps1`) y despliegue contenerizado (`Dockerfile` + `docker-entrypoint.sh`).

### Fase 6: Monitoreo, Alertas y Mantenimiento
- Envío automático de notificaciones a instructores voceros y comités de evaluación.

---

## 📊 Diagramas del Proyecto

### Diagrama de Arquitectura con Worker Asíncrono

```mermaid
graph TD
    subgraph UI ["Capa de Interfaz (Jinja2 + Tailwind + Web Components)"]
        DashboardView["📊 Tablero de Control de Fichas"]
        ObservadorView["📝 Bitácora del Observador"]
        AlertasView["🚨 Panel de Alertas Tempranas"]
        ImportView["📥 Carga de Excel SOFIA Plus"]
    end

    subgraph ServerApp ["Servidor Web (Flask WSGI | wsgi.py)"]
        RouterLayer["🚦 Controladores de Rutas (/fichas, /aprendices)"]
        AuthFilter["🔐 Autenticación & Control de Roles"]
        SyncManager["🔄 Coordinador de Tareas"]
    end

    subgraph AsyncWorker ["Motor de Tareas en Segundo Plano (worker.py)"]
        ExcelParser["📑 Ingestor Excel / Pandas"]
        RiskEngine["🧠 Motor de Riesgo de Deserción"]
        GamificationEngine["🏆 Calculador de Rankings & Estrellas"]
    end

    subgraph InfrastructureLayer ["Infraestructura & Datos"]
        Database["🐘 PostgreSQL 18 (Puerto 5434)<br/>Schema: panel_instructores"]
        RedisQueue["⚡ Redis / Memurai (Puerto 6380)<br/>Cola de Tareas & Caché"]
    end

    UI -->|HTTP / Peticiones Web| ServerApp
    ServerApp --> AuthFilter
    AuthFilter --> RouterLayer
    RouterLayer --> Database
    SyncManager -->|Publica tarea a la cola| RedisQueue
    RedisQueue -->|Consume tarea pesada| AsyncWorker
    AsyncWorker --> ExcelParser
    AsyncWorker --> RiskEngine
    AsyncWorker --> GamificationEngine
    AsyncWorker --> Database
```

### Diagrama de Secuencia: Ingesta de Reporte SOFIA Plus y Alerta de Deserción

```mermaid
sequenceDiagram
    autonumber
    actor Instructor as Instructor Técnico
    participant Web as Panel Web (Flask)
    participant Worker as Async Worker (Python)
    participant DB as PostgreSQL (5434)

    Instructor->>Web: Carga archivo "Reporte Juicios Evaluativos.xls"
    Web->>Web: Valida formato MIME y guarda en temporal
    Web->>Worker: Encola tarea ingest_sofia_report(file_id)
    Web-->>Instructor: 202 Accepted (Procesamiento iniciado en segundo plano)
    
    Worker->>Worker: Parsea filas de aprendices, RAPs y estados ("A", "D")
    Worker->>DB: Actualiza juicios evaluativos por aprendiz
    Worker->>Worker: Evalúa heurística de riesgo: inasistencias > 3 consecutivas o > 2 RAPs "D"
    
    alt Riesgo Crítico Detectado
        Worker->>DB: Inserta alerta tipo "RIESGO_DESERCION_ALTO"
        Worker->>DB: Registra nota preventiva en observador del aprendiz
    end
    
    Worker-->>Web: Tarea completada con éxito
    Web-->>Instructor: Notificación en vivo: "Planilla procesada (30 aprendices actualizados, 2 alertas generadas)"
```

### Diagrama Entidad-Relación Pedagógico (ERD)

```mermaid
erDiagram
    INSTRUCTOR ||--o{ FICHA_INSTRUCTOR : lidera
    FICHA ||--o{ FICHA_INSTRUCTOR : asigna
    FICHA ||--o{ APRENDIZ : matricula
    APRENDIZ ||--o{ ASISTENCIA : registra
    APRENDIZ ||--o{ JUICIO_EVALUATIVO : obtiene
    APRENDIZ ||--o{ OBSERVADOR_ANOTACION : posee
    APRENDIZ ||--o{ ALERTA : dispara
    APRENDIZ ||--o{ INSIGNIA_APRENDIZ : gana

    INSTRUCTOR {
        uuid id PK
        string documento
        string nombre_completo
        string correo_sena
        string rol "VOCERO|TECNICO|TRANSVERSAL"
    }

    FICHA {
        uuid id PK
        string numero_ficha
        string programa_formacion
        string jornada
        string estado "LECTIVA|PRODUCTIVA"
    }

    APRENDIZ {
        uuid id PK
        uuid ficha_id FK
        string documento
        string nombres
        string apellidos
        string estado "ACTIVO|CONDICIONADO|DESERTOR"
        int total_estrellas
    }

    JUICIO_EVALUATIVO {
        uuid id PK
        uuid aprendiz_id FK
        string codigo_rap
        string estado_juicio "APROBADO|DEFICIENTE|PENDIENTE"
        date fecha_juicio
        string origen "SOFIA_PLUS_IMPORT|MANUAL"
    }

    OBSERVADOR_ANOTACION {
        uuid id PK
        uuid aprendiz_id FK
        uuid instructor_id FK
        date fecha
        string tipo "FELICITACION|LLAMADO_ATENCION|COMPROMISO"
        text descripcion
        boolean firmado_aprendiz
    }

    ALERTA {
        uuid id PK
        uuid aprendiz_id FK
        string nivel_severidad "BAJA|MEDIA|CRITICA"
        string motivo
        date fecha_deteccion
        boolean resuelta
    }
```

---

## 📂 Estructura del Repositorio

```text
panel de instructores/
├── app/                      # Núcleo modular de la aplicación
│   ├── models/               # Entidades SQLAlchemy (Aprendiz, Juicio, Alerta, etc.)
│   ├── routes/               # Enrutadores y controladores de vistas
│   ├── services/             # Lógica de cálculo de deserción y rankings
│   ├── static/               # Hojas de estilo, logos institucionales y scripts
│   └── templates/            # Vistas Jinja2 (dashboard, observador, planeación)
├── docs/                     # Especificaciones pedagógicas y guías
├── config.py                 # Configuración canónica y lectura segura de entorno
├── worker.py                 # Worker asíncrono para ingesta pesada de Excel
├── wsgi.py                   # Punto de entrada WSGI para servidores web
├── seed_admin.py             # Script de inicialización de usuarios maestros
├── start-windows.ps1         # Script oficial de arranque local Windows nativo
├── requirements.txt          # Dependencias Python
└── README.md                 # Este documento
```

---

## 🚀 Guía de Arranque Rápido

### Prerrequisitos
- **Windows 10 / 11** nativo o Linux.
- **Python 3.11+**.
- **PostgreSQL 18** en puerto `5434` (schema `panel_instructores`).
- **Memurai / Redis** en puerto `6380`.

### 1. Clonar e Instalar Dependencias
```powershell
git clone https://github.com/miuguelt/panel-de-instructores.git
cd "panel de instructores"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configurar Variables de Entorno
Copie `.env.example` a `.env` y ajuste sus parámetros locales:
```ini
FLASK_ENV=development
SECRET_KEY=clave_aleatoria_segura_desarrollo
DATABASE_URL=<TU_DSN_POSTGRESQL>
REDIS_URL=redis://127.0.0.1:6380/0
PORT=5000
```

### 3. Iniciar el Servidor Web y el Worker
```powershell
# En Windows nativo:
powershell -ExecutionPolicy Bypass -File .\start-windows.ps1

# O manualmente en dos consolas:
# Consola 1 (Web):
python wsgi.py
# Consola 2 (Worker Asíncrono):
python worker.py
```

Abra su navegador en: `http://127.0.0.1:5000`

---

## 🧪 Testing y Verificación

```powershell
# Ejecución de pruebas unitarias
pytest

# Validación de modelos pedagógicos
pytest tests/test_models.py
```

---

## 🏛️ Licencia Institucional

Desarrollado para el **Cuerpo de Instructores del SENA**.
Herramienta de innovación pedagógica bajo lineamientos institucionales.
