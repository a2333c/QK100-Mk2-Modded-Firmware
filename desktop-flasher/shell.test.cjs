const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { supported, SUPPORTED_PATHS, sameOrigin, allowHidCheck, deviceIdentity } = require('./policy.cjs');
test('selected descriptor identity matches ID-less Electron open callback and rejects other interfaces', () => {
  const selected={deviceId:'chooser-id',vendorId:0x36b0,productId:0x3059,name:'QK100 Mk2',serialNumber:'test',collections:[{usagePage:0xff00,usage:1,inputReports:[{reportId:63,items:[{reportSize:8,reportCount:63}]}],outputReports:[{reportId:63,items:[{reportSize:8,reportCount:63}]}]}]};
  const opened={...selected};delete opened.deviceId;
  assert.equal(deviceIdentity(opened),deviceIdentity(selected));
  for(const changed of [{...opened,serialNumber:'other'},{...opened,productId:0x33ff},{...opened,collections:[{...opened.collections[0],usagePage:0xff60}]},{...opened,collections:[{...opened.collections[0],outputReports:[]}]}]) assert.notEqual(deviceIdentity(changed),deviceIdentity(selected));
  assert.equal(deviceIdentity({vendorId:0x36b0,productId:0x3002}),null);
});
test('Electron HID service permits its null-WebContents check only for app security origin', () => {
  const main={}, other={}, origin='http://127.0.0.1:52123';
  assert.ok(allowHidCheck(null,main,'hid',origin+'/',{isMainFrame:false,securityOrigin:origin+'/'},origin));
  assert.ok(allowHidCheck(main,main,'hid',origin+'/',{},origin));
  for (const [wc,permission,request,details] of [
    [other,'hid',origin+'/',{securityOrigin:origin+'/'}],
    [null,'hid',origin+'/',{}],
    [null,'hid',origin+'/',{securityOrigin:'http://127.0.0.1:52124/'}],
    [null,'hid','http://127.0.0.1:52124/',{securityOrigin:origin+'/'}],
    [main,'usb',origin+'/',{}],
    [main,'hid','invalid',{}],
  ]) assert.equal(allowHidCheck(wc,main,permission,request,details,origin),false);
  assert.equal(sameOrigin('http://127.0.0.1:52123.evil.test/',origin),false);
});
test('hardware permission rejects unrelated HID and receiver', () => {
  for (const device of [{vendorId:0x36b0,productId:0x3059},{vendorId:0x36b0,productId:0x33ff},{vendorId:0x1919,productId:0x1919}]) assert.ok(supported(device));
  for (const device of [null,{}, {vendorId:0x36b0,productId:0x3002},{vendorId:0x36b0,productId:0x305a},{vendorId:0x1919,productId:0x3059}]) assert.equal(supported(device),false);
});
test('packaged resource whitelist includes exactly page and reviewed firmware assets', () => {
  assert.equal(SUPPORTED_PATHS.length,7);
  for (const name of SUPPORTED_PATHS) {
    const file=path.join(__dirname,'assets',name);
    assert.ok(fs.existsSync(file),name);
  }
  assert.ok(!SUPPORTED_PATHS.includes('/../package.json'));
});
test('prepared asset bytes match generated SHA-256 manifest',()=>{
  const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'assets','manifest.json'),'utf8'));
  for(const [name,record] of Object.entries(manifest)) {
    const bytes=fs.readFileSync(path.join(__dirname,'assets',name));
    assert.equal(bytes.length,record.bytes,name);
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),record.sha256,name);
  }
});
