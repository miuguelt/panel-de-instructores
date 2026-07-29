"""Importación de plantillas de aprendices y reportes oficiales de juicios SENA."""

from datetime import datetime, date, timedelta
import hashlib
import io
import re
import unicodedata

import openpyxl
from sqlalchemy import or_

from app import db
from app.models.alertas import ConfiguracionAlertas
from app.models.aprendiz import Aprendiz
from app.models.aseo import ConfiguracionAseo
from app.models.asistencia import SesionAsistencia
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.models.juicio import JuicioEvaluativo, JuicioEvaluativoInstructor
from app.models.ranking import ConfiguracionRanking

_TECHNICAL_KEYWORDS = (
    'software', 'programac', 'desarrollo de software', 'desarrollar la solucion',
    'requisitos tecnic', 'propuesta tecnic', 'estandares tecnic',
    'calidad del servicio de software', 'base de datos', 'base datos',
    'proyectos de construcc', 'medir construcc', 'planos', 'dibujo', 'induccion'
)

_INGLES_KEYWORDS = (
    'ingl', 'english', 'lengua inglesa',
)

_TRANSVERSAL_KEYWORDS = (
    'comunicac', 'expres', 'redacci', 'ortograf',
    'trabajo en equipo', 'colaborativ',
    'herramientas informatic', 'utilizar herramientas',
    'razonar cuantitativ', 'matem', 'logica',
    'aprendizaje autonom', 'autogesti',
    'etic', 'valores', 'ciudadan', 'convivencia', 'derechos fundamental', 'cultura de paz', 'enrique low',
    'lectura critica', 'interpretaci',
    'emprend', 'innovaci',
    'seguridad y salud', 'salud ocupacional', 'bienestar', 'actividad fisica', 'habitos salud',
    'ciencias natural',
    'investigaci',
    'recursos financier',
    'atender client',
    'medio ambient', 'ambiental',
    'etapa practica'
)


class ErrorImportacion(ValueError):
    """Error legible para el usuario al validar un archivo de importación."""


def _texto(valor):
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return re.sub(r'\s+', ' ', str(valor).strip())


def _clave(valor):
    texto = unicodedata.normalize('NFKD', _texto(valor))
    return ''.join(c for c in texto if not unicodedata.combining(c)).lower()


def clasificar_competencia(nombre_competencia):
    if not nombre_competencia:
        return 'tecnica'
    texto = _clave(nombre_competencia)
    for kw in _TECHNICAL_KEYWORDS:
        if kw in texto:
            return 'tecnica'
    for kw in _INGLES_KEYWORDS:
        if kw in texto:
            return 'ingles'
    for kw in _TRANSVERSAL_KEYWORDS:
        if kw in texto:
            return 'transversal'
    return 'tecnica'


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime.combine(valor, datetime.min.time())
    texto = _texto(valor)
    if not texto:
        return None
    if isinstance(valor, (int, float)) and float(valor) > 20000:
        return datetime(1899, 12, 30) + timedelta(days=float(valor))
    for formato in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y',
                    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    return None


def _metadata_fila(label, value, metadata):
    clave = _clave(label).replace(':', '')
    if clave == 'ficha de caracterizacion':
        metadata['codigo_ficha'] = _texto(value)
        return True
    elif clave in ('codigo', 'codigo programa', 'cogigo'):
        metadata['codigo_programa'] = _texto(value)
        return True
    elif 'denominacion' in clave:
        metadata['nombre_programa'] = _texto(value)
        return True
    elif 'fecha inicio' in clave:
        metadata['fecha_inicio'] = _fecha(value).date() if _fecha(value) else None
        return True
    elif 'fecha fin' in clave:
        metadata['fecha_fin'] = _fecha(value).date() if _fecha(value) else None
        return True
    return False


def _extraer_metadata(filas):
    """Lee las parejas etiqueta/valor aunque el formato cambie de columnas."""
    metadata = {}
    for fila in filas[:20]:
        for posicion, celda in enumerate(fila):
            if not _texto(celda):
                continue
            clave = _clave(celda).replace(':', '')
            if not (
                clave == 'ficha de caracterizacion'
                or clave in ('codigo', 'codigo programa', 'cogigo')
                or 'denominacion' in clave
                or 'fecha inicio' in clave
                or 'fecha fin' in clave
            ):
                continue

            valor = next(
                (candidato for candidato in fila[posicion + 1:] if _texto(candidato)),
                '',
            )
            _metadata_fila(celda, valor, metadata)
            break
    return metadata


def _estado_aprendiz(valor):
    estado = _clave(valor).upper().replace(' ', '_').replace('-', '_')
    return estado or 'EN_FORMACION'


def _parse_rows(rows):
    """Convierte filas tabulares en registros; soporta encabezados con tildes."""
    filas = [list(row) for row in rows]
    encabezado_idx = None
    indices = {}
    for i, fila in enumerate(filas):
        claves = {_clave(c): pos for pos, c in enumerate(fila) if _texto(c)}
        documento = next((k for k in claves if 'numero de documento' in k or k == 'documento'), None)
        if documento and any('nombre' == k for k in claves):
            encabezado_idx = i
            indices = claves
            break
    if encabezado_idx is None:
        # Plantilla simple: el encabezado es la primera fila.
        fila = filas[0] if filas else []
        indices = {_clave(c): pos for pos, c in enumerate(fila) if _texto(c)}
        encabezado_idx = 0

    def pos(*nombres):
        for nombre in nombres:
            if nombre in indices:
                return indices[nombre]
        for clave, valor in indices.items():
            if any(nombre in clave for nombre in nombres):
                return valor
        return None

    p_documento = pos('numero de documento', 'documento')
    p_nombre = pos('nombre')
    p_apellidos = pos('apellidos', 'apellido')
    p_tipo = pos('tipo de documento', 'tipo')
    p_estado = pos('estado')
    p_competencia = pos('competencia')
    p_resultado = pos('resultado de aprendizaje', 'resultado')
    p_juicio = pos('juicio de evaluacion', 'juicio evaluativo', 'juicio')
    p_fecha = pos('fecha y hora del juicio evaluativo', 'fecha juicio', 'fecha')
    p_funcionario = pos('funcionario que registro el juicio evaluativo', 'funcionario')

    registros = []
    for numero_fila, fila in enumerate(filas[encabezado_idx + 1:], start=encabezado_idx + 2):
        def get(posicion):
            return fila[posicion] if posicion is not None and posicion < len(fila) else ''

        documento = _texto(get(p_documento))
        if not documento or documento.lower() in ('none', 'nan'):
            continue
        registro = {
            'fila': numero_fila,
            'documento': documento,
            'nombre': _texto(get(p_nombre)),
            'apellidos': _texto(get(p_apellidos)),
            'tipo_documento': _texto(get(p_tipo)) or 'CC',
            'estado': _estado_aprendiz(get(p_estado)),
            'competencia': _texto(get(p_competencia)),
            'resultado_aprendizaje': _texto(get(p_resultado)),
            'juicio': _texto(get(p_juicio)),
            'fecha_fuente_texto': _texto(get(p_fecha)),
            'fecha_juicio': _fecha(get(p_fecha)),
            'funcionario_registro': _texto(get(p_funcionario)),
        }
        registros.append(registro)
    return registros


def _leer_archivo(archivo):
    contenido = archivo.read()
    extension = (archivo.filename or '').lower().rsplit('.', 1)[-1]
    if extension == 'xls':
        try:
            import xlrd
        except ImportError as exc:
            raise RuntimeError('Para cargar reportes .xls instala la dependencia xlrd==2.0.1.') from exc
        try:
            libro = xlrd.open_workbook(file_contents=contenido)
        except Exception as exc:
            raise ErrorImportacion(
                'El archivo .xls no es válido o está dañado.'
            ) from exc
        hoja = libro.sheet_by_index(0)
        filas = [hoja.row_values(i) for i in range(hoja.nrows)]
        return _extraer_metadata(filas), _parse_rows(filas)

    try:
        libro = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as exc:
        raise ErrorImportacion(
            'El archivo no es un Excel válido o está dañado.'
        ) from exc
    hoja = libro.active
    filas = list(hoja.iter_rows(values_only=True))
    metadata = _extraer_metadata(filas)
    libro.close()
    return metadata, _parse_rows(filas)


def _buscar_ficha(ficha_actual, metadata):
    codigo_ficha = metadata.get('codigo_ficha')
    codigo_programa = metadata.get('codigo_programa')
    # La ficha de caracterización es la identidad principal; el código del
    # programa solo se usa como respaldo para reportes incompletos.
    if codigo_ficha:
        encontrada = Ficha.query.filter(or_(
            Ficha.codigo == codigo_ficha, Ficha.codigo_ficha == codigo_ficha
        )).order_by(Ficha.id).first()
        if encontrada:
            return encontrada
        return ficha_actual
    if codigo_programa:
        encontrada = Ficha.query.filter(or_(
            Ficha.codigo == codigo_programa, Ficha.codigo_ficha == codigo_programa,
            Ficha.codigo_programa == codigo_programa
        )).order_by(Ficha.id).first()
        if encontrada:
            return encontrada
    return ficha_actual


def _asegurar_configuraciones(ficha):
    if not ConfiguracionAlertas.query.filter_by(ficha_id=ficha.id).first():
        db.session.add(ConfiguracionAlertas(ficha_id=ficha.id))
    if not ConfiguracionRanking.query.filter_by(ficha_id=ficha.id).first():
        db.session.add(ConfiguracionRanking(ficha_id=ficha.id))
    if not ConfiguracionAseo.query.filter_by(ficha_id=ficha.id).first():
        db.session.add(ConfiguracionAseo(ficha_id=ficha.id))


def _resolver_ficha(ficha_actual, metadata, instructor_id, crear_ficha):
    codigo_reporte = metadata.get('codigo_ficha')

    if ficha_actual is not None:
        codigos_actuales = {
            _texto(ficha_actual.codigo),
            _texto(ficha_actual.codigo_ficha),
        }
        codigos_actuales.discard('')
        if codigo_reporte and codigo_reporte not in codigos_actuales:
            raise ErrorImportacion(
                f'El reporte corresponde a la ficha {codigo_reporte}, '
                f'no a la ficha {ficha_actual.codigo}.'
            )
        _asegurar_configuraciones(ficha_actual)
        return ficha_actual, False

    if not crear_ficha:
        raise ErrorImportacion('No se indicó la ficha que recibirá la importación.')
    if not codigo_reporte:
        raise ErrorImportacion(
            'No se encontró “Ficha de Caracterización” en el reporte.'
        )
    if not metadata.get('nombre_programa'):
        raise ErrorImportacion('No se encontró “Denominación” en el reporte.')

    ficha = _buscar_ficha(None, metadata)
    if ficha:
        _asegurar_configuraciones(ficha)
        return ficha, False

    ficha = Ficha(
        codigo=codigo_reporte,
        codigo_ficha=codigo_reporte,
        codigo_programa=metadata.get('codigo_programa'),
        nombre_programa=metadata['nombre_programa'],
        instructor_id=instructor_id,
        fecha_inicio=metadata.get('fecha_inicio'),
        fecha_fin=metadata.get('fecha_fin'),
        duracion_productiva_meses=6,
    )
    db.session.add(ficha)
    db.session.flush()
    _asegurar_configuraciones(ficha)
    return ficha, True


def importar_archivo(archivo, ficha_actual, instructor_id, crear_ficha=False):
    metadata, registros = _leer_archivo(archivo)
    ficha, ficha_creada = _resolver_ficha(
        ficha_actual, metadata, instructor_id, crear_ficha
    )

    if metadata.get('codigo_ficha'):
        ficha.codigo = metadata['codigo_ficha']
        ficha.codigo_ficha = metadata['codigo_ficha']
    if metadata.get('codigo_programa'):
        ficha.codigo_programa = metadata['codigo_programa']
    for campo in ('nombre_programa', 'fecha_inicio', 'fecha_fin'):
        if metadata.get(campo):
            setattr(ficha, campo, metadata[campo])

    asociacion = FichaInstructor.query.filter_by(
        ficha_id=ficha.id, instructor_id=instructor_id
    ).first()
    if not asociacion:
        db.session.add(FichaInstructor(ficha_id=ficha.id, instructor_id=instructor_id))

    nuevos = actualizados = juicios_nuevos = juicios_repetidos = 0
    errores = []

    # Precarga en memoria para que cada fila se resuelva con O(1) lookups.
    # La importación oficial suele traer miles de filas; no conviene hacer un
    # round-trip a PostgreSQL por cada aprendiz o juicio.
    aprendices_db = {
        a.documento: a
        for a in Aprendiz.query.filter_by(ficha_id=ficha.id).all()
    }

    # Precalcular las huellas y consultar solo los juicios presentes en este
    # archivo. Se deduplican los parámetros del IN porque el reporte puede
    # repetir la misma evaluación.
    huellas_excel = []
    for registro in registros:
        if registro['competencia'] or registro['resultado_aprendizaje'] or registro['juicio']:
            partes = [
                str(ficha.id), registro['documento'], registro['competencia'],
                registro['resultado_aprendizaje'], registro['juicio'],
                (registro['fecha_juicio'].isoformat() if registro['fecha_juicio']
                 else registro['fecha_fuente_texto']), registro['funcionario_registro'],
            ]
            registro['huella_calc'] = hashlib.sha256(
                '|'.join(_texto(p) for p in partes).encode('utf-8')
            ).hexdigest()
            huellas_excel.append(registro['huella_calc'])

    huellas_excel = list(dict.fromkeys(huellas_excel))
    juicios_db = {
        j.huella: j
        for j in (
            JuicioEvaluativo.query
            .filter(JuicioEvaluativo.huella.in_(huellas_excel))
            .all()
            if huellas_excel else []
        )
    }

    # Primera pasada: preparar aprendices nuevos y actualizar los existentes.
    # Los nuevos se insertan con bulk_insert_mappings más abajo; crear objetos
    # ORM y hacer flush por fila vuelve la importación sensible a la latencia.
    aprendices_pendientes = {}
    registros_validos = []
    for registro in registros:
        documento = registro['documento']
        aprendiz = aprendices_db.get(documento)
        if not aprendiz:
            if not registro['nombre']:
                errores.append(
                    f"Fila {registro['fila']}: el documento {documento} no tiene nombre."
                )
                continue
            aprendiz = Aprendiz(
                documento=documento,
                nombre=registro['nombre'],
                apellidos=registro['apellidos'],
                tipo_documento=registro['tipo_documento'],
                estado=registro['estado'],
                ficha_id=ficha.id,
            )
            aprendices_pendientes[documento] = {
                'documento': documento,
                'nombre': registro['nombre'],
                'apellidos': registro['apellidos'],
                'tipo_documento': registro['tipo_documento'],
                'estado': registro['estado'],
                'ficha_id': ficha.id,
            }
            aprendices_db[documento] = aprendiz
            nuevos += 1
        else:
            cambios = False
            for campo in ('nombre', 'apellidos', 'tipo_documento', 'estado'):
                valor = registro[campo]
                if valor and getattr(aprendiz, campo) != valor:
                    setattr(aprendiz, campo, valor)
                    cambios = True
            if cambios:
                actualizados += 1
        registros_validos.append((registro, documento))

    if aprendices_pendientes:
        db.session.bulk_insert_mappings(
            Aprendiz,
            list(aprendices_pendientes.values()),
        )
        db.session.flush()
        aprendices_db.update({
            aprendiz.documento: aprendiz
            for aprendiz in Aprendiz.query.filter(
                Aprendiz.ficha_id == ficha.id,
                Aprendiz.documento.in_(list(aprendices_pendientes)),
            ).all()
        })

    # Segunda pasada: preparar todos los juicios para una inserción masiva.
    # Los duplicados dentro del mismo archivo se resuelven en memoria.
    juicios_pendientes = {}
    for registro, documento in registros_validos:
        if 'huella_calc' not in registro:
            continue
        huella = registro['huella_calc']
        if huella not in juicios_db and huella not in juicios_pendientes:
            aprendiz = aprendices_db[documento]
            juicios_pendientes[huella] = {
                'ficha_id': ficha.id,
                'aprendiz_id': aprendiz.id,
                'competencia': registro['competencia'],
                'tipo_competencia': clasificar_competencia(registro['competencia']),
                'resultado_aprendizaje': registro['resultado_aprendizaje'],
                'juicio': registro['juicio'],
                'fecha_juicio': registro['fecha_juicio'],
                'fecha_fuente_texto': registro['fecha_fuente_texto'],
                'funcionario_registro': registro['funcionario_registro'],
                'fuente_archivo': _texto(archivo.filename)[:255],
                'huella': huella,
                'importado_en': datetime.utcnow(),
            }
            juicios_nuevos += 1
        else:
            juicios_repetidos += 1

    if juicios_pendientes:
        db.session.bulk_insert_mappings(
            JuicioEvaluativo,
            list(juicios_pendientes.values()),
        )
        db.session.flush()
        # Recuperar una sola vez los IDs de los juicios nuevos y conservar la
        # misma forma de lookup para los ya existentes.
        huellas_consulta = list(juicios_pendientes) + list(juicios_db)
        juicios_db = {
            juicio.huella: juicio
            for juicio in JuicioEvaluativo.query.filter(
                JuicioEvaluativo.huella.in_(huellas_consulta)
            ).all()
        }

    # Consultar únicamente los vínculos relevantes. Antes se cargaba todo el
    # historial de juicios del instructor en cada importación.
    juicio_ids = {juicio.id for juicio in juicios_db.values() if juicio.id}
    vinculos_existentes = set()
    if juicio_ids:
        vinculos_existentes = {
            juicio_id
            for (juicio_id,) in (
                db.session.query(JuicioEvaluativoInstructor.juicio_id)
                .filter(
                    JuicioEvaluativoInstructor.instructor_id == instructor_id,
                    JuicioEvaluativoInstructor.juicio_id.in_(juicio_ids),
                )
                .all()
            )
        }

    vinculos_pendientes = [
        {
            'juicio_id': juicio.id,
            'instructor_id': instructor_id,
            'fecha_importacion': datetime.utcnow(),
        }
        for juicio in juicios_db.values()
        if juicio.id not in vinculos_existentes
    ]
    if vinculos_pendientes:
        db.session.bulk_insert_mappings(
            JuicioEvaluativoInstructor,
            vinculos_pendientes,
        )

    # Resolver las sesiones en una consulta, en lugar de ejecutar un SELECT
    # por cada fecha distinta del reporte.
    sesiones_creadas = 0
    fechas_unicas = sorted({
        registro['fecha_juicio'].date()
        for registro in registros
        if registro['fecha_juicio'] is not None
    })
    if fechas_unicas:
        fechas_existentes = {
            fecha
            for (fecha,) in (
                db.session.query(SesionAsistencia.fecha)
                .filter(
                    SesionAsistencia.ficha_id == ficha.id,
                    SesionAsistencia.fecha.in_(fechas_unicas),
                )
                .all()
            )
        }
        sesiones_pendientes = [
            {
                'ficha_id': ficha.id,
                'fecha': fecha_sesion,
                'observaciones': 'Creada automáticamente al importar juicios.',
                'creada_en': datetime.utcnow(),
            }
            for fecha_sesion in fechas_unicas
            if fecha_sesion not in fechas_existentes
        ]
        if sesiones_pendientes:
            db.session.bulk_insert_mappings(
                SesionAsistencia,
                sesiones_pendientes,
            )
            sesiones_creadas = len(sesiones_pendientes)

    return {
        'ficha': ficha, 'ficha_creada': ficha_creada,
        'metadata': metadata, 'nuevos': nuevos,
        'actualizados': actualizados, 'juicios_nuevos': juicios_nuevos,
        'juicios_repetidos': juicios_repetidos, 'errores': errores,
        'sesiones_creadas': sesiones_creadas,
    }
