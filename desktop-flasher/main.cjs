const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const { supported, SUPPORTED_PATHS, sameOrigin, allowHidCheck, deviceIdentity } = require('./policy.cjs');
let server, mainWindow, chooser, pending, origin, closing = false, writeBusy = false;
const explicitlySelected = new Set();
const selectedIdentities = new Set();
const assets = path.join(__dirname, 'assets');
function hidStatus(message) {
  if (mainWindow && !mainWindow.webContents.isDestroyed()) mainWindow.webContents.send('flasher-hid-status', message);
}
function serve(req, res) {
  if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405).end(); return; }
  let name;
  try { name = decodeURIComponent(new URL(req.url, origin).pathname); } catch { res.writeHead(400).end(); return; }
  if (name === '/') name = '/index.html';
  if (!SUPPORTED_PATHS.includes(name)) { res.writeHead(404).end(); return; }
  fs.readFile(path.join(assets, name.slice(1)), (error, bytes) => {
    if (error) { res.writeHead(404).end(); return; }
    res.writeHead(200, { 'Content-Type': name.endsWith('.html') ? 'text/html; charset=utf-8' : 'application/octet-stream', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'none'" });
    res.end(req.method === 'HEAD' ? undefined : bytes);
  });
}
function showDevices() {
  if (chooser && pending) chooser.webContents.send('chooser-devices', pending.devices.filter(supported).map(d => ({ deviceId:d.deviceId, name:d.name || 'QK100 HID', vendorId:d.vendorId, productId:d.productId })));
}
function finishSelection(id) {
  if (!pending) return;
  const p = pending; pending = null;
  const device = p.devices.find(d => d.deviceId === id && supported(d));
  const selected = device ? id : '';
  if(selected) { explicitlySelected.add(selected); selectedIdentities.add(deviceIdentity(device)); }
  hidStatus(selected ? '已授权所选 HID 设备，正在核查升级接口。' : '设备选择已取消，未连接或写入设备。');
  p.callback(selected);
  if (chooser) { const w=chooser; chooser=null; w.close(); }
}
ipcMain.on('chooser-ready', e => { if (chooser && e.sender === chooser.webContents) showDevices(); });
ipcMain.on('chooser-select', (e, id) => { if (chooser && e.sender === chooser.webContents && typeof id === 'string') finishSelection(id); });
ipcMain.on('flasher-busy', (e, value) => { if(mainWindow && e.sender===mainWindow.webContents && typeof value==='boolean') writeBusy=value; });

async function start() {
  server = http.createServer(serve);
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  origin = `http://127.0.0.1:${server.address().port}`;
  mainWindow = new BrowserWindow({ width: 1020, height: 920, minWidth:760, minHeight:640, title:'QK100 固件升级', autoHideMenuBar:true, webPreferences:{ partition:'qk100-flasher', preload:path.join(__dirname,'preload.cjs'), contextIsolation:true, sandbox:true, nodeIntegration:false } });
  const session = mainWindow.webContents.session;
  session.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    const allowed = allowHidCheck(webContents, mainWindow.webContents, permission, requestingOrigin, details, origin);
    if (permission === 'hid' && !allowed) hidStatus('HID 权限检查未通过：请求页面不属于本应用。');
    return allowed;
  });
  session.setPermissionRequestHandler((webContents, permission, callback) => callback(permission === 'hid' && webContents === mainWindow.webContents));
  session.setDevicePermissionHandler(details => {
    // Electron 40 omits deviceId/guid from the open-time permission callback.
    // Match only descriptors recorded during the user's native chooser selection.
    return details.deviceType === 'hid' && sameOrigin(details.origin, origin) && supported(details.device) &&
      (details.device.deviceId ? explicitlySelected.has(details.device.deviceId) : selectedIdentities.has(deviceIdentity(details.device)));
  });
  session.on('select-hid-device', (event, details, callback) => {
    event.preventDefault();
    const frameURL = details.frame && details.frame.top && details.frame.top.url;
    if (frameURL !== `${origin}/` && frameURL !== `${origin}/index.html`) { hidStatus('HID 设备选择已拒绝：请求页面不属于本应用。'); callback(''); return; }
    finishSelection('');
    pending={callback, devices:details.deviceList.filter(supported)};
    hidStatus(`HID 枚举完成：找到 ${pending.devices.length} 个受支持的候选设备。`);
    if (!pending.devices.length) { finishSelection(''); return; }
    chooser = new BrowserWindow({ parent:mainWindow, modal:true, width:580, height:420, resizable:false, autoHideMenuBar:true, webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,sandbox:true,nodeIntegration:false} });
    chooser.on('closed', () => { chooser=null; if(pending){const p=pending;pending=null;p.callback('');} });
    chooser.loadFile(path.join(__dirname,'chooser.html'));
  });
  session.on('hid-device-added', (_event, device) => { if(pending && supported(device)){pending.devices.push(device);showDevices();} });
  session.on('hid-device-removed', (_event, device) => { if(pending){pending.devices=pending.devices.filter(d=>d.deviceId!==device.deviceId);showDevices();} });
  mainWindow.webContents.setWindowOpenHandler(() => ({ action:'deny' }));
  mainWindow.webContents.on('will-navigate', (event, url) => { if (!url.startsWith(origin + '/')) event.preventDefault(); });
  mainWindow.on('close', event => {
    if (closing) return;
    if (writeBusy) {
      event.preventDefault();
      dialog.showMessageBox(mainWindow, { type:'warning', message:'正在写入固件，请等待完成后再关闭应用。', buttons:['返回'] });
    }
  });
  await mainWindow.loadURL(origin + '/');
  if (process.argv.includes('--smoke-test')) {
    const check = await mainWindow.webContents.executeJavaScript("({title:document.title,url:location.href,hid:!!navigator.hid,buttons:document.querySelectorAll('button').length})");
    check.electron=process.versions.electron;
    check.chrome=process.versions.chrome;
    const reportDir=path.join(app.isPackaged ? (process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(app.getPath('exe'))) : __dirname,'build');
    fs.mkdirSync(reportDir,{recursive:true});
    await new Promise(resolve=>setTimeout(resolve,300));
    fs.writeFileSync(path.join(reportDir,'smoke.png'),(await mainWindow.webContents.capturePage()).toPNG());
    fs.writeFileSync(path.join(reportDir,'smoke.json'),JSON.stringify(check,null,2));
    console.log(JSON.stringify(check));
    if (!check.hid || !check.buttons) app.exit(2); else {closing=true;app.quit();}
  }
}
if (!app.requestSingleInstanceLock()) app.quit();
else { app.on('second-instance',()=>{if(mainWindow){mainWindow.restore();mainWindow.focus();}});app.whenReady().then(start).catch(error=>{dialog.showErrorBox('启动失败',error.message);app.quit();}); }
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',event=>{if(writeBusy){event.preventDefault();if(mainWindow)mainWindow.focus();}});
app.on('will-quit',()=>{finishSelection('');if(server)server.close();});
module.exports = { supported };
