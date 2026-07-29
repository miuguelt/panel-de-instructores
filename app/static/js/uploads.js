/*
 * uploads.js — Subida de archivos con progreso real.
 *
 * Antes, cualquier formulario con archivo (evidencia, soporte, material,
 * reporte de juicios) enviaba un POST clásico: el navegador se quedaba en
 * blanco sin indicar nada y, en la red del aula, el aprendiz volvía a pulsar
 * "Enviar" creyendo que no había pasado nada. Aquí se intercepta el envío y
 * se sube por XHR para poder mostrar porcentaje, bloquear el doble envío y
 * traducir el 413 del servidor a un mensaje entendible.
 *
 * La respuesta del servidor sigue siendo la misma redirección de siempre: al
 * terminar se navega a `xhr.responseURL`, así los mensajes flash se muestran
 * exactamente igual que en el flujo sin JavaScript.
 *
 * Degradación: si el navegador no soporta FormData o progreso de subida, no
 * se intercepta nada y el formulario funciona como HTML plano.
 */
(function () {
  'use strict';

  var soportado = (
    typeof window.FormData === 'function' &&
    typeof window.XMLHttpRequest === 'function' &&
    'upload' in new XMLHttpRequest()
  );
  if (!soportado) return;

  var LIMITE_BYTES = window.ADSO_MAX_UPLOAD_BYTES || 0;

  function formatearTamano(bytes) {
    var unidades = ['B', 'KB', 'MB', 'GB'];
    var valor = bytes;
    var i = 0;
    while (valor >= 1024 && i < unidades.length - 1) {
      valor /= 1024;
      i += 1;
    }
    return valor.toFixed(1) + ' ' + unidades[i];
  }

  function extensionDe(nombre) {
    var partes = String(nombre || '').split('.');
    return partes.length > 1 ? partes.pop().toLowerCase() : '';
  }

  /** Extensiones declaradas en el atributo accept del input, si lo hay. */
  function extensionesAceptadas(input) {
    var accept = (input.getAttribute('accept') || '').trim();
    if (!accept) return null;
    var lista = accept.split(',').map(function (item) {
      return item.trim().replace(/^\./, '').toLowerCase();
    }).filter(function (item) {
      return item && item.indexOf('/') === -1;
    });
    return lista.length ? lista : null;
  }

  function archivosDe(form) {
    var seleccionados = [];
    var inputs = form.querySelectorAll('input[type="file"]');
    for (var i = 0; i < inputs.length; i += 1) {
      var archivos = inputs[i].files;
      if (!archivos) continue;
      for (var j = 0; j < archivos.length; j += 1) {
        seleccionados.push({ archivo: archivos[j], input: inputs[i] });
      }
    }
    return seleccionados;
  }

  function validar(seleccion) {
    var total = 0;
    for (var i = 0; i < seleccion.length; i += 1) {
      var archivo = seleccion[i].archivo;
      total += archivo.size;

      if (archivo.size === 0) {
        return 'El archivo "' + archivo.name + '" está vacío. Selecciona otro.';
      }
      var permitidas = extensionesAceptadas(seleccion[i].input);
      if (permitidas && permitidas.indexOf(extensionDe(archivo.name)) === -1) {
        return 'El archivo "' + archivo.name + '" no tiene un formato permitido. ' +
          'Se aceptan: ' + permitidas.join(', ') + '.';
      }
    }
    if (LIMITE_BYTES && total > LIMITE_BYTES) {
      return 'La subida pesa ' + formatearTamano(total) + ' y el máximo permitido es ' +
        formatearTamano(LIMITE_BYTES) + '.';
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
    barra.style.cssText =
      'height:8px;border-radius:999px;overflow:hidden;background:rgba(127,127,127,.25);';

    var relleno = document.createElement('div');
    relleno.style.cssText =
      'height:100%;width:0%;background:var(--accent-primary,#39a900);transition:width .15s linear;';

    barra.appendChild(relleno);
    panel.appendChild(texto);
    panel.appendChild(barra);
    form.appendChild(panel);
    return { panel: panel, texto: texto, relleno: relleno };
  }

  function botonesDe(form) {
    return form.querySelectorAll('button[type="submit"], input[type="submit"], button:not([type])');
  }

  function bloquear(form, bloqueado) {
    var botones = botonesDe(form);
    for (var i = 0; i < botones.length; i += 1) {
      botones[i].disabled = bloqueado;
    }
  }

  function mostrarError(form, mensaje) {
    var previo = form.querySelector('.upload-error');
    if (previo) previo.remove();
    var aviso = document.createElement('p');
    aviso.className = 'upload-error';
    aviso.setAttribute('role', 'alert');
    aviso.style.cssText = 'margin:8px 0;color:#c0392b;font-size:13px;';
    aviso.textContent = mensaje;
    form.appendChild(aviso);
  }

  function enviar(form, evento) {
    var seleccion = archivosDe(form);
    if (!seleccion.length) return;  // Sin archivo: envío normal del navegador.

    var error = validar(seleccion);
    if (error) {
      evento.preventDefault();
      mostrarError(form, error);
      return;
    }

    evento.preventDefault();
    var previo = form.querySelector('.upload-error');
    if (previo) previo.remove();

    var ui = crearPanel(form);
    bloquear(form, true);
    ui.texto.textContent = 'Preparando la subida…';

    var xhr = new XMLHttpRequest();
    xhr.open(form.method || 'POST', form.action, true);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

    xhr.upload.addEventListener('progress', function (evt) {
      if (!evt.lengthComputable) {
        ui.texto.textContent = 'Subiendo archivo…';
        return;
      }
      var porcentaje = Math.round((evt.loaded / evt.total) * 100);
      ui.relleno.style.width = porcentaje + '%';
      ui.texto.textContent = 'Subiendo… ' + porcentaje + '% (' +
        formatearTamano(evt.loaded) + ' de ' + formatearTamano(evt.total) + ')';
    });

    xhr.upload.addEventListener('load', function () {
      ui.relleno.style.width = '100%';
      ui.texto.textContent = 'Archivo recibido. Procesando en el servidor…';
    });

    xhr.addEventListener('load', function () {
      if (xhr.status >= 200 && xhr.status < 400) {
        // El servidor responde con redirección; XHR ya la siguió, así que
        // basta con navegar a la URL final para ver los mensajes flash.
        window.location.href = xhr.responseURL || window.location.href;
        return;
      }
      bloquear(form, false);
      ui.panel.remove();
      if (xhr.status === 413) {
        mostrarError(form, 'El archivo supera el tamaño máximo permitido' +
          (LIMITE_BYTES ? ' (' + formatearTamano(LIMITE_BYTES) + ')' : '') + '.');
      } else if (xhr.status === 429) {
        mostrarError(form, 'Demasiados intentos seguidos. Espera un minuto y vuelve a enviarlo.');
      } else {
        mostrarError(form, 'El servidor rechazó la subida (error ' + xhr.status + '). Inténtalo de nuevo.');
      }
    });

    xhr.addEventListener('error', function () {
      bloquear(form, false);
      ui.panel.remove();
      mostrarError(form, 'Se perdió la conexión durante la subida. El archivo no se guardó; vuelve a intentarlo.');
    });

    xhr.addEventListener('abort', function () {
      bloquear(form, false);
      ui.panel.remove();
    });

    xhr.send(new FormData(form));
  }

  document.addEventListener('submit', function (evento) {
    var form = evento.target;
    if (!form || form.tagName !== 'FORM') return;
    if ((form.enctype || '').toLowerCase() !== 'multipart/form-data') return;
    if (form.hasAttribute('data-sin-progreso')) return;
    enviar(form, evento);
  }, true);
})();
