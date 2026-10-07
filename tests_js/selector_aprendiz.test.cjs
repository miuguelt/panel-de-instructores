const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const selector = require('../app/static/js/selector_aprendiz.js');
const selectorSource = fs.readFileSync(path.resolve(__dirname, '../app/static/js/selector_aprendiz.js'), 'utf8');

function crearAzarControlado(valores) {
    const usados = [];
    return {
        usados,
        getRandomValues(buffer) {
            usados.push(buffer);
            buffer[0] = valores.shift();
            return buffer;
        },
    };
}

test('usa rechazo criptográfico para evitar sesgo de módulo', () => {
    const cryptoFalso = crearAzarControlado([0xffffffff, 4]);

    assert.equal(selector.numeroAleatorioSeguro(3, cryptoFalso), 1);
    assert.equal(cryptoFalso.usados.length, 2, 'debe descartar el valor fuera del rango uniforme');
    assert.ok(cryptoFalso.usados.every(valor => valor instanceof Uint32Array));
});

test('valida el rango y exige un generador criptográfico', () => {
    assert.equal(selector.numeroAleatorioSeguro(1, null), 0);
    assert.throws(() => selector.numeroAleatorioSeguro(0, crearAzarControlado([])), RangeError);
    assert.throws(() => selector.numeroAleatorioSeguro(0x100000001, crearAzarControlado([])), RangeError);
    assert.throws(() => selector.numeroAleatorioSeguro(2, null), /criptográfico/i);
});

test('baraja una copia con índices válidos y rechaza índices fuera del rango', () => {
    const personas = [{ id: 1 }, { id: 2 }, { id: 3 }];
    const orden = [0, 0];
    const resultado = selector.barajarAprendices(personas, limite => {
        const indice = orden.shift();
        assert.ok(indice < limite);
        return indice;
    });

    assert.deepEqual(resultado.map(persona => persona.id), [2, 3, 1]);
    assert.deepEqual(personas.map(persona => persona.id), [1, 2, 3]);
    assert.deepEqual(selector.barajarAprendices([{ id: 4 }], () => 0), [{ id: 4 }]);
    assert.throws(() => selector.barajarAprendices(personas, () => 3), RangeError);
});

test('reparte turnos sin repetir dentro de la ronda y evita repetir al iniciar la siguiente', () => {
    const resultadosAzar = [2, 1, 0, 1, 1];
    const bolsa = selector.crearBolsa([
        { id: 1, nombre: 'Ana' },
        { id: 2, nombre: 'Luis' },
        { id: 3, nombre: 'Sara' },
    ], () => resultadosAzar.shift());

    assert.deepEqual(
        [bolsa.siguiente().id, bolsa.siguiente().id, bolsa.siguiente().id],
        [3, 2, 1],
    );
    assert.equal(bolsa.restantes(), 0);
    assert.equal(bolsa.siguiente().id, 2, 'la nueva ronda no debe repetir de inmediato a la última persona');
    assert.equal(bolsa.restantes(), 2);
});

test('valida la lista de participantes y sus identificadores', () => {
    assert.throws(() => selector.crearBolsa([]), /al menos un aprendiz/i);
    assert.throws(() => selector.crearBolsa([{ id: 1 }, { id: 1 }]), /identificadores únicos/i);
});

test('expone e inicializa el selector cuando el script se carga en el navegador', () => {
    const contexto = vm.createContext({
        document: { getElementById: () => null },
        crypto: {},
    });

    vm.runInContext(selectorSource, contexto);
    assert.equal(typeof contexto.SelectorAprendiz.inicializar, 'function');
});

class ElementoFalso {
    constructor(dataset = {}) {
        this.dataset = dataset;
        this.disabled = false;
        this.hidden = false;
        this.textContent = '';
        this.attributes = new Map();
        this.listeners = new Map();
        this.classNames = new Set();
        this.classList = {
            add: name => this.classNames.add(name),
            remove: name => this.classNames.delete(name),
            toggle: (name, force) => {
                if (force) this.classNames.add(name);
                else this.classNames.delete(name);
            },
            contains: name => this.classNames.has(name),
        };
    }

    addEventListener(nombre, callback) {
        this.listeners.set(nombre, callback);
    }

    setAttribute(nombre, valor) {
        this.attributes.set(nombre, valor);
    }

    focus() {
        this.focused = true;
    }

    async activar(nombre, evento = {}) {
        return this.listeners.get(nombre)?.(evento);
    }
}

function crearVistaSelector({ personas = [], pantallaDisponible = true, solicitudCompletaFalla = false, salidaCompletaFalla = false } = {}) {
    const nombres = [
        'selector-aprendiz',
        'selector-aprendiz-sortear',
        'selector-aprendiz-expandir',
        'selector-aprendiz-salir',
        'selector-aprendiz-nombre',
        'selector-aprendiz-estado',
        'selector-aprendiz-mensaje',
        'selector-aprendiz-contador',
    ];
    const elementos = Object.fromEntries(nombres.map(nombre => [nombre, new ElementoFalso()]));
    const eventos = new Map();
    const temporizadores = [];
    const cuerpo = new ElementoFalso();
    const documento = {
        body: cuerpo,
        fullscreenElement: null,
        defaultView: { setTimeout: callback => temporizadores.push(callback) },
        getElementById: id => elementos[id] || null,
        querySelectorAll: () => personas.map(persona => new ElementoFalso({
            id: String(persona.id),
            nombre: persona.nombre,
            estado: persona.estado || 'En formación',
        })),
        addEventListener: (nombre, callback) => eventos.set(nombre, callback),
        async exitFullscreen() {
            if (salidaCompletaFalla) throw new Error('No se pudo salir de pantalla completa');
            this.fullscreenElement = null;
            eventos.get('fullscreenchange')();
        },
    };

    if (pantallaDisponible) {
        elementos['selector-aprendiz'].requestFullscreen = async () => {
            if (solicitudCompletaFalla) throw new Error('Pantalla completa bloqueada');
            documento.fullscreenElement = elementos['selector-aprendiz'];
            eventos.get('fullscreenchange')();
        };
    }

    return {
        documento,
        elementos,
        eventos,
        temporizadores,
        async ejecutarTemporizador() {
            const callback = temporizadores.shift();
            assert.equal(typeof callback, 'function');
            callback();
        },
    };
}

test('inicializa el sorteo, anuncia el resultado y completa una ronda sin duplicados', async () => {
    assert.equal(selector.inicializar(null), null);
    assert.equal(selector.inicializar({ getElementById: () => null }), null);

    const vista = crearVistaSelector({ personas: [
        { id: 1, nombre: 'Ana' },
        { id: 2, nombre: 'Luis' },
        { id: 3, nombre: 'Sara' },
    ] });
    const resultado = selector.inicializar(vista.documento, { getRandomValues: valores => {
        valores[0] = 0;
        return valores;
    } });

    assert.equal(resultado.cantidad, 3);
    assert.equal(vista.elementos['selector-aprendiz-contador'].textContent, '3 participantes disponibles');
    const boton = vista.elementos['selector-aprendiz-sortear'];
    await boton.activar('click');
    await boton.activar('click');
    assert.equal(vista.temporizadores.length, 1, 'bloquea sorteos mientras anima el resultado');
    assert.equal(boton.disabled, true);
    assert.equal(vista.elementos['selector-aprendiz-mensaje'].textContent, 'Sorteando el próximo turno…');

    const seleccionados = [];
    for (let turno = 0; turno < 3; turno += 1) {
        if (turno > 0) await boton.activar('click');
        await vista.ejecutarTemporizador();
        seleccionados.push(vista.elementos['selector-aprendiz-nombre'].textContent);
        assert.equal(vista.elementos['selector-aprendiz'].attributes.get('aria-busy'), 'false');
    }

    assert.equal(new Set(seleccionados).size, 3);
    assert.equal(boton.textContent, 'Iniciar otra ronda');
    assert.match(vista.elementos['selector-aprendiz-mensaje'].textContent, /ronda completa/i);
});

test('maneja una lista vacía y la ausencia de controles', () => {
    const vista = crearVistaSelector();
    const inicializacion = selector.inicializar(vista.documento, null);

    assert.equal(inicializacion.cantidad, 0);
    assert.equal(vista.elementos['selector-aprendiz-sortear'].disabled, true);
    assert.match(vista.elementos['selector-aprendiz-mensaje'].textContent, /no hay aprendices activos/i);

    const sinControl = crearVistaSelector();
    sinControl.elementos['selector-aprendiz-sortear'] = null;
    assert.equal(selector.inicializar(sinControl.documento), null);
});

test('informa un error seguro y recupera los controles cuando falta el generador aleatorio', async () => {
    const vista = crearVistaSelector({ personas: [
        { id: 1, nombre: 'Ana' },
        { id: 2, nombre: 'Luis' },
    ] });
    selector.inicializar(vista.documento, null);
    const boton = vista.elementos['selector-aprendiz-sortear'];
    await boton.activar('click');
    await vista.ejecutarTemporizador();

    assert.equal(boton.disabled, false);
    assert.equal(vista.elementos['selector-aprendiz'].attributes.get('aria-busy'), 'false');
    assert.equal(vista.elementos['selector-aprendiz-nombre'].textContent, 'Sorteo no disponible');
    assert.match(vista.elementos['selector-aprendiz-mensaje'].textContent, /sorteo seguro/i);
});

test('abre y cierra pantalla completa y ofrece una vista ampliada de respaldo', async () => {
    const vista = crearVistaSelector({ personas: [{ id: 1, nombre: 'Ana' }] });
    selector.inicializar(vista.documento, { getRandomValues: valores => { valores[0] = 0; return valores; } });
    const panel = vista.elementos['selector-aprendiz'];
    const expandir = vista.elementos['selector-aprendiz-expandir'];
    const salir = vista.elementos['selector-aprendiz-salir'];

    await expandir.activar('click');
    assert.equal(vista.documento.fullscreenElement, panel);
    assert.equal(expandir.hidden, true);
    assert.equal(salir.hidden, false);
    assert.equal(salir.focused, true, 'el foco debe pasar al control visible');
    await salir.activar('click');
    assert.equal(vista.documento.fullscreenElement, null);
    assert.equal(expandir.hidden, false);
    assert.equal(expandir.focused, true, 'el foco debe regresar al control de ampliación');

    const errorAlSalir = crearVistaSelector({
        personas: [{ id: 1, nombre: 'Ana' }],
        salidaCompletaFalla: true,
    });
    selector.inicializar(errorAlSalir.documento, { getRandomValues: valores => { valores[0] = 0; return valores; } });
    await errorAlSalir.elementos['selector-aprendiz-expandir'].activar('click');
    await errorAlSalir.elementos['selector-aprendiz-salir'].activar('click');
    assert.equal(errorAlSalir.elementos['selector-aprendiz-salir'].hidden, false);

    const respaldo = crearVistaSelector({
        personas: [{ id: 1, nombre: 'Ana' }],
        solicitudCompletaFalla: true,
    });
    selector.inicializar(respaldo.documento, { getRandomValues: valores => { valores[0] = 0; return valores; } });
    await respaldo.elementos['selector-aprendiz-expandir'].activar('click');
    assert.equal(respaldo.elementos['selector-aprendiz'].classList.contains('is-fullscreen-fallback'), true);
    assert.equal(respaldo.elementos['selector-aprendiz-salir'].hidden, false);
    await respaldo.eventos.get('keydown')({ key: 'Escape' });
    assert.equal(respaldo.elementos['selector-aprendiz'].classList.contains('is-fullscreen-fallback'), false);

    const sinApi = crearVistaSelector({ personas: [{ id: 1, nombre: 'Ana' }], pantallaDisponible: false });
    selector.inicializar(sinApi.documento, { getRandomValues: valores => { valores[0] = 0; return valores; } });
    await sinApi.elementos['selector-aprendiz-expandir'].activar('click');
    assert.equal(sinApi.elementos['selector-aprendiz'].classList.contains('is-fullscreen-fallback'), true);
});
