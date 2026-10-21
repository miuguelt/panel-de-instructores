/* Copia explícita con confirmación y alternativa si el navegador la rechaza. */
'use strict';

async function copiarTexto(texto, ambito = window) {
    const avisar = typeof ambito.mostrarAviso === 'function' ? ambito.mostrarAviso : function (mensaje) { ambito.alert(mensaje); };
    try {
        if (!ambito.navigator.clipboard || typeof ambito.navigator.clipboard.writeText !== 'function') throw new Error('Portapapeles no disponible.');
        await ambito.navigator.clipboard.writeText(String(texto));
        avisar('Enlace copiado al portapapeles.', { title: 'Enlace copiado', intent: 'success' });
        return true;
    } catch (_) {
        avisar('No fue posible copiar el enlace. Selecciónalo y cópialo manualmente.', { title: 'No se pudo copiar', intent: 'danger' });
        return false;
    }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { copiarTexto };
