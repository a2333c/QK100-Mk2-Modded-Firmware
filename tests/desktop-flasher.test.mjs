import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

const root = new URL('../', import.meta.url);
function harness() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: ['scrPreset','mainPreset','imgPreset'].includes(id) ? 'official' : '', files: [], disabled: false,
      textContent: '', innerHTML: '', style: {}, classList: {add(){},remove(){}},
      appendChild(){}, addEventListener(){}, click(){}, setAttribute(){},
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    Uint8Array, ArrayBuffer, DataView, TextEncoder, TextDecoder, Date, Math,
    console, crypto:webcrypto, setTimeout, clearTimeout, setInterval, clearInterval,
    Blob, URL, navigator:{hid:{getDevices:async()=>[],addEventListener(){}}},
    window:{desktopFlasher:{setBusy(){}}},
    document:{getElementById:element,createElement:()=>element(Symbol()),
      querySelectorAll:()=>[...elements.values()],body:{appendChild(){}}},
    fetch:async()=>{throw new Error('Network not allowed in tests');},
    confirm:()=>true,
  });
  const html=fs.readFileSync(new URL('tools/flasher/index.html',root),'utf8');
  const source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInContext(source,context);
  return {call:(name,...args)=>context[name](...args),context,element,
    run:code=>vm.runInContext(code,context)};
}
const read = path=>new Uint8Array(fs.readFileSync(new URL(path,root)));
const main=read('firmware/main-v137-official.bin');
const lcd=read('firmware/screen-v120-official.bin');

test('main built-in presets load the selected pinned bytes instead of a stale local file',async()=>{
  for(const [preset,path] of [['official','/fw/main.bin'],['nobrightfloor','/fw/main-nobrightfloor.bin']]){
    const h=harness(),bytes=preset==='official'?main:read('firmware/main-v137-nobrightfloor.bin'),requests=[];
    h.element('mainPreset').value=preset;
    h.element('mainFile').files=[{arrayBuffer:async()=>{throw Error('Stale local file must not load');}}];
    h.context.fetch=async url=>{requests.push(url);return {ok:true,arrayBuffer:async()=>bytes.slice().buffer};};
    const selected=await h.call('loadMainBin');
    assert.deepEqual(selected,bytes);assert.deepEqual(requests,[path]);
    await h.call('validateMain',selected);
  }
});

test('main preset hash mismatch and unknown preset fail before opening any HID',async()=>{
  const h=harness(),wrong=main.slice();wrong[wrong.length-1]^=1;
  h.context.fetch=async()=>({ok:true,arrayBuffer:async()=>wrong.buffer});
  let requests=0;h.context.navigator.hid.requestDevice=async()=>{requests++;return [];};
  await assert.rejects(()=>h.call('enterIapMode'),/预选校验失败/);
  assert.equal(requests,0);
  h.element('mainPreset').value='unknown';
  await assert.rejects(()=>h.call('loadMainBin'),/未知主控预选/);
});

test('local main selection requires a file and does not fetch a built-in preset',async()=>{
  const h=harness();h.element('mainPreset').value='local';
  await assert.rejects(()=>h.call('loadMainBin'),/请选择本地主控固件/);
  h.element('mainFile').files=[{arrayBuffer:async()=>main.slice().buffer}];
  assert.deepEqual(await h.call('loadMainBin'),main);
});

test('changing main preset clears locked firmware and disables its pending write',()=>{
  const h=harness();h.context.mockBoot={opened:true};h.context.mockMain=main;
  h.run('preparedMain=mockMain;preparedMainInfo={sha256:"locked"};kbdBootDev=mockBoot;refreshControls();');
  assert.equal(h.element('btnMainFlash').disabled,false);
  h.element('mainPreset').value='nobrightfloor';h.element('mainPreset').onchange();
  assert.equal(h.run('preparedMain'),null);assert.equal(h.run('preparedMainInfo'),null);
  assert.equal(h.element('btnMainFlash').disabled,true);assert.equal(h.element('mainFile').disabled,true);
  h.element('mainPreset').value='local';h.element('mainPreset').onchange();
  assert.equal(h.element('mainFile').disabled,false);
});

test('official and alpha128 image presets load exactly their pinned complete pack',async()=>{
  for(const [preset,path,file] of [
    ['official','/fw/screen-image.bin','firmware/screen-image-v120-official.bin'],
    ['alpha128','/fw/screen-image-alpha128.bin','firmware/screen-image-v120-alpha128.bin'],
  ]){
    const h=harness(),bytes=read(file),requests=[];
    h.element('imgPreset').value=preset;
    h.element('imgFile').files=[{arrayBuffer:async()=>{throw Error('Stale local image must not load');}}];
    h.context.fetch=async url=>{requests.push(url);return {ok:true,arrayBuffer:async()=>bytes.slice().buffer};};
    const selected=await h.call('loadImageBin');
    assert.deepEqual(selected,bytes);assert.deepEqual(requests,[path]);
    const verified=await h.call('validateImage',selected);
    assert.equal(verified.bytes,11744376);assert.match(verified.label,preset==='official'?/官方/:/alpha128/);
  }
});

test('corrupted image preset stops before screen preflight, erase or writes',async()=>{
  const h=harness(),bytes=read('firmware/screen-image-v120-alpha128.bin');
  bytes[bytes.length-1]^=1;h.element('imgPreset').value='alpha128';
  h.context.fetch=async()=>({ok:true,arrayBuffer:async()=>bytes.buffer});
  h.context.fake=fakeDevice();h.run('scrDev=fake;scrReports=new Reports(fake,0);');
  await assert.rejects(()=>h.call('flashScreenImage'),/预选校验失败/);
  assert.equal(h.context.fake.writes.length,0);
  await assert.rejects(()=>h.call('validateImage',bytes),/禁止擦除或写入/);
});

test('local image selection requires a file and image choice stays independent from screen app',async()=>{
  const h=harness();h.element('imgPreset').value='local';h.element('imgPreset').onchange();
  assert.equal(h.element('imgFile').disabled,false);
  await assert.rejects(()=>h.call('loadImageBin'),/请选择本地图包/);
  const bytes=read('firmware/screen-image-v120-official.bin');
  h.element('imgFile').files=[{arrayBuffer:async()=>bytes.slice().buffer}];
  assert.deepEqual(await h.call('loadImageBin'),bytes);
  h.element('scrPreset').value='v20';h.element('scrPreset').onchange();
  assert.equal(h.element('imgPreset').value,'local');
  h.element('imgPreset').value='official';h.element('imgPreset').onchange();
  assert.equal(h.element('imgFile').disabled,true);
});

test('official board and screen pass validation; corrupted and cross-target files fail',async()=>{
  const h=harness();
  await h.call('validateMain',main);
  await h.call('validateScreen',lcd);
  const bad=main.slice();bad[bad.length-1]^=1;
  await assert.rejects(async()=>h.call('validateMain',bad));
  const badLcd=lcd.slice();badLcd[badLcd.length-1]^=1;
  await assert.rejects(async()=>h.call('validateScreen',badLcd));
  await assert.rejects(async()=>h.call('validateMain',lcd));
  await assert.rejects(async()=>h.call('validateScreen',main));
});

test('v20 reviewed app passes; image requires complete reviewed bytes',async()=>{
  const h=harness();
  const v20=read('firmware/screen-v20.bin');
  await h.call('validateScreen',v20);
  await h.call('validateImage',read('firmware/screen-image-v120-official.bin'));
  await assert.rejects(async()=>h.call('validateImage',lcd));
});

test('board envelopes preserve bytes and include official XOR checksum',()=>{
  const h=harness();
  for(const length of [1,56,57,133,267]) {
    const input=Uint8Array.from({length},(_,i)=>(i*17+4)&255);
    const frames=h.call('boardFrames',input);
    const joined=[];
    assert.equal(frames.length,Math.ceil(length/56));
    frames.forEach((frame,index)=>{
      assert.equal(frame.length,63);
      assert.equal(frame[0],0xaa);
      assert.equal(frame[2],frames.length-index-1);
      assert.equal(frame[3],index===0?0x80:0);
      const count=frame[4]|frame[5]<<8;
      let xor=0; for(let i=1;i<6+count;i++)xor^=frame[i];
      assert.equal(frame[6+count],xor);
      joined.push(...frame.slice(6,6+count));
    });
    assert.deepEqual(joined,Array.from(input));
  }
});

test('LCD packet checksums and per-chunk padding match strict updater',()=>{
  const h=harness();
  function check(packet) {
    const sum=packet.slice(0,-2).reduce((a,b)=>(a+b)&65535,0);
    assert.equal(packet[packet.length-2]|packet[packet.length-1]<<8,sum);
  }
  check(h.call('buildUpgradeStart',lcd.length));
  for(const length of [1,48,64,4096]) {
    const data=Uint8Array.from({length},(_,i)=>i&255);
    const packets=h.call('firmwarePackets',data);
    assert.equal(packets.length,Math.ceil(length/48));
    packets.forEach(packet=>{assert.equal(packet.length,52);check(packet);});
    const rebuilt=packets.flatMap(p=>Array.from(p.slice(2,50))).slice(0,length);
    assert.deepEqual(Array.from(rebuilt),Array.from(data));
  }
  const packet=h.call('imagePacket',0x123456,new Uint8Array([1,2,3]));
  assert.equal(packet.length,64);check(packet);
  assert.deepEqual(Array.from(packet.slice(2,5)),[0x56,0x34,0x12]);
});

test('LCD response parser rejects invalid checksum and embedded fake status',()=>{
  const h=harness();
  const ack=new Uint8Array(64);
  ack.set(h.call('appendSum16',new Uint8Array([0xff,0x70,3])));
  const good=h.call('parseScreenStatus',ack);
  assert.ok(good);
  const bad=ack.slice();bad[4]^=1;
  assert.throws(()=>h.call('parseScreenStatus',bad));
  assert.throws(()=>h.call('parseScreenStatus',new Uint8Array([0,0,0xff,0x70,3,0,0])));
});

function otaReply(h,status,command=0x70) {
  const data=new Uint8Array(64);
  data.set(h.call('appendSum16',Uint8Array.of(0xff,command,status)));
  return data;
}
function fakeDevice() {
  return {opened:true,writes:[],addEventListener(){},removeEventListener(){},
    async sendReport(id,data){this.writes.push({id,data:data.slice()});}};
}
test('LCD full stream consumes every block ACK and final CRC completion',async()=>{
  const h=harness();h.context.fake=fakeDevice();
  const bytes=Uint8Array.from({length:64+4096+61},(_,i)=>(i*13)&255);
  h.context.responses=[0,1,2,2,3].map(st=>otaReply(h,st));
  h.run('scrDev=fake; scrReports=new Reports(fake,0); scrReports.queue=responses;');
  await h.call('transferScreen',bytes);
  assert.equal(h.context.fake.writes.length,1+2+86+2);
  assert.equal(h.run('scrReports.queue.length'),0);
  assert.equal(h.run('screenFinished'),true);
});
test('LCD refused start sends no data and missing completion cannot succeed',async()=>{
  const h=harness();h.context.fake=fakeDevice();h.context.responses=[otaReply(h,4)];
  h.run('scrDev=fake; scrReports=new Reports(fake,0); scrReports.queue=responses;');
  await assert.rejects(()=>h.call('transferScreen',new Uint8Array(128)));
  assert.equal(h.context.fake.writes.length,1);
  assert.equal(h.run('screenFinished'),false);
  h.context.fake.writes=[];
  h.context.responses=[0,1,2].map(st=>otaReply(h,st));
  h.run('scrReports.queue=responses; const nextReal=scrReports.next.bind(scrReports); scrReports.next=timeout=>nextReal(15);');
  await assert.rejects(()=>h.call('transferScreen',new Uint8Array(128)),/超时/);
  assert.equal(h.run('screenFinished'),false);
});
test('device selection rejects wrong product, collection and report size',()=>{
  const h=harness();
  const dev={vendorId:0x36b0,productId:0x33ff,collections:[{usagePage:0xff00,usage:1,outputReports:[{reportId:63,items:[{reportSize:8,reportCount:63}]}]}]};
  assert.equal(h.call('exactDevice',dev,0x36b0,0x33ff,0xff00,1,63,63),true);
  assert.equal(h.call('exactDevice',{...dev,productId:0x3002},0x36b0,0x33ff,0xff00,1,63,63),false);
  assert.equal(h.call('exactDevice',dev,0x36b0,0x33ff,0xff,1,63,63),false);
  assert.equal(h.call('exactDevice',dev,0x36b0,0x33ff,0xff00,1,63,64),false);
});
function compositeKeyboardInterfaces(reportCount=63) {
  const descriptor=(usagePage,usage,reportId,count)=>({usagePage,usage,
    outputReports:[{reportId,items:[{reportSize:8,reportCount:count}]}]});
  const base={vendorId:0x36b0,productId:0x3059,productName:'QK100 Mk2',opened:false,
    opens:0,writes:0,async open(){this.opens++;this.opened=true;},
    async sendReport(){this.writes++;throw new Error('Selection must not write reports');}};
  return [
    {...base,collections:[descriptor(0xff60,0x61,0,64)]},
    {...base,collections:[{usagePage:1,usage:6,outputReports:[]}]},
    {...base,collections:[{usagePage:1,usage:2,outputReports:[]},
      {usagePage:1,usage:128,outputReports:[]},
      {usagePage:12,usage:1,outputReports:[]},descriptor(0xff00,1,63,reportCount),
      {usagePage:1,usage:6,outputReports:[]}]},
  ];
}

test('composite keyboard selection opens only the unique upgrade interface and sends no reports',async()=>{
  const h=harness(),devices=compositeKeyboardInterfaces();
  h.context.navigator.hid.requestDevice=async()=>devices;
  const selected=await h.call('choose',0x36b0,0x3059,0xff00,1,63,63,'有线主控');
  assert.equal(selected,devices[2]);
  await h.call('choose',0x36b0,0x3059,0xff00,1,63,63,'有线主控');
  assert.deepEqual(devices.map(d=>d.opens),[0,0,1]);
  assert.deepEqual(devices.map(d=>d.writes),[0,0,0]);
});

test('wrong composite report length is rejected without opening or writing',async()=>{
  const h=harness(),devices=compositeKeyboardInterfaces(64);
  h.context.navigator.hid.requestDevice=async()=>devices;
  await assert.rejects(()=>h.call('choose',0x36b0,0x3059,0xff00,1,63,63,'有线主控'),/匹配 0 个/);
  assert.deepEqual(devices.map(d=>d.opens),[0,0,0]);
  assert.deepEqual(devices.map(d=>d.writes),[0,0,0]);
});

test('cancelled or empty device choice reports no selection clearly',async()=>{
  const h=harness();
  h.context.navigator.hid.requestDevice=async()=>[];
  await assert.rejects(()=>h.call('choose',0x36b0,0x3059,0xff00,1,63,63,'有线主控'),/未选择|未发现/);
});

function configDevice(states=[0,1], refusals=new Set()) {
  let stateIndex=0;
  const listeners=new Set();
  return {vendorId:0x36b0,productId:0x3059,productName:'QK100 Mk2',opened:false,
    opens:0,closes:0,writes:[],
    collections:[{usagePage:0xff60,usage:0x61,outputReports:[{reportId:0,items:[{reportSize:8,reportCount:64}]}]}],
    async open(){this.opens++;this.opened=true;},
    async close(){this.closes++;this.opened=false;},
    addEventListener(name,callback){if(name==='inputreport')listeners.add(callback);},
    removeEventListener(name,callback){if(name==='inputreport')listeners.delete(callback);},
    get listeners(){return listeners.size;},
    async sendReport(id,data){
      this.writes.push({id,data:data.slice()});
      const command=data[1],reply=new Uint8Array(64);
      reply.set([0xaa,command,0,0,0,0,0,refusals.has(command)?0x0f:0x55]);
      if(command===0xe2)reply[8]=states[Math.min(stateIndex++,states.length-1)];
      for(const callback of listeners)callback({reportId:0,data:new DataView(reply.buffer)});
    },
  };
}
const configCommands=device=>device.writes.map(w=>w.data[1]);

test('screen USB enable uses only official control commands and confirms state before continuing',async()=>{
  const h=harness(),device=configDevice();
  h.context.navigator.hid.requestDevice=async()=>[device];
  await h.call('enableScreenUsb');
  assert.deepEqual(configCommands(device),[0x10,0xe2,0xe0,0xe2,0x11]);
  for(const {id,data} of device.writes){
    assert.equal(id,0);assert.equal(data.length,64);assert.equal(data[0],0xaa);
    assert.ok(data.slice(2).every(byte=>byte===0),'no config fields or flash payload written');
  }
  assert.equal(device.opens,1);assert.equal(device.closes,1);
  assert.equal(device.opened,false);assert.equal(device.listeners,0);
});

test('already enabled screen USB is queried without toggling or writing settings',async()=>{
  const h=harness(),device=configDevice([1]);
  h.context.navigator.hid.requestDevice=async()=>[device];
  await h.call('enableScreenUsb');
  assert.deepEqual(configCommands(device),[0x10,0xe2,0x11]);
  assert.equal(device.closes,1);assert.equal(device.listeners,0);
});

test('unknown screen USB state stops before enable and closes the control session',async()=>{
  const h=harness(),device=configDevice([2]);
  h.context.navigator.hid.requestDevice=async()=>[device];
  await assert.rejects(()=>h.call('enableScreenUsb'),/未知/);
  assert.deepEqual(configCommands(device),[0x10,0xe2,0x11]);
  assert.equal(device.opened,false);assert.equal(device.listeners,0);
});

test('refused or unconfirmed USB enable stops without retry, setting writes or flash commands',async()=>{
  for(const device of [configDevice([0],new Set([0xe0])),configDevice([0,0])]){
    const h=harness();h.context.navigator.hid.requestDevice=async()=>[device];
    await assert.rejects(()=>h.call('enableScreenUsb'),/拒绝|未确认/);
    assert.deepEqual(configCommands(device),device.writes.length===4?[0x10,0xe2,0xe0,0x11]:[0x10,0xe2,0xe0,0xe2,0x11]);
    assert.equal(device.opened,false);assert.equal(device.listeners,0);
  }
});

test('refused control session does not send state queries or end an unstarted session',async()=>{
  const h=harness(),device=configDevice([0],new Set([0x10]));
  h.context.navigator.hid.requestDevice=async()=>[device];
  await assert.rejects(()=>h.call('enableScreenUsb'),/拒绝/);
  assert.deepEqual(configCommands(device),[0x10]);
  assert.equal(device.opened,false);assert.equal(device.listeners,0);
});

test('cancelled control selection sends no screen enable command',async()=>{
  const h=harness();h.context.navigator.hid.requestDevice=async()=>[];
  await assert.rejects(()=>h.call('enableScreenUsb'),/未选择|未发现/);
});

test('cancelled screen reconnect clears stale handles and leaves write controls unavailable',async()=>{
  const h=harness();
  h.context.oldScreen={...fakeDevice(),closes:0,async close(){this.closes++;this.opened=false;}};
  const known={vendorId:0x1919,productId:0x1919,collections:[{usagePage:0xff,usage:1,
    outputReports:[{reportId:0,items:[{reportSize:8,reportCount:64}]}]}]};
  h.context.navigator.hid.getDevices=async()=>[known];
  h.context.navigator.hid.requestDevice=async()=>[];
  h.run('scrDev=oldScreen;scrReports=new Reports(oldScreen,0);');
  await h.call('guard',h.context.connectScreen)();
  assert.equal(h.context.oldScreen.closes,1);assert.equal(h.run('scrDev'),null);
  assert.equal(h.run('scrReports'),null);assert.equal(h.element('btnScrFlash').disabled,true);
  assert.equal(h.element('btnImgFlash').disabled,true);assert.equal(h.context.oldScreen.writes.length,0);
});

test('screen preparation and LCD authorization require separate clicks, and cancellation resets preparation',async()=>{
  const h=harness(),device=configDevice([1]),requests=[];
  h.context.navigator.hid.getDevices=async()=>[];
  h.context.navigator.hid.requestDevice=async options=>{
    requests.push(options.filters[0]);
    return requests.length===1?[device]:[];
  };
  const click=h.call('guard',h.context.connectScreen);
  await click();
  assert.equal(requests.length,1,'preparation must not request LCD after asynchronous control exchange');
  assert.equal(requests[0].vendorId,0x36b0);assert.equal(requests[0].usagePage,0xff60);
  assert.deepEqual(configCommands(device),[0x10,0xe2,0x11]);
  assert.equal(h.run('screenUsbReady'),true);
  assert.equal(h.element('btnScrLink').textContent,'选择 LCD 屏幕');
  assert.equal(h.element('btnScrFlash').disabled,true);
  assert.equal(h.element('btnImgFlash').disabled,true);
  await click();
  assert.equal(requests.length,2,'second click performs only LCD authorization');
  assert.equal(requests[1].vendorId,0x1919);assert.equal(requests[1].productId,0x1919);
  assert.equal(requests[1].usagePage,0xff);assert.equal(requests[1].usage,1);
  assert.deepEqual(configCommands(device),[0x10,0xe2,0x11],'second click must not repeat main control commands');
  assert.equal(h.run('screenUsbReady'),false);
  assert.equal(h.element('btnScrLink').textContent,'连接屏幕');
  assert.equal(h.run('scrDev'),null);assert.equal(h.run('scrReports'),null);
  assert.equal(h.element('btnScrFlash').disabled,true);
  assert.equal(h.element('btnImgFlash').disabled,true);
});

test('enter boot uses exact official frame once; invalid file never opens HID',async()=>{
  const h=harness();
  let requests=0;
  h.context.navigator.hid.requestDevice=async()=>{requests++;return [];};
  h.element('mainPreset').value='local';
  h.element('mainFile').files=[{arrayBuffer:async()=>new Uint8Array(10).buffer}];
  await assert.rejects(()=>h.call('enterIapMode'));
  assert.equal(requests,0);
  assert.equal(h.call('bootFrame').length,63);
  assert.equal(Buffer.from(h.call('bootFrame').slice(0,15)).toString('hex'),'aa0000800700c002006400690f4700');
});
test('board data blocks preserve offset, last-block sentinel and CRC',()=>{
  const h=harness();
  const payload=main.slice(128),count=Math.ceil(payload.length/256);
  const start=h.call('buildMainStart',main);
  assert.equal(start.length,133);
  assert.deepEqual(Array.from(start.slice(3,131)),Array.from(main.slice(0,128)));
  for(const index of [0,1,count-1]) {
    const packet=h.call('buildMainWrite',payload,index,256);
    const view=new DataView(packet.buffer);
    assert.equal(view.getUint16(3,true),index===count-1?65535:index);
    assert.equal(view.getUint32(5,true),index*256);
    assert.deepEqual(Array.from(packet.slice(9,-2)),Array.from(payload.slice(index*256,(index+1)*256)));
    assert.equal(view.getUint16(packet.length-2,false),h.call('crc16',packet.slice(0,-2)));
  }
});
test('valid CRC cannot disguise a different product in the board payload',async()=>{
  const h=harness(),wrong=main.slice();
  wrong[0x2806a]=0x5a;
  const payloadCrc=h.call('crc16',wrong.slice(128));
  wrong[62]=payloadCrc>>8;wrong[63]=payloadCrc&255;
  const headerCrc=h.call('crc16',wrong.slice(0,126));
  wrong[126]=headerCrc>>8;wrong[127]=headerCrc&255;
  await assert.rejects(()=>h.call('validateMain',wrong));
});
test('board ACK errors, mismatched echo and missing reply stop the transaction',async()=>{
  const h=harness();h.context.fake=fakeDevice();h.run('testReports=new Reports(fake,63);');
  h.context.reply=Uint8Array.of(0xb0,0,0xa0);h.run('testReports.queue=[reply]');
  await h.run('testReports.boardAck(0xa0,15)');
  h.context.reply=Uint8Array.of(0xb0,0,0);h.run('testReports.queue=[reply]');
  await h.run('testReports.boardAck(0xa0,15)');
  h.context.reply=Uint8Array.of(0xb0,0xe2,0xa0);h.run('testReports.queue=[reply]');
  await assert.rejects(()=>h.run('testReports.boardAck(0xa0,15)'));
  h.context.reply=Uint8Array.of(0xb0,0,0xa1);h.run('testReports.queue=[reply]');
  await assert.rejects(()=>h.run('testReports.boardAck(0xa0,15)'));
  await assert.rejects(()=>h.run('testReports.boardAck(0xa0,15)'),/超时/);
});
test('interrupted write releases lock and requires explicit reconnect',async()=>{
  const h=harness();h.context.fake={...fakeDevice(),async close(){this.opened=false;}};
  h.run('scrDev=fake; scrReports=new Reports(fake,0);');
  const guarded=h.run('guard(async()=>{writeKind="screen";throw Error("test stop");})');
  await guarded();
  assert.equal(h.run('operation'),false);
  assert.equal(h.run('scrDev'),null);
  assert.equal(h.element('btnScrFlash').disabled,true);
  assert.equal(h.context.fake.opened,false);
});
