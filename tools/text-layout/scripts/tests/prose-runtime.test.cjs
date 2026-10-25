const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const filename = path.resolve(__dirname,'../../templates/prose-layout.js');
const source = fs.readFileSync(filename,'utf8');

function paragraph(width, blocked=false, initialTextAlign='') {
  const values = new Map(initialTextAlign ? [['text-align',initialTextAlign]] : []);
  return {width,isConnected:true,closest:()=>blocked,getBoundingClientRect(){return {width:this.width};},
    style:{getPropertyValue:key=>values.get(key),setProperty:(key,value)=>values.set(key,value),removeProperty:key=>values.delete(key)}};
}

function surface(readyState='complete', supported=true, initialTextAlign='') {
  const elements=[paragraph(639,false,initialTextAlign),paragraph(640),paragraph(900,true)];
  const events=new Map(); const observers=[];
  class Observer {
    constructor(callback){this.callback=callback;this.observed=new Set();observers.push(this);}
    observe(element){this.observed.add(element);}
    unobserve(element){this.observed.delete(element);}
    disconnect(){this.observed.clear();}
  }
  const document={readyState,documentElement:{},querySelectorAll:()=>elements,addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name)};
  const host={document,MutationObserver:Observer,getComputedStyle:()=>({fontSize:'16px'}),addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name),module:{exports:{}}};
  if(supported)host.ResizeObserver=Observer;
  vm.runInNewContext(source,host,{filename});
  return {host,elements,observers,events};
}

test('el ancho real gobierna la alineación y responde a cambios sin alterar controles',()=>{
  const {host,elements,observers,events}=surface();
  assert.equal(elements[0].style.getPropertyValue('--text-align-reading'),'start');
  assert.equal(elements[1].style.getPropertyValue('--text-align-reading'),'justify');
  assert.equal(elements[0].style.getPropertyValue('text-align'),'start');
  assert.equal(elements[1].style.getPropertyValue('text-align'),'justify');
  assert.equal(elements[2].style.getPropertyValue('--text-align-reading'),undefined);
  elements[0].width=800; observers[0].callback([{target:elements[0]}]);
  assert.equal(elements[0].style.getPropertyValue('--text-align-reading'),'justify');
  assert.equal(elements[0].style.getPropertyValue('text-align'),'justify');
  elements[0].isConnected=false;
  elements.push(paragraph(700)); observers[1].callback();
  assert.equal(observers[0].observed.has(elements[0]),false);
  assert.equal(elements[3].style.getPropertyValue('--text-align-reading'),'justify');
  elements[3].width=300; events.get('resize')();
  assert.equal(elements[3].style.getPropertyValue('--text-align-reading'),'start');
  events.get('load')();
  const instance=host.DevBrainProseLayout; host.module.exports.start();
  assert.equal(host.DevBrainProseLayout,instance);
  instance.destroy();
  assert.equal(observers[0].observed.size,0);
  assert.equal(elements[3].style.getPropertyValue('--text-align-reading'),undefined);
  assert.equal(elements[3].style.getPropertyValue('text-align'),undefined);
});

test('restaura la alineación inline previa al desmontar el runtime',()=>{
  const {host,elements}=surface('complete',true,'center');
  assert.equal(elements[0].style.getPropertyValue('text-align'),'start');
  host.DevBrainProseLayout.destroy();
  assert.equal(elements[0].style.getPropertyValue('text-align'),'center');
});

test('el inicio espera al DOM y conserva una salida segura si falta ResizeObserver',()=>{
  const waiting=surface('loading');
  assert.equal(waiting.host.DevBrainProseLayout,undefined);
  waiting.events.get('DOMContentLoaded')();
  assert.ok(waiting.host.DevBrainProseLayout);
  const unsupported=surface('complete',false);
  assert.equal(unsupported.host.DevBrainProseLayout,undefined);
  const noDocument={module:{exports:{}}}; vm.runInNewContext(source,noDocument,{filename});
  assert.equal(typeof noDocument.module.exports.initProseLayout,'function');
});
