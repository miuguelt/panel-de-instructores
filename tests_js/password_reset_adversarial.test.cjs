const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const raiz = path.resolve(__dirname, '..');
const codigoJs = fs.readFileSync(path.join(raiz, 'app/static/js/password-reset.js'), 'utf8');

function ejecutarScriptConContexto(opciones) {
    let replacedState = null;
    let tokenInput = opciones.sinInput ? null : {
        value: opciones.valorInicial || ''
    };

    const windowObj = {
        location: {
            pathname: '/restablecer-contrasena',
            search: opciones.search || '',
            hash: opciones.hash || '',
        },
        history: {
            replaceState: (state, title, url) => {
                replacedState = { state, title, url };
            }
        },
        URLSearchParams: opciones.sinUrlSearchParams ? undefined : global.URLSearchParams
    };

    const documentObj = {
        getElementById: (id) => (id === 'token' ? tokenInput : null)
    };

    const contexto = {
        window: windowObj,
        document: documentObj,
        URLSearchParams: windowObj.URLSearchParams,
    };

    vm.createContext(contexto);
    vm.runInContext(codigoJs, contexto);

    return {
        tokenValorFinal: tokenInput ? tokenInput.value : null,
        replacedState
    };
}

test('password-reset.js retorna silenciosamente si no existe elemento #token en el DOM', () => {
    const res = ejecutarScriptConContexto({ sinInput: true, search: '?token=123' });
    assert.equal(res.tokenValorFinal, null);
    assert.equal(res.replacedState, null);
});

test('password-reset.js preserva el valor existente precargado por el servidor y limpia la barra de direcciones', () => {
    const res = ejecutarScriptConContexto({
        valorInicial: 'token_servidor_fijo',
        search: '?token=token_query_ignorado',
        hash: '#token=token_hash_ignorado'
    });
    assert.equal(res.tokenValorFinal, 'token_servidor_fijo');
    // Debe limpiar la URL para que el token no permanezca expuesto en el historial o barra de direcciones
    assert.deepEqual(res.replacedState, {
        state: null,
        title: '',
        url: '/restablecer-contrasena'
    });
});

test('password-reset.js extrae token desde ?token=... en search y limpia URL con replaceState', () => {
    const res = ejecutarScriptConContexto({
        valorInicial: '',
        search: '?token=token_desde_query_param_456',
        hash: '#token_hash_secundario'
    });
    assert.equal(res.tokenValorFinal, 'token_desde_query_param_456');
    assert.deepEqual(res.replacedState, {
        state: null,
        title: '',
        url: '/restablecer-contrasena'
    });
});

test('password-reset.js extrae token retrocompatible desde hash con prefijo token=', () => {
    const res = ejecutarScriptConContexto({
        valorInicial: '',
        search: '',
        hash: '#token=token_desde_hash_con_prefijo_789'
    });
    assert.equal(res.tokenValorFinal, 'token_desde_hash_con_prefijo_789');
    assert.deepEqual(res.replacedState, {
        state: null,
        title: '',
        url: '/restablecer-contrasena'
    });
});

test('password-reset.js extrae token retrocompatible desde hash plano sin prefijo', () => {
    const res = ejecutarScriptConContexto({
        valorInicial: '',
        search: '',
        hash: '#token_desde_hash_plano_sin_prefijo_abc'
    });
    assert.equal(res.tokenValorFinal, 'token_desde_hash_plano_sin_prefijo_abc');
    assert.deepEqual(res.replacedState, {
        state: null,
        title: '',
        url: '/restablecer-contrasena'
    });
});

test('password-reset.js no altera nada si search y hash están vacíos', () => {
    const res = ejecutarScriptConContexto({
        valorInicial: '',
        search: '',
        hash: ''
    });
    assert.equal(res.tokenValorFinal, '');
    assert.equal(res.replacedState, null);
});

test('password-reset.js tolera entorno sin URLSearchParams y degrada a hash', () => {
    const res = ejecutarScriptConContexto({
        valorInicial: '',
        search: '?token=no_parseable',
        hash: '#token=token_fallback_hash',
        sinUrlSearchParams: true
    });
    assert.equal(res.tokenValorFinal, 'token_fallback_hash');
});
