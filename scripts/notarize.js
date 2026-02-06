const { notarize } = require('@electron/notarize');

exports.default = async function notarizing(context) {
  const { electronPlatformName, appOutDir } = context;

  if (electronPlatformName !== 'darwin') {
    console.log('Skipping notarization — not macOS.');
    return;
  }

  const appName = context.packager.appInfo.productFilename;
  const appBundleId = context.packager.appInfo.id;

  const apiKey = process.env.APPLE_API_KEY;
  const apiKeyId = process.env.APPLE_API_KEY_ID;
  const apiIssuer = process.env.APPLE_API_ISSUER;

  if (!apiKey || !apiKeyId || !apiIssuer) {
    console.log('Skipping notarization — APPLE_API_KEY, APPLE_API_KEY_ID, or APPLE_API_ISSUER not set.');
    return;
  }

  const appPath = `${appOutDir}/${appName}.app`;
  console.log(`afterSign hook: notarizing ${appBundleId}`);
  console.log(`  appPath: ${appPath}`);
  console.log(`  apiKey: ${apiKey}`);
  console.log(`  apiKeyId: ${apiKeyId}`);

  try {
    await notarize({
      appPath,
      appleApiKey: apiKey,
      appleApiKeyId: apiKeyId,
      appleApiIssuer: apiIssuer,
    });
    console.log('Notarization complete.');
  } catch (err) {
    console.error('Notarization FAILED:', err);
    throw err;
  }
};
