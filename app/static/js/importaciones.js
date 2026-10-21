/* Estado de importación confirmado por el servidor y recuperación de su consulta. */
'use strict';

function initImportStatus(doc = document, win = window) {
    const box = doc.getElementById('import-status');
    const message = doc.getElementById('import-status-message');
    if (!box || !message || !box.dataset.statusUrl) return null;
    let intentos = 0;
    let busy = false;
    let detenido = false;
    let temporizador;
    const retry = doc.createElement('button');
    retry.id = 'import-status-retry'; retry.type = 'button'; retry.className = 'btn btn-outline';
    retry.textContent = 'Volver a consultar'; retry.hidden = true;
    const refresh = doc.createElement('button');
    refresh.id = 'import-status-refresh'; refresh.type = 'button'; refresh.className = 'btn btn-outline';
    refresh.textContent = 'Actualizar vista'; refresh.hidden = true;
    box.append(retry, refresh);

    function mostrar(texto, tipo, ocupado = false) {
        message.textContent = texto;
        message.setAttribute('role', tipo === 'error' || tipo === 'warning' ? 'alert' : 'status');
        box.classList.remove('alert-error', 'alert-warning', 'alert-success');
        if (tipo !== 'info') box.classList.add('alert', 'alert-' + tipo);
        box.setAttribute('aria-busy', String(ocupado));
    }

    function actualizarVista() {
        const destino = new URL(win.location.href);
        destino.searchParams.delete('importacion_id');
        win.location.replace(destino.toString());
    }

    function programar(demora) {
        if (intentos >= 150) {
            mostrar('No se pudo confirmar el estado de la importación en el tiempo previsto. Vuelve a consultar para comprobar el resultado; no cargues el archivo otra vez.', 'warning');
            retry.hidden = false;
            return;
        }
        temporizador = win.setTimeout(consultar, demora);
    }

    function completar(resultado) {
        const partes = [];
        const contadores = { nuevos: 'aprendices nuevos', actualizados: 'aprendices actualizados', juicios_nuevos: 'juicios evaluativos incorporados', juicios_actualizados: 'juicios evaluativos actualizados' };
        for (const [campo, etiqueta] of Object.entries(contadores)) {
            if (Number.isInteger(resultado[campo]) && resultado[campo] > 0) partes.push(`${resultado[campo]} ${etiqueta}`);
        }
        if (Number.isInteger(resultado.juicios_repetidos) && resultado.juicios_repetidos > 0) {
            partes.push(`${resultado.juicios_repetidos} ${resultado.juicios_nuevos || resultado.juicios_actualizados ? 'juicios ya estaban en el historial' : 'juicios evaluativos verificados y conservados al día'}`);
        }
        const detalle = partes.length ? partes.join(', ') : 'Datos procesados correctamente';
        const advertencias = Array.isArray(resultado.advertencias) ? resultado.advertencias.filter(texto => typeof texto === 'string' && texto.trim()) : [];
        detenido = true;
        if (advertencias.length) {
            mostrar(`Importación completada: ${detalle}. Advertencias: ${advertencias.join(' ')} Puedes actualizar la vista cuando termines de leerlas.`, 'warning');
            refresh.hidden = false;
        } else {
            mostrar(`Importación completada con éxito: ${detalle}. Actualizando vista…`, 'success');
            temporizador = win.setTimeout(actualizarVista, 1200);
        }
    }

    async function consultar() {
        if (busy || detenido) return;
        win.clearTimeout(temporizador);
        busy = true; retry.disabled = true; retry.hidden = true;
        intentos++;
        box.setAttribute('aria-busy', 'true');
        const controller = new win.AbortController();
        const limite = win.setTimeout(function () { controller.abort(); }, 15000);
        try {
            const respuesta = await win.fetch(box.dataset.statusUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: controller.signal });
            if (respuesta.redirected || !respuesta.ok) {
                const error = new Error('No se pudo consultar el estado de la importación.');
                error.status = respuesta.redirected ? 401 : respuesta.status;
                throw error;
            }
            let job;
            try { job = await respuesta.json(); }
            catch (_) { throw new Error('La respuesta del servidor no es válida.'); }
            if (!job || !['encolado', 'procesando', 'completado', 'error'].includes(job.estado)) throw new Error('La respuesta del servidor no es válida.');
            if (job.estado === 'completado') {
                completar(job.resultado || {});
            } else if (job.estado === 'error') {
                detenido = true;
                mostrar('La importación no se pudo completar: ' + (job.error || 'revisa el archivo o consulta al administrador.'), 'error');
                refresh.hidden = false;
            } else {
                mostrar(job.estado === 'procesando' ? 'El sistema está leyendo y guardando el reporte. No vuelvas a enviarlo; puedes seguir navegando por el panel.' : 'El reporte está en cola. Puedes seguir navegando mientras se procesa.', 'info', true);
                programar(2000);
            }
        } catch (error) {
            if (error.status === 401 || error.status === 403) {
                detenido = true;
                mostrar('La sesión terminó o ya no tienes acceso para consultar la importación. Actualiza la vista para ingresar de nuevo y comprobar el resultado.', 'error');
                refresh.hidden = false;
            } else {
                const detalle = controller.signal.aborted ? 'Se agotó el tiempo de espera al consultar la importación.' : error.message === 'La respuesta del servidor no es válida.' ? error.message : 'No se pudo consultar el estado de la importación.';
                mostrar(detalle + ' Volveremos a consultar; también puedes reintentar. No cargues el archivo nuevamente hasta comprobar el resultado.', 'error');
                retry.hidden = false;
                programar(4000);
            }
        } finally {
            win.clearTimeout(limite);
            busy = false; retry.disabled = false;
        }
    }

    retry.addEventListener('click', function () { intentos = 0; return consultar(); });
    refresh.addEventListener('click', actualizarVista);
    return { consultar, ready: consultar() };
}

if (typeof module !== 'undefined' && module.exports) module.exports = { initImportStatus };
if (typeof window !== 'undefined' && typeof document !== 'undefined') initImportStatus(document, window);
