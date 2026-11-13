const SUPPORTED_PATHS = ['/index.html', '/fw/main.bin', '/fw/main-nobrightfloor.bin', '/fw/screen-app.bin', '/fw/screen-image.bin', '/fw/screen-image-alpha128.bin', '/fw/screen-v20.bin'];
const supported = d => !!d && ((d.vendorId === 0x36b0 && [0x3059, 0x33ff].includes(d.productId)) || (d.vendorId === 0x1919 && d.productId === 0x1919));
function sameOrigin(value, expected) {
  try { return new URL(value).origin === expected; } catch { return false; }
}
// Electron's HID service checks have no WebContents and supply securityOrigin.
// This policy is installed only on the main window's private in-memory session.
function allowHidCheck(webContents, mainContents, permission, requestingOrigin, details, origin) {
  return permission === 'hid' && sameOrigin(requestingOrigin, origin) &&
    (webContents === mainContents || (webContents === null && sameOrigin(details?.securityOrigin, origin)));
}
function deviceIdentity(device) {
  if (!supported(device)) return null;
  const reports = list => (list || []).map(r => ({id:r.reportId,bits:(r.items || []).reduce((sum,i)=>sum+i.reportSize*i.reportCount,0)}));
  const collections = list => (list || []).map(c => ({page:c.usagePage,usage:c.usage,input:reports(c.inputReports),output:reports(c.outputReports),feature:reports(c.featureReports),children:collections(c.children)}));
  return JSON.stringify({vendorId:device.vendorId,productId:device.productId,name:device.name || '',serial:device.serialNumber || '',collections:collections(device.collections)});
}
module.exports = { SUPPORTED_PATHS, supported, sameOrigin, allowHidCheck, deviceIdentity };
