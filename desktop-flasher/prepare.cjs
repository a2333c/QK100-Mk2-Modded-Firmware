const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const files = {
  'index.html': path.join(root, 'tools/flasher/index.html'),
  'fw/main.bin': path.join(root, 'firmware/main-v137-official.bin'),
  'fw/main-nobrightfloor.bin': path.join(root, 'firmware/main-v137-nobrightfloor.bin'),
  'fw/screen-app.bin': path.join(root, 'firmware/screen-v120-official.bin'),
  'fw/screen-image.bin': path.join(root, 'firmware/screen-image-v120-official.bin'),
  'fw/screen-image-alpha128.bin': path.join(root, 'firmware/screen-image-v120-alpha128.bin'),
  'fw/screen-v20.bin': path.join(root, 'firmware/screen-v20.bin'),
};
const expected = {
  'fw/main.bin':'2a9d951f98b2d570a07f069eeefac77f60d1cbfebc01f133dc34cb5e8fb0aa03',
  'fw/main-nobrightfloor.bin':'52904d7d6e767ea5195862a54c84fc922a022c2bfaf6370937c7b4f864c6e749',
  'fw/screen-app.bin':'f4d0dc14baa423cbea0946b31d34cf0fe61fa383cc103d94943b5a0a7267c68f',
  'fw/screen-image.bin':'50beaa063d4a2464fb7525094c6e49a5bf8ba0ab059c61a1a70ad5c6acda5b9d',
  'fw/screen-image-alpha128.bin':'281dd4618882036daa9058f2213efcd33a5dd76550b5e5375467b53e8a938c7f',
  'fw/screen-v20.bin':'ea159057a2e91d488ebe7a74e8e05e53f13933cde569339013a3ba409e618ab4',
};
const manifest = {};
// Validate every source before copying so a missing or changed asset fails the build.
for (const [name,source] of Object.entries(files)) {
  if (!fs.existsSync(source)) throw new Error(`Missing asset: ${source}`);
  const bytes=fs.readFileSync(source);
  const sha256=crypto.createHash('sha256').update(bytes).digest('hex');
  if(expected[name] && expected[name]!==sha256) throw new Error(`Firmware SHA-256 mismatch: ${source}`);
  manifest[name]={sha256,bytes:bytes.length};
}
for (const [name, source] of Object.entries(files)) {
  const target = path.join(__dirname, 'assets', name);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
}
fs.writeFileSync(path.join(__dirname,'assets','manifest.json'),JSON.stringify(manifest,null,2));
console.log('Copied standalone page and firmware assets.');
