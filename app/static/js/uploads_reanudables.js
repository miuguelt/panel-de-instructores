/* Transferencia por bloques: el servidor confirma el avance y el resultado. */
(function (raiz) {
  'use strict';

  function crearMotor(win, doc) {
    var memoria = {};
    var CLASES_PROGRESO = { panel: 'upload-progress', texto: 'upload-progress-text', relleno: 'upload-progress-fill' };

    // El motor reutiliza el panel canónico de cargas creado por uploads.js. Si
    // una integración aporta nodos sin clase se completan aquí: el progreso usa
    // siempre las clases del sistema, nunca estilos inline con colores.
    function asegurarClases(ui) {
      if (!ui) return;
      var pares = [['panel', CLASES_PROGRESO.panel], ['texto', CLASES_PROGRESO.texto], ['relleno', CLASES_PROGRESO.relleno]];
      for (var i = 0; i < pares.length; i += 1) {
        var nodo = ui[pares[i][0]];
        if (nodo && nodo.classList && typeof nodo.classList.add === 'function') nodo.classList.add(pares[i][1]);
      }
    }

    function pintarAvance(ui, porcentaje) {
      if (!ui || !ui.relleno) return;
      if (ui.relleno.classList && typeof ui.relleno.classList.add === 'function') {
        ui.relleno.classList.add(CLASES_PROGRESO.relleno);
      }
      ui.relleno.style.width = porcentaje + '%';
    }

    function mensaje(destino, instructor, aprendiz) {
      return destino.indexOf('/aprendiz/') === 0 ? aprendiz : instructor;
    }

    function leer(clave) {
      try { return JSON.parse(win.localStorage.getItem(clave) || 'null') || memoria[clave] || {}; }
      catch (_) { return memoria[clave] || {}; }
    }

    function guardar(clave, entrada) {
      memoria[clave] = entrada;
      try {
        if (entrada) win.localStorage.setItem(clave, JSON.stringify(entrada));
        else win.localStorage.removeItem(clave);
      } catch (_) { /* La carga también funciona cuando el navegador restringe el almacenamiento. */ }
    }

    async function huella(blob) {
      var bytes = await win.crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
      return Array.from(new Uint8Array(bytes), function (valor) { return valor.toString(16).padStart(2, '0'); }).join('');
    }

    function restaurar() {
      var formularios = doc.querySelectorAll('form[enctype="multipart/form-data"]');
      for (var i = 0; i < formularios.length; i += 1) {
        var form = formularios[i];
        var destino = new win.URL(form.action, win.location.href).pathname;
        var entrada = leer('adso:cargas:v1:' + destino);
        if (!entrada.archivos || !Object.keys(entrada.archivos).length || form.querySelector('.upload-resume-notice')) continue;
        var aviso = doc.createElement('p'); aviso.className = 'upload-resume-notice';
        aviso.setAttribute('role', 'status');
        aviso.textContent = mensaje(destino,
          'Tiene una carga pendiente. Seleccione el archivo original y envíe el formulario para consultar el avance y continuar.',
          'Tienes una carga pendiente. Selecciona el archivo original y envía el formulario para consultar el avance y continuar.');
        form.appendChild(aviso);
      }
    }

    async function iniciar(form, datos, seleccion, ui, callbacks, config) {
      asegurarClases(ui);
      var destino = new win.URL(form.action, win.location.href).pathname;
      var clave = 'adso:cargas:v1:' + destino;
      var entrada = leer(clave);
      var firma = seleccion.map(function (item) {
        return [item.input.name, item.archivo.name, item.archivo.size, item.archivo.lastModified || 0];
      });
      if (JSON.stringify(entrada.firma) !== JSON.stringify(firma)) {
        entrada = { envio: win.crypto.randomUUID(), firma: firma, archivos: {} };
      }
      entrada.inicios = entrada.inicios || {};
      var control = { pausado: false, cancelado: false, confirmar: false, activos: new Set(), esperas: new Set() };
      var referencias = {};
      var avances = seleccion.map(function () { return 0; });
      var bases = avances.slice();
      var total = seleccion.reduce(function (suma, item) { return suma + item.archivo.size; }, 0);
      var inicio = Date.now();
      var pausa = doc.createElement('button'); pausa.type = 'button'; pausa.textContent = 'Pausar';
      pausa.className = 'btn btn-secondary upload-pause';
      var cancelar = doc.createElement('button'); cancelar.type = 'button'; cancelar.textContent = 'Cancelar';
      cancelar.className = 'btn btn-secondary upload-cancel';
      ui.panel.appendChild(pausa); ui.panel.appendChild(cancelar);
      guardar(clave, entrada);

      function actualizar() {
        var recibidos = avances.reduce(function (suma, avance) { return suma + avance; }, 0);
        var nuevos = 0;
        for (var n = 0; n < avances.length; n += 1) nuevos += avances[n] - bases[n];
        var velocidad = nuevos / Math.max((Date.now() - inicio) / 1000, 0.001);
        var restante = Math.ceil((total - recibidos) / Math.max(velocidad, 1));
        var porcentaje = Math.floor(recibidos / total * 100);
        pintarAvance(ui, porcentaje);
        ui.texto.textContent = 'Subiendo… ' + porcentaje + '% · ' + (recibidos / 1048576).toFixed(1) +
          ' de ' + (total / 1048576).toFixed(1) + ' MiB confirmados · ' + (velocidad / 1048576).toFixed(1) +
          ' MiB/s · aproximadamente ' + restante + ' s restantes.';
      }

      function avisar(mensaje) {
        ui.texto.textContent = mensaje;
        ui.texto.setAttribute('role', 'alert');
      }

      function suspender(mensaje) {
        control.pausado = true;
        pausa.disabled = false;
        pausa.textContent = 'Continuar';
        avisar(mensaje);
      }

      function despertar() {
        control.esperas.forEach(function (resolver) { resolver(); });
        control.esperas.clear();
      }

      function conexion() {
        if (win.navigator.onLine) despertar();
      }

      async function esperarControl() {
        while (!control.cancelado && (control.pausado || !win.navigator.onLine)) {
          if (!win.navigator.onLine) avisar('Se perdió la conexión. Conservamos el avance durante 24 horas desde el último bloque confirmado.');
          await new Promise(function (resolver) { control.esperas.add(resolver); });
        }
        if (control.cancelado) throw new Error('CANCELADA');
      }

      pausa.addEventListener('click', function () {
        if (control.pausado) { control.pausado = false; pausa.disabled = control.confirmar; pausa.textContent = 'Pausar'; despertar(); }
        else {
          suspender('Carga pausada. El avance se conserva durante 24 horas desde el último bloque confirmado.');
          control.activos.forEach(function (peticion) { peticion.abort(); });
        }
      });
      cancelar.addEventListener('click', function () {
        control.cancelado = true;
        control.activos.forEach(function (peticion) { peticion.abort(); });
        despertar();
      });
      win.addEventListener('online', conexion);

      async function solicitar(url, opciones) {
        var token = doc.querySelector('meta[name="csrf-token"]');
        var peticion = new win.AbortController();
        var limite = win.setTimeout(function () { peticion.abort(); }, 120000);
        control.activos.add(peticion);
        opciones = opciones || {};
        opciones.credentials = 'same-origin'; opciones.signal = peticion.signal;
        opciones.headers = Object.assign({ Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': token ? token.content : '' }, opciones.headers || {});
        try {
          var respuesta = await win.fetch(url, opciones);
          if (respuesta.redirected || respuesta.status === 401) {
            throw Object.assign(new Error(mensaje(destino,
              'La sesión terminó. Ingrese nuevamente para continuar la carga guardada.',
              'Tu sesión terminó. Ingresa nuevamente para continuar la carga guardada.')), { status: 401 });
          }
          var cuerpo;
          try { cuerpo = await respuesta.json(); }
          catch (_) { throw Object.assign(new Error(mensaje(destino,
            'El servidor no confirmó el resultado. Consulte el estado antes de volver a cargar el archivo.',
            'El servidor no confirmó el resultado. Consulta el estado antes de volver a cargar el archivo.')), {
            status: respuesta.ok ? undefined : respuesta.status, transitorio: respuesta.ok || respuesta.status === 429 || (respuesta.status >= 500 && respuesta.status <= 504),
          }); }
          if (!respuesta.ok || respuesta.redirected || cuerpo.ok === false) {
            var espera = respuesta.headers.get('Retry-After');
            throw Object.assign(new Error(cuerpo.message || cuerpo.error || 'No fue posible completar la carga.'), {
              status: respuesta.redirected ? 401 : respuesta.status,
              transitorio: respuesta.status === 429 || (respuesta.status >= 500 && respuesta.status <= 504) ||
                (respuesta.status === 409 && cuerpo.code === 'carga_ocupada'),
              desfase: respuesta.status === 409 && (!cuerpo.code || cuerpo.code === 'desfase'),
              reload: cuerpo.reload === true || cuerpo.code === 'csrf_vencido',
              espera: espera && /^\d+$/.test(espera) ? Number(espera) * 1000 : Math.max(0, Date.parse(espera) - Date.now()) || 0,
            });
          }
          return cuerpo;
        } catch (error) {
          if (!error.status) error.transitorio = true;
          throw error;
        } finally {
          win.clearTimeout(limite); control.activos.delete(peticion);
        }
      }

      async function recuperar(operacion) {
        var intentos = 0;
        while (true) {
          await esperarControl();
          try { return await operacion(); }
          catch (error) {
            if (control.cancelado) throw new Error('CANCELADA');
            if (!error.transitorio && !error.desfase) throw error;
            if (control.pausado || !win.navigator.onLine) continue;
            if (intentos >= 5) {
              suspender(mensaje(destino,
                'No fue posible confirmar la carga. El avance se conserva durante 24 horas desde el último bloque. Seleccione Continuar para reintentar.',
                'No fue posible confirmar la carga. El avance se conserva durante 24 horas desde el último bloque. Selecciona Continuar para reintentar.'));
              intentos = 0;
              continue;
            }
            var demora = Math.max(error.espera || 0, Math.pow(2, intentos) * 1000 * (1 + Math.random() * 0.2));
            intentos += 1;
            avisar('No se confirmó el último envío. Consultaremos el avance antes de continuar. Intento ' + intentos + ' de 5.');
            await new Promise(function (resolver) { win.setTimeout(resolver, demora); });
          }
        }
      }

      async function transferir(item, indice) {
        var archivo = item.archivo;
        var campo = item.input.name;
        var id = entrada.archivos[campo];
        var estado;
        if (id) {
          try { estado = await recuperar(function () { return solicitar(config.url + '/' + id); }); }
          catch (error) {
            if (error.status !== 404 && error.status !== 410) throw error;
            delete entrada.archivos[campo]; delete entrada.inicios[campo]; id = null;
          }
        }
        if (!id) {
          entrada.inicios[campo] = entrada.inicios[campo] || win.crypto.randomUUID();
          guardar(clave, entrada);
          estado = await recuperar(function () {
            return solicitar(config.url, { method: 'POST', headers: {
              'Content-Type': 'application/json', 'Idempotency-Key': entrada.inicios[campo],
            }, body: JSON.stringify({
              destino: destino, campo: campo, nombre: archivo.name, tamano: archivo.size, tipo: archivo.type,
            }) });
          });
          id = estado.id; entrada.archivos[campo] = id; guardar(clave, entrada);
        }
        var bloque = estado.chunk_bytes || config.chunkBytes;
        if (!Number.isSafeInteger(estado.offset) || estado.offset < 0 || estado.offset > archivo.size || estado.tamano !== archivo.size) {
          throw new Error(mensaje(destino,
            'El servidor devolvió un avance inválido. Consulte al administrador antes de continuar.',
            'El servidor devolvió un avance inválido. Consulta al administrador antes de continuar.'));
        }
        ui.texto.textContent = 'Verificando el archivo seleccionado…';
        for (var posicion = 0, numero = 0; posicion < estado.offset; posicion += bloque, numero += 1) {
          if (!estado.huellas || estado.huellas[numero] !== await huella(archivo.slice(posicion, Math.min(posicion + bloque, archivo.size)))) {
            throw new Error(mensaje(destino,
              'El archivo seleccionado no coincide con el que comenzó a subir. Seleccione el archivo original.',
              'El archivo seleccionado no coincide con el que comenzaste a subir. Selecciona el archivo original.'));
          }
        }
        bases[indice] = estado.offset; avances[indice] = estado.offset; actualizar();
        while (estado.offset < archivo.size) {
          await esperarControl();
          var ultimo = estado.offset;
          var consultar = false;
          var fragmento = archivo.slice(ultimo, Math.min(ultimo + bloque, archivo.size));
          var hash = await huella(fragmento);
          estado = await recuperar(async function () {
            if (consultar) {
              var confirmado = await solicitar(config.url + '/' + id);
              if (confirmado.offset !== ultimo) return confirmado;
            }
            consultar = true;
            return solicitar(config.url + '/' + id, { method: 'PATCH', headers: {
              'Content-Type': 'application/octet-stream', 'Upload-Offset': String(ultimo), 'X-Chunk-SHA256': hash,
            }, body: fragmento });
          });
          if (!Number.isSafeInteger(estado.offset) || estado.offset <= ultimo || estado.offset > archivo.size) {
            throw new Error('No fue posible verificar el avance de la carga. El archivo todavía no se ha confirmado.');
          }
          avances[indice] = estado.offset; actualizar();
        }
        referencias[campo] = id;
      }

      try {
        // Dos consumidores comparten el índice; cada archivo mantiene su orden de bloques.
        var siguiente = 0;
        async function consumir() {
          while (siguiente < seleccion.length) {
            var indice = siguiente++; await transferir(seleccion[indice], indice);
          }
        }
        var consumidores = [consumir()];
        if (seleccion.length > 1) consumidores.push(consumir());
        var resultados = await Promise.allSettled(consumidores);
        for (var i = 0; i < resultados.length; i += 1) if (resultados[i].status === 'rejected') throw resultados[i].reason;
        await esperarControl();
        control.confirmar = true; pausa.disabled = true; cancelar.disabled = true;
        ui.texto.textContent = 'Verificando y registrando los archivos recibidos…';
        seleccion.forEach(function (item) { datos.delete(item.input.name); });
        datos.set('_cargas', JSON.stringify(referencias)); datos.set('_carga_envio', entrada.envio);
        var final = await recuperar(function () { return solicitar(form.action, { method: form.method || 'POST', body: datos }); });
        var destinoFinal = final.redirect;
        if (final.status_url) {
          ui.texto.textContent = final.message || 'Guardado; pendiente de procesamiento. El panel sigue disponible.';
          var estadoFinal;
          do {
            estadoFinal = await recuperar(function () { return solicitar(final.status_url); });
            var detalle = estadoFinal.resultado || estadoFinal;
            var reintento = detalle.retry_url || estadoFinal.retry_url;
            if (estadoFinal.estado === 'error') {
              var falloProceso = detalle.message || estadoFinal.message || mensaje(destino,
                'El archivo quedó guardado, pero su procesamiento falló. Puede reintentarlo sin subirlo otra vez.',
                'El archivo quedó guardado, pero su procesamiento falló. Puedes reintentarlo sin subirlo otra vez.');
              if (!reintento) throw new Error(falloProceso);
              suspender(falloProceso);
              pausa.textContent = 'Reintentar procesamiento';
              await esperarControl();
              await recuperar(function () { return solicitar(reintento, { method: 'POST' }); });
              continue;
            }
            if (estadoFinal.estado === 'completado') destinoFinal = detalle.redirect || destinoFinal;
            if (estadoFinal.estado !== 'completado') {
              ui.texto.textContent = estadoFinal.estado === 'procesando' ? 'Procesando los archivos guardados…' : 'Guardado; pendiente de procesamiento. El panel sigue disponible.';
              await new Promise(function (resolver) { win.setTimeout(resolver, 2000); });
            }
          } while (estadoFinal.estado !== 'completado');
        }
        ui.texto.textContent = 'Completado. Los archivos quedaron registrados.';
        guardar(clave, null);
        win.location.href = destinoFinal || win.location.href;
      } catch (error) {
        if (control.cancelado && !control.confirmar) {
          var ids = Object.values(entrada.archivos);
          var eliminaciones = [];
          for (var j = 0; j < ids.length; j += 1) eliminaciones.push(solicitar(config.url + '/' + ids[j], { method: 'DELETE' }));
          var eliminados = await Promise.allSettled(eliminaciones);
          if (eliminados.every(function (resultado) { return resultado.status === 'fulfilled'; })) guardar(clave, null);
          callbacks.fallar('La carga se canceló. Los archivos que no se pudieron retirar vencerán a las 24 horas.');
        } else callbacks.fallar(error.message, error.reload || error.status === 401);
      } finally {
        win.removeEventListener('online', conexion);
      }
    }

    return { iniciar: iniciar, restaurar: restaurar };
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { crearMotor: crearMotor };
  if (raiz && raiz.document) raiz.ADSOCargasReanudables = crearMotor(raiz, raiz.document);
})(typeof window !== 'undefined' ? window : null);
