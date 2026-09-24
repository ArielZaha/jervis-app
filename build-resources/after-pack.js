// After the app is assembled, before the installer is made.
// macOS: the app isn't signed with a paid Apple Developer ID, so give it a consistent ad-hoc signature. Without one,
// Apple Silicon Macs report the downloaded app as "damaged" instead of offering "Open Anyway".
const { execFileSync } = require('child_process');
const path = require('path');

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  execFileSync('xattr', ['-cr', app]);   // Finder info and download marks on copied files make codesign refuse
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: 'inherit' });
  execFileSync('codesign', ['--verify', '--deep', '--strict', app], { stdio: 'inherit' });
};
