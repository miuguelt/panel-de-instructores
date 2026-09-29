(function () {
    'use strict';

    var chats = document.querySelectorAll('[data-grupo-chat]');
    if (!chats.length || typeof window.fetch !== 'function') return;

    chats.forEach(function (chat) {
        var endpoint = chat.dataset.chatUrl;
        var messagesBox = chat.querySelector('[data-chat-messages]');
        var emptyMessage = chat.querySelector('[data-chat-empty]');
        var status = chat.querySelector('[data-chat-status]');
        var form = chat.querySelector('[data-chat-form]');
        var input = chat.querySelector('[data-chat-input]');
        var counter = chat.querySelector('[data-chat-count]');
        var submit = chat.querySelector('[data-chat-submit]');
        var csrf = form && form.querySelector('input[name="csrf_token"]');
        var messageIds = new Set();
        var newestId = 0;
        var polling = false;
        var sending = false;
        var pollInterval = 6000;

        if (!endpoint || !messagesBox || !form || !input || !csrf) return;

        function actualizarContador() {
            if (counter) counter.textContent = String(input.value.length);
        }

        function fechaLegible(valor) {
            if (!valor) return '';
            var fecha = new Date(valor);
            if (Number.isNaN(fecha.getTime())) return String(valor);
            return new Intl.DateTimeFormat('es-CO', {
                dateStyle: 'short',
                timeStyle: 'short'
            }).format(fecha);
        }

        function agregarMensaje(mensaje) {
            if (!mensaje || typeof mensaje !== 'object') return false;
            var id = Number(mensaje.id);
            if (Number.isFinite(id) && messageIds.has(id)) return false;
            if (Number.isFinite(id)) {
                messageIds.add(id);
                newestId = Math.max(newestId, id);
            }

            var estabaAbajo = messagesBox.scrollHeight - messagesBox.scrollTop - messagesBox.clientHeight < 56;
            var fila = document.createElement('article');
            fila.className = 'learner-group-chat-message';
            fila.classList.toggle('is-own', mensaje.propio === true);
            if (Number.isFinite(id)) fila.dataset.messageId = String(id);

            var cabecera = document.createElement('div');
            cabecera.className = 'learner-group-chat-message-meta';
            var autor = document.createElement('strong');
            autor.textContent = mensaje.propio === true ? 'Tú' : (mensaje.autor || 'Integrante del grupo');
            cabecera.appendChild(autor);

            var fechaTexto = fechaLegible(mensaje.creado_en);
            if (fechaTexto) {
                var fecha = document.createElement('time');
                fecha.textContent = fechaTexto;
                if (mensaje.creado_en) fecha.dateTime = String(mensaje.creado_en);
                cabecera.appendChild(fecha);
            }

            var contenido = document.createElement('p');
            contenido.className = 'learner-group-chat-message-content';
            contenido.textContent = String(mensaje.contenido || '');
            fila.appendChild(cabecera);
            fila.appendChild(contenido);
            if (emptyMessage && emptyMessage.isConnected) emptyMessage.remove();
            messagesBox.appendChild(fila);
            if (estabaAbajo || mensaje.propio === true) {
                messagesBox.scrollTop = messagesBox.scrollHeight;
            }
            return true;
        }

        function mostrarVacio() {
            if (messagesBox.querySelector('.learner-group-chat-message')) return;
            if (emptyMessage && emptyMessage.isConnected) {
                emptyMessage.textContent = 'Aún no hay mensajes. Inicia la conversación con tu grupo.';
            }
        }

        async function leerMensajes() {
            if (polling || document.hidden) return;
            polling = true;
            var url = new URL(endpoint, window.location.href);
            if (newestId > 0) url.searchParams.set('despues_id', String(newestId));
            try {
                var respuesta = await window.fetch(url.toString(), {
                    method: 'GET',
                    credentials: 'same-origin',
                    headers: { 'Accept': 'application/json' }
                });
                var datos = await respuesta.json();
                if (!respuesta.ok) throw new Error(datos.error || datos.mensaje || 'No se pudo cargar la conversación.');
                var mensajes = Array.isArray(datos.messages) ? datos.messages.slice() : [];
                mensajes.sort(function (a, b) { return Number(a.id) - Number(b.id); });
                mensajes.forEach(agregarMensaje);
                if (!messagesBox.querySelector('.learner-group-chat-message')) mostrarVacio();
                if (status) status.textContent = '';
            } catch (error) {
                if (status) status.textContent = error.message || 'No se pudo actualizar el chat. Revisa tu conexión e inténtalo de nuevo.';
            } finally {
                polling = false;
            }
        }

        input.addEventListener('input', actualizarContador);
        actualizarContador();

        form.addEventListener('submit', async function (evento) {
            evento.preventDefault();
            var contenido = input.value.trim();
            if (!contenido) {
                if (status) status.textContent = 'Escribe un mensaje antes de enviarlo.';
                input.focus();
                return;
            }
            if (contenido.length > 1200 || sending) return;

            sending = true;
            submit.disabled = true;
            if (status) status.textContent = 'Enviando mensaje…';
            try {
                var respuesta = await window.fetch(endpoint, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrf.value
                    },
                    body: JSON.stringify({ contenido: contenido })
                });
                var datos = await respuesta.json();
                if (!respuesta.ok) throw new Error(datos.error || datos.mensaje || 'No se pudo enviar el mensaje. Inténtalo de nuevo.');
                if (datos.message) agregarMensaje(datos.message);
                input.value = '';
                actualizarContador();
                if (status) status.textContent = 'Mensaje enviado.';
            } catch (error) {
                if (status) status.textContent = error.message || 'No se pudo enviar el mensaje. Revisa tu conexión e inténtalo de nuevo.';
            } finally {
                sending = false;
                submit.disabled = false;
            }
        });

        leerMensajes();
        window.setInterval(leerMensajes, pollInterval);
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) leerMensajes();
        });
    });
})();
