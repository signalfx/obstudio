const setupURL = "https://github.com/signalfx/obstudio/blob/main/docs/USER.md#secure-token-storage";
const help = Object.freeze({
  darwin: { label: "Set up secure storage on macOS", url: "https://support.apple.com/guide/keychain-access/welcome/mac" },
  windows: { label: "Set up secure storage on Windows", url: "https://support.microsoft.com/en-us/windows/security/credential-manager-in-windows" },
  linux: { label: "Set up secure storage on Linux", url: setupURL },
});

function credentialStorageHelp(platform) {
  return Object.hasOwn(help, platform) ? { platform, ...help[platform] } : { label: "Set up secure storage", url: setupURL };
}

module.exports = { credentialStorageHelp };
