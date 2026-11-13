const asar=require('@electron/asar');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const archive=path.join(__dirname,'release','win-unpacked','resources','app.asar');
const manifest=JSON.parse(asar.extractFile(archive,path.join('assets','manifest.json')).toString('utf8'));
const checks=[];
for(const [name,record] of Object.entries(manifest)) {
  const bytes=asar.extractFile(archive,path.join('assets',...name.split('/')));
  const sha256=crypto.createHash('sha256').update(bytes).digest('hex');
  if(sha256!==record.sha256 || bytes.length!==record.bytes) throw new Error(`Packaged asset mismatch: ${name}`);
  checks.push({name,sha256,bytes:bytes.length});
}
for(const name of ['main.cjs','policy.cjs','preload.cjs','chooser.html']) {
  if(!asar.extractFile(archive,name).equals(fs.readFileSync(path.join(__dirname,name)))) throw new Error(`Packaged source mismatch: ${name}`);
}
if(!asar.extractFile(archive,path.join('assets','index.html')).equals(fs.readFileSync(path.join(__dirname,'../tools/flasher/index.html')))) throw new Error('Packaged renderer differs from final source');
fs.writeFileSync(path.join(__dirname,'release','verification.json'),JSON.stringify({checks,sourcesMatch:true},null,2));
console.log(JSON.stringify({assets:checks.length,sourcesMatch:true}));
