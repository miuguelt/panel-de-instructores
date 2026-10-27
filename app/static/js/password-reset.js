(function () {
    const tokenInput = document.getElementById('token');
    if (!tokenInput) return;

    let tokenVal = tokenInput.value ? tokenInput.value.trim() : '';

    // 1. Extraer desde parámetro de consulta (?token=...)
    if (!tokenVal && window.location.search) {
        try {
            const params = new URLSearchParams(window.location.search);
            const queryToken = params.get('token');
            if (queryToken) {
                tokenVal = queryToken.trim();
            }
        } catch (_) {
            // Entorno sin soporte de URLSearchParams
        }
    }

    // 2. Extraer desde fragmento hash (#token=... o #...) para enlaces anteriores
    if (!tokenVal && window.location.hash) {
        const hash = window.location.hash.slice(1);
        if (hash.startsWith('token=')) {
            tokenVal = hash.slice(6).trim();
        } else {
            tokenVal = hash.trim();
        }
    }

    // 3. Asignar al campo oculto y limpiar la barra de direcciones
    if (tokenVal) {
        tokenInput.value = tokenVal;
        if (window.history && window.history.replaceState) {
            window.history.replaceState(null, '', window.location.pathname);
        }
    }
})();
