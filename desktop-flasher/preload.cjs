const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('desktopFlasher', {
  setBusy: (value) => { if (typeof value === 'boolean') ipcRenderer.send('flasher-busy', value); },
  onHidStatus: (callback) => { if (typeof callback === 'function') ipcRenderer.on('flasher-hid-status', (_event, message) => { if (typeof message === 'string') callback(message); }); },
});
contextBridge.exposeInMainWorld('deviceChooser', {
  ready: () => ipcRenderer.send('chooser-ready'),
  select: (deviceId) => ipcRenderer.send('chooser-select', deviceId),
  onDevices: (callback) => ipcRenderer.on('chooser-devices', (_event, devices) => callback(devices)),
});
