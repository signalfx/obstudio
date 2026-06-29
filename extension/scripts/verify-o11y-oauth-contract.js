const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..', '..');
const workspaceRoot = path.dirname(repoRoot);
const signalViewRoot =
    process.env.O11Y_SIGNALVIEW_REPO || path.join(workspaceRoot, 'signalview-oauth');
const authServerRoot =
    process.env.O11Y_AUTH_SERVER_REPO || path.join(workspaceRoot, 'app-platform-server-oauth');

function read(root, relativePath) {
    const filePath = path.join(root, relativePath);
    if (!fs.existsSync(filePath)) {
        throw new Error(`OAuth contract dependency is missing: ${filePath}`);
    }
    return fs.readFileSync(filePath, 'utf8');
}

function requireText(source, expected, owner) {
    assert.ok(source.includes(expected), `${owner} is missing OAuth contract value: ${expected}`);
}

const oauthClient = read(repoRoot, 'observer/internal/o11yoauth/client.go');
const signalViewPage = read(
    signalViewRoot,
    'src/common/security/oauth/OAuthAuthorize.tsx'
);
const signalViewParams = read(
    signalViewRoot,
    'src/common/security/oauth/oauthAuthorizationParams.ts'
);
const signalViewServer = read(signalViewRoot, 'dev/oauth-authorization-dev-server.js');
const authResource = read(
    authServerRoot,
    'auth-server/src/main/java/com/splunk/o11y/identity/oauth/OAuthAuthorizationResource.java'
);
const authClients = read(
    authServerRoot,
    'auth-server/src/main/java/com/splunk/o11y/identity/oauth/OAuthClientRegistry.java'
);
const authMetadata = read(
    authServerRoot,
    'identity-common/src/main/java/sf/oauth/OAuthAuthorizationServerMetadata.java'
);
const authPublicContract = read(
    authServerRoot,
    'identity-common/src/main/java/sf/oauth/OAuthPublicContract.java'
);
const authMetadataResource = read(
    authServerRoot,
    'auth-server/src/main/java/com/splunk/o11y/identity/oauth/OAuthAuthorizationServerMetadataResource.java'
);
const indexPageModule = read(
    authServerRoot,
    'signalboost-rest-server/src/main/java/sf/sb/rootcontext/IndexPageModule.java'
);
const publicMetadataServlet = read(
    authServerRoot,
    'signalboost-rest-server/src/main/java/sf/sb/rootcontext/AppAssociationServlet.java'
);

for (const clientId of [
    'obstudio-vscode',
    'obstudio-cursor',
    'obstudio-cli',
    'splunk-mcp-gateway-local',
]) {
    requireText(signalViewServer, clientId, 'SignalView server registry');
    requireText(authClients, clientId, 'authorization-server client registry');
}
for (const clientId of ['obstudio-vscode', 'splunk-mcp-gateway-local']) {
    assert.ok(
        !signalViewParams.includes(clientId),
        `SignalView browser parser must not duplicate authorization policy for ${clientId}`
    );
}

for (const endpoint of [
    '/v2/oauth/authorization-context',
    '/v2/oauth/authorization-decisions',
    '/v2/oauth/token',
    '/v2/oauth/revoke',
]) {
    requireText(signalViewServer, endpoint, 'SignalView server');
}
requireText(signalViewPage, "'/v2/oauth/authorization-context'", 'SignalView UI');
requireText(signalViewPage, "'/v2/oauth/authorization-decisions'", 'SignalView UI');
requireText(authResource, '@Path("/v2/oauth")', 'authorization server');
for (const endpoint of [
    '@Path("/authorization-context")',
    '@Path("/authorization-decisions")',
    '@Path("/token")',
    '@Path("/revoke")',
]) {
    requireText(authResource, endpoint, 'authorization server');
}

for (const pathValue of [
    '/.well-known/oauth-authorization-server',
    'authorization_endpoint',
    'token_endpoint',
    'revocation_endpoint',
]) {
    requireText(oauthClient, pathValue, 'Obstudio OAuth client');
}
requireText(indexPageModule, 'serve("/", "/oauth/authorize")', 'SignalView production routing');
requireText(
    publicMetadataServlet,
    '"/oauth-authorization-server"',
    'SignalView public metadata routing'
);
requireText(
    authMetadataResource,
    '@Path("/.well-known/oauth-authorization-server")',
    'authorization-server metadata'
);
for (const endpoint of ['/oauth/authorize', '/v2/oauth/token', '/v2/oauth/revoke']) {
    requireText(authPublicContract, endpoint, 'OAuth public contract');
}
requireText(authMetadata, 'OAuthPublicContract', 'authorization-server metadata');
requireText(publicMetadataServlet, 'OAuthAuthorizationServerMetadata', 'SignalView public metadata');

for (const field of [
    'client_id',
    'code_challenge',
    'code_challenge_method',
    'redirect_uri',
    'response_type',
    'scope',
    'state',
]) {
    requireText(oauthClient, `"${field}"`, 'Obstudio authorization request');
}
for (const field of ['requestedScope', 'codeChallenge', 'redirectUri', 'responseType']) {
    requireText(signalViewPage, field, 'SignalView authorization request');
    requireText(authResource, field, 'authorization-server validation');
}
for (const field of ['splunk_issuer']) {
    requireText(oauthClient, field, 'Obstudio token response');
    requireText(signalViewServer, field, 'SignalView token response');
}
for (const source of [oauthClient, signalViewPage]) {
    requireText(source, 'iss', 'authorization response issuer validation');
}
requireText(oauthClient, '"token_type_hint": {"access_token"}', 'Obstudio revocation request');
requireText(authResource, '@FormParam("token") String token', 'authorization-server revocation');
requireText(authResource, '@FormParam("token_type_hint") String tokenTypeHint', 'authorization-server revocation');
requireText(authResource, 'authorization.getIssuer()', 'authorization-server token response');
requireText(authResource, 'IdUtil.id2Str(namedToken.getId())', 'authorization-server token response');
requireText(authResource, 'namedToken.getName()', 'authorization-server token response');

console.log('O11y OAuth cross-repository contract is aligned.');
