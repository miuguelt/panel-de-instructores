/* Carga compartida: progreso, validación y recuperación sin perder la selección. */
(function () {
  'use strict';

  if (typeof window.FormData !== 'function' || typeof window.XMLHttpRequest !== 'function' ||
      !('upload' in new XMLHttpRequest())) return;

  var LIMITE_BYTES = window.ADSO_MAX_UPLOAD_BYTES || 0;
  var LIMITE_SOLICITUD = window.ADSO_MAX_REQUEST_BYTES || (LIMITE_BYTES ? LIMITE_BYTES + 1024 * 1024 : 0);
  var activos = new WeakMap();

  function formatearTamano(bytes) {
    var unidades = ['B', 'KiB', 'MiB', 'GiB'];
    var valor = bytes;
    var i = 0;
    while (valor >= 1024 && i < unidades.length - 1) { valor /= 1024; i += 1; }
    return valor.toFixed(1) + ' ' + unidades[i];
  }

  function formatoAceptado(archivo, input) {
    var accept = (input.getAttribute('accept') || '').toLowerCase();
    if (!accept.trim()) return true;
    var nombre = (archivo.name || '').toLowerCase();
    var mime = (archivo.type || '').toLowerCase();
    var formatos = accept.split(',');
    for (var i = 0; i < formatos.length; i += 1) {
      var formato = formatos[i].trim();
      if (formato.charAt(0) === '.' && nombre.endsWith(formato)) return true;
      if (formato.indexOf('/') !== -1 && mime &&
          (formato === mime || (formato.endsWith('/*') && mime.indexOf(formato.slice(0, -1)) === 0))) return true;
    }
    return false;
  }

  function archivosDe(form) {
    var seleccion = [];
    var inputs = form.querySelectorAll('input[type="file"]');
    for (var i = 0; i < inputs.length; i += 1) {
      if (inputs[i].disabled || !inputs[i].files) continue;
      for (var j = 0; j < inputs[i].files.length; j += 1) {
        seleccion.push({ archivo: inputs[i].files[j], input: inputs[i] });
      }
    }
    return seleccion;
  }

  function validar(seleccion) {
    var total = 0;
    for (var i = 0; i < seleccion.length; i += 1) {
      var archivo = seleccion[i].archivo;
      if (archivo.webkitRelativePath) return 'Para cargar una carpeta, comprime su contenido en un archivo ZIP y selecciona el ZIP generado.';
      if (archivo.size === 0) return 'El archivo "' + archivo.name + '" está vacío. Selecciona otro.';
      if (LIMITE_BYTES && archivo.size > LIMITE_BYTES) {
        return 'El archivo "' + archivo.name + '" pesa ' + formatearTamano(archivo.size) +
          ' y el máximo permitido por archivo es ' + formatearTamano(LIMITE_BYTES) + '. Reduce su tamaño e inténtalo de nuevo.';
      }
      if (!formatoAceptado(archivo, seleccion[i].input)) {
        return 'El archivo "' + archivo.name + '" no tiene un formato permitido. Se aceptan: ' +
          seleccion[i].input.getAttribute('accept') + '.';
      }
      total += archivo.size;
    }
    if (LIMITE_SOLICITUD && total > LIMITE_SOLICITUD) {
      return 'La subida pesa ' + formatearTamano(total) + ' y el máximo permitido por envío es ' +
        formatearTamano(LIMITE_SOLICITUD) + '. Carga los archivos en envíos separados.';
    }
    return '';
  }

  function crearPanel(form) {
    var panel = document.createElement('div');
    panel.className = 'upload-progress';
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    panel.style.cssText = 'margin:10px 0;font-size:13px;';
    var texto = document.createElement('div');
    texto.className = 'upload-progress-text';
    texto.style.cssText = 'margin-bottom:6px;';
    var barra = document.createElement('div');
    barra.style.cssText = 'height:8px;border-radius:999px;overflow:hidden;background:rgba(127,127,127,.25);';
    var relleno = document.createElement('div');
    relleno.style.cssText = 'height:100%;width:0%;background:var(--accent-primary,#39a900);transition:width .15s linear;';
    barra.appendChild(relleno); panel.appendChild(texto); panel.appendChild(barra); form.appendChild(panel);
    return { panel: panel, texto: texto, relleno: relleno };
  }

  function mostrarError(form, mensaje, recargar) {
    var previo = form.querySelector('.upload-error');
    if (previo) previo.remove();
    var aviso = document.createElement('p');
    aviso.className = 'upload-error';
    aviso.setAttribute('role', 'alert');
    aviso.setAttribute('tabindex', '-1');
    aviso.style.cssText = 'margin:8px 0;color:var(--danger-text,#c0392b);font-size:13px;';
    aviso.textContent = mensaje;
    if (recargar) {
      var boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'btn btn-secondary';
      boton.textContent = 'Recargar formulario';
      boton.style.cssText = 'display:block;margin-top:8px;min-height:44px;';
      boton.addEventListener('click', function () { window.location.reload(); });
      aviso.appendChild(boton);
    }
    form.appendChild(aviso);
    aviso.focus();
  }

  function esJson(xhr) {
    var tipo = (xhr.getResponseHeader('Content-Type') || '').split(';', 1)[0].trim().toLowerCase();
    return tipo === 'application/json' || tipo.endsWith('+json');
  }

  function cuerpoJson(xhr) {
    if (!esJson(xhr)) return null;
    try { return JSON.parse(xhr.responseText || '{}'); } catch (_error) { return null; }
  }

  function errorHttp(status) {
    if (status === 400) return 'No se pudo leer el formulario. Revisa los archivos y vuelve a intentarlo; si persiste, recarga la página.';
    if (status === 401) return 'Tu sesión terminó. Vuelve a ingresar al panel antes de cargar el archivo.';
    if (status === 403) return 'No tienes permiso para cargar este archivo aquí. Verifica tu acceso con el instructor.';
    if (status === 413) return 'La subida supera el tamaño máximo permitido' + (LIMITE_BYTES ? ' (' + formatearTamano(LIMITE_BYTES) + ' por archivo)' : '') + '. Reduce el tamaño o carga menos archivos.';
    if (status === 429) return 'Hay demasiados intentos seguidos. Espera un minuto y vuelve a enviar el archivo.';
    if (status === 502 || status === 503 || status === 504) return 'El servidor no confirmó la carga (' + status + '). Revisa si el archivo quedó registrado antes de volver a enviarlo.';
    return 'El servidor rechazó la subida (error ' + status + '). Inténtalo de nuevo.';
  }

  function enviar(form, evento) {
    if (activos.has(form)) { evento.preventDefault(); return; }
    var seleccion = archivosDe(form);
    if (!seleccion.length) {
      var inputs = form.querySelectorAll('input[type="file"]');
      for (var i = 0; i < inputs.length; i += 1) {
        if (!inputs[i].disabled && inputs[i].hasAttribute('webkitdirectory')) {
          evento.preventDefault();
          mostrarError(form, 'Para cargar una carpeta, comprime su contenido en un archivo ZIP y selecciona el ZIP generado.');
          break;
        }
      }
      return;
    }
    evento.preventDefault();
    var error = validar(seleccion);
    if (error) { mostrarError(form, error); return; }
    var previo = form.querySelector('.upload-error');
    if (previo) previo.remove();
    var botones = form.querySelectorAll('button[type="submit"], input[type="submit"], button:not([type])');
    var estados = [];
    var ui = crearPanel(form);
    activos.set(form, true);

    function fallar(mensaje, recargar) {
      for (var k = 0; k < estados.length; k += 1) botones[k].disabled = estados[k];
      activos.delete(form);
      form.removeAttribute('aria-busy');
      ui.panel.remove();
      mostrarError(form, mensaje, recargar);
    }

    try {
      // FormData se construye antes de bloquear controles para conservar sus valores.
      var datos = new FormData(form);
      var submitter = evento.submitter;
      if (submitter && submitter.name && !submitter.disabled) datos.append(submitter.name, submitter.value);
      for (var j = 0; j < botones.length; j += 1) { estados.push(botones[j].disabled); botones[j].disabled = true; }
      form.setAttribute('aria-busy', 'true');
      ui.texto.textContent = 'Preparando la subida…';
      var xhr = new XMLHttpRequest();
      xhr.open(form.method || 'POST', form.action, true);
      xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
      xhr.timeout = 15 * 60 * 1000;
      xhr.upload.addEventListener('progress', function (evt) {
        if (!evt.lengthComputable) { ui.texto.textContent = 'Subiendo archivo…'; return; }
        var porcentaje = Math.round((evt.loaded / evt.total) * 100);
        ui.relleno.style.width = porcentaje + '%';
        ui.texto.textContent = 'Subiendo… ' + porcentaje + '% (' + formatearTamano(evt.loaded) + ' de ' + formatearTamano(evt.total) + ')';
      });
      xhr.upload.addEventListener('load', function () {
        ui.relleno.style.width = '100%';
        ui.texto.textContent = 'Archivo recibido. Procesando en el servidor…';
      });
      xhr.addEventListener('load', function () {
        var cuerpo = cuerpoJson(xhr);
        if (cuerpo) {
          if (xhr.status >= 200 && xhr.status < 300 && cuerpo.ok) {
            window.location.href = cuerpo.redirect || xhr.responseURL || window.location.href;
          } else {
            fallar(cuerpo.message || cuerpo.detail || cuerpo.error || errorHttp(xhr.status), cuerpo.reload || xhr.status === 401);
          }
          return;
        }
        if (esJson(xhr) && xhr.status >= 200 && xhr.status < 300) {
          fallar('No se pudo confirmar la carga porque la respuesta del servidor llegó incompleta. Revisa si el archivo quedó registrado antes de volver a enviarlo.');
          return;
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          var html = new DOMParser().parseFromString(xhr.responseText || '', 'text/html');
          if (html.querySelector('form.auth-form input[type="password"]')) { fallar(errorHttp(401), true); return; }
          var alerta = html.querySelector('.flash-messages .alert-error, .flash-messages .alert-danger');
          if (alerta) { fallar(alerta.textContent.trim()); return; }
          window.location.href = xhr.responseURL || window.location.href;
          return;
        }
        fallar(errorHttp(xhr.status), xhr.status === 401);
      });
      xhr.addEventListener('error', function () {
        fallar('Se perdió la conexión y no se confirmó la carga. Revisa si el archivo quedó registrado antes de volver a enviarlo.');
      });
      xhr.addEventListener('abort', function () {
        fallar('La subida se canceló. Revisa si el archivo quedó registrado antes de volver a enviarlo.');
      });
      xhr.addEventListener('timeout', function () {
        fallar('La subida tardó demasiado y no se confirmó el resultado. Revisa si el archivo quedó registrado antes de volver a enviarlo.');
      });
      xhr.send(datos);
    } catch (_error) {
      fallar('No se pudo iniciar la subida. Comprueba que el archivo siga disponible e inténtalo de nuevo.');
    }
  }

  // En propagación: los validadores del formulario pueden cancelar primero el envío.
  document.addEventListener('submit', function (evento) {
    var form = evento.target;
    if (evento.defaultPrevented || !form || form.tagName !== 'FORM') return;
    if ((form.enctype || '').toLowerCase() !== 'multipart/form-data' || form.hasAttribute('data-sin-progreso')) return;
    enviar(form, evento);
  });
})();
