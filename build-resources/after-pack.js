// After the app is assembled, before the installer is made.
// macOS: Jervis isn't signed with a paid Apple Developer ID. It's signed with Jervis's own certificate when the build
// has it (JERVIS_MAC_IDENTITY, set up by the GitHub workflow): every version then has the same signing identity, so
// macOS keeps the permissions people gave Jervis (Accessibility, microphone) across updates. Without the certificate
// (a local build) it gets an ad-hoc signature, which Apple Silicon needs, but which changes with every build.
const { execFileSync } = require('child_process');
const path = require('path');

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const identity = process.env.JERVIS_MAC_IDENTITY || '-';
  execFileSync('xattr', ['-cr', app]);   // Finder info and download marks on copied files make codesign refuse
  execFileSync('codesign', ['--force', '--deep', '--sign', identity, app], { stdio: 'inherit' });
  execFileSync('codesign', ['--verify', '--deep', '--strict', app], { stdio: 'inherit' });
  const requirement = execFileSync('codesign', ['-d', '-r-', app], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  console.log(`  • signed with ${identity === '-' ? 'an ad-hoc signature' : identity}: ${requirement.trim().split('\n').pop()}`);
  if (identity !== '-' && !/certificate (leaf|root) = H/.test(requirement)) {
    throw new Error('The app was not signed with Jervis’s certificate, so macOS would drop permissions on update.');
  }
};
