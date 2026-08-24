import * as assert from 'node:assert/strict';
import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as http from 'node:http';
import * as https from 'node:https';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import test from 'node:test';
import {
	authorizeWithSISCIMD,
	parseSISCIMDOAuthSession,
	requestSISCIMD,
	sisCIMDOAuthRedirectUri,
	sisCIMDOAuthSessionMatchesConfiguration,
	type SISCIMDOAuthConfiguration,
	validateClientID,
} from '../sis-cimd-oauth';

const testRootCertificate = `-----BEGIN CERTIFICATE-----
MIIDNjCCAh6gAwIBAgIUC4+RRdkpNWDQsCaddA5XuJNKWtEwDQYJKoZIhvcNAQEL
BQAwITEfMB0GA1UEAwwWU0lTIExvY2FsIERlbW8gUm9vdCBDQTAeFw0yNjA4MjAw
NDM4MjlaFw0zNjA4MTcwNDM4MjlaMCExHzAdBgNVBAMMFlNJUyBMb2NhbCBEZW1v
IFJvb3QgQ0EwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCpnPV5VdYv
5Mmj61Ce//S7HZNQNwYi4ZE9CGbByI0spx8/cmakXJQipKhTZlcckkCutGfT2tPc
TMPVzR2AEOtpzNBerJxahOA3x88TGNZni3foyGVdilhbBVlH8JM2SCegbEf3xn0U
zPWZ1eUVKOIkqon//7p8TbT40hIqLl2KESfjFFAGUEprl3OAf5C59Z5kSAEiVrYc
LYWtkvmBhj26MSS1XOamyg9xtT5yePvfhzsNsMDcSeuOVgjp9sbTGcBayRywdxoo
YO+/xfHuUXrZOqC+ABq9NXE30bdwC5vMNAVodtVD4Izt0rZYaTlSSBoMcl2ZrNd/
FqAXwMuz1C0ZAgMBAAGjZjBkMB8GA1UdIwQYMBaAFHOkQ3lQyf9YMldoEjFO8YiF
n5DsMBIGA1UdEwEB/wQIMAYBAf8CAQAwDgYDVR0PAQH/BAQDAgEGMB0GA1UdDgQW
BBRzpEN5UMn/WDJXaBIxTvGIhZ+Q7DANBgkqhkiG9w0BAQsFAAOCAQEAf8I00E1N
rBsyg4xLt4FSaRAO291THbDO+FZiJWY3aJjYr/sFhV05zIJceykt/wPHklKWK1Yu
Tham3hSSR4N37baLtH3XA5Cvu3sPopTB4puc8NjImIZ9Gk7GdXoLs4Mf+7Rpvvqp
HQ9znHZlmW3O3jHkKYZ98ySGRQbUUfSeYheZlklW+fPxulqdQ0Z3EG7cC11J4XBv
CAsYaoIrIHkGJuQMChH9RNVHoY/TatB+1pVSunuJjgtaEQ2+ME1RHxHBnklyiLba
cFA7bTU9Vdo38v3xpoWfygmSQhHMEXxurfeNULqKbgwzNUGp+/JiT+eirLsTfZCp
mDbaZO5mnnOEQw==
-----END CERTIFICATE-----`;

const testCertificate = `-----BEGIN CERTIFICATE-----
MIIDTTCCAjWgAwIBAgILU0lTQ0lNRFRFU1QwDQYJKoZIhvcNAQELBQAwITEfMB0G
A1UEAwwWU0lTIExvY2FsIERlbW8gUm9vdCBDQTAeFw0yNjA4MjAwNDQ5MzFaFw0z
NjA4MTcwNDQ5MzFaMBQxEjAQBgNVBAMMCWxvY2FsaG9zdDCCASIwDQYJKoZIhvcN
AQEBBQADggEPADCCAQoCggEBAK+V7npg3dcO+wrgiMkTUO3udKYwGPHgwpCPWNXI
nSY3ADyvqBswi2eoYhS9cHuANfWl0PK0KNDMQ1+hhPVlq7Zr9671JkHo0B16chbB
xHC3L907FC+v2gYLx3k2qZOsi0iy+gg8fS0gWNj/UoOgyC6kd/fUi2Alk3KjJ5yR
3rg5uYlCkuc/Inbr9Oc94YoVntwW5egeFl4zOBdTeD2aOWhAvtNQ5QzCClgl0WN+
z79kZw5XumK7E299IYlxBRcT3MINbfAadV0ySy63G8MmkDQLxTdz9ZkdvtLuLQWY
7ju1Q4KUFJnz29/0HHllFtmkjLlnGvumO86+79sZIBNpDekCAwEAAaOBkjCBjzAM
BgNVHRMBAf8EAjAAMA4GA1UdDwEB/wQEAwIFoDATBgNVHSUEDDAKBggrBgEFBQcD
ATAaBgNVHREEEzARgglsb2NhbGhvc3SHBH8AAAEwHQYDVR0OBBYEFNZR91RWINPj
aKZsNfUwKpxsVwfYMB8GA1UdIwQYMBaAFHOkQ3lQyf9YMldoEjFO8YiFn5DsMA0G
CSqGSIb3DQEBCwUAA4IBAQAy4zy7yGsQwixCOE7KfagMdiKIMCKB1fySWSM97TGb
vGeWG+F9tEmzKrN/5ny8m4wGZQA0EsF7Ew5fnI9QIhbbTRReDEb/gjlQFWcJLWtA
bykLe6MaS/mSoVtGcvQNSBc4bPcZe/DOWqktcdKjqnCepFhqsV2AMlpCUwudA4S/
ykw4KZ6cIi7grF0DbsAPyrse29bQdBkFVsPhCWspuRlJFC84qWU7rhqNzeo1KMew
4bax5Zg0IQhxZmkb2bsfhkm1lPyMJngbiJUf7WnGGomp+THX+GDkC115DP2WL+6M
XqZJ74gTK5oZPMTzalwAS5ZB9vn6VElSK6q9AkpD5unP
-----END CERTIFICATE-----`;

const testPrivateKey = `-----BEGIN PRIVATE KEY-----
MIIEuwIBADANBgkqhkiG9w0BAQEFAASCBKUwggShAgEAAoIBAQCvle56YN3XDvsK
4IjJE1Dt7nSmMBjx4MKQj1jVyJ0mNwA8r6gbMItnqGIUvXB7gDX1pdDytCjQzENf
oYT1Zau2a/eu9SZB6NAdenIWwcRwty/dOxQvr9oGC8d5NqmTrItIsvoIPH0tIFjY
/1KDoMgupHf31ItgJZNyoyeckd64ObmJQpLnPyJ26/TnPeGKFZ7cFuXoHhZeMzgX
U3g9mjloQL7TUOUMwgpYJdFjfs+/ZGcOV7piuxNvfSGJcQUXE9zCDW3wGnVdMksu
txvDJpA0C8U3c/WZHb7S7i0FmO47tUOClBSZ89vf9Bx5ZRbZpIy5Zxr7pjvOvu/b
GSATaQ3pAgMBAAECgf8qaOGxArSSZ+E66gDKkF/RGEdp3Il/N/Ub9YOqH0qAcHMe
NU86l1Rp38HQ60YVOQ0kyBLajFP6GrGAklgK7a5hNrLHD29Y0WLIZqAn3vq+PtYm
GUmcOwfuGJTq3MkYt2mXpaMUBN2MiMOXphPIDI2itmxDmpK6JllMLHGPilbBKB6v
yBqcWM1jV3Uwye3acLJnEvPUfzfboI4t93h96w+/suJFFIh6ziHdH2Yd9nkk7CHd
x5rAvKtKCSChYFYk1hW/MCiMm+USt67A8LWZpeCrSiSJagFV5aIkpMfOcuCQ5PoC
VgUhNpE6HY1+T1vXs/MzkmwlT849WeRXSZv+BosCgYEA5zl4es7if1OnClvacoBd
u6OMeIsYQfoZ+VfxAwBHXYUmGd8XQnrxWiJqRoSjs+AdPK1dHHjrcIQh0B5zA/bG
jjKYFppTeAxNVo1B1RcZwJGSJZnW8P4T5L4A+thFPwBbWss2USYc+wvHfALHUNya
I3BWuZllS7WNMOAxGGFAqB8CgYEAwmZHKns9QY+ylChiP4cndtjiqRpMs97fpEqt
vSyIdcL5qeoGAjw7LckIbZZJI7WeWBr16E0kJIk3F3VTtHMUd54yzQl1G50FtUR8
VE4bZL90MT125IVcyKo0lb9ag7L7MvLLW2Z0FCN1/ds9F3hM0pC8X8rbtIsW+ug4
+Av+KPcCgYEAxpprbHh0vU65xED/EahGWlvw1L0MWecbFjs97Qj5Q0+RWVlwXg7B
bVzwEZ/uCBswoaR6vHD0MRGdBWiR+86j3xF/5rIpjYxrhTMRX5lW6jte32MS5q4l
oiy9JLhMSf/hd8vh3LOy4sLMVi0Ay+ifkF72brZd9jh7jIaURM+LvJsCgYBara7A
iB/4tvjL11KM45RrAZwo2RWySWH0lskYFu/ITpx6v6jx3fqUztNZmuKe/5bO7jSK
mYEkccT68kWLRKrlaSu1LJYtvT7uYPXFtXFdu1iNp2gQDI1NJOfGei3UhOZby5lE
FzRKOIhPU7bZfcoH5m+YF14Ih2C+xRfdzGpP3QKBgDIogEhBrxMEnGICsMFHWcr0
YyFUDhhZFbR1m9Dn1SosLA7+IFPy3RE5yyNJSMn7ctm1gADDYLzbUS+deNzEXTe+
4Wgbz3X9kM9RSt3p7SXwnnMXkPDTjT1J4j1CgcBVhvS97XJV3Ad3MX81BKsPLg/w
ERPzCwpu2EO6+AemqgyD
-----END PRIVATE KEY-----`;

type MockSIS = {
	baseUrl: string;
	close(): Promise<void>;
	configuration: SISCIMDOAuthConfiguration;
	discovery: Record<string, unknown>;
	metadata: Record<string, unknown>;
	setTokenResponseDelay(delayMs: number): void;
	tokenRequestBodies: string[];
	tokenRequestHeaders: http.IncomingHttpHeaders[];
	tokenRequestStarted: Promise<void>;
	tokenResponse: Record<string, unknown>;
};

const originalCA = https.globalAgent.options.ca;
https.globalAgent.options.ca = testRootCertificate;
test.after(() => {
	https.globalAgent.options.ca = originalCA;
});

test('validateClientID accepts only exact HTTPS URLs with a non-root path', () => {
	const prefix = 'https://localhost/';
	const maxLengthClientId = `${prefix}${'a'.repeat(512 - prefix.length)}`;
	assert.equal(validateClientID(maxLengthClientId), maxLengthClientId);
	assert.equal(
		validateClientID('https://localhost:9192/oauth/client-metadata.json'),
		'https://localhost:9192/oauth/client-metadata.json',
	);
	for (const invalid of [
		'',
		' https://localhost/client.json',
		'http://localhost/client.json',
		'https://localhost',
		'https://localhost/',
		'https://user@localhost/client.json',
		'https://localhost/client.json?version=1',
		'https://localhost/client.json?',
		'https://localhost/client.json#fragment',
		'https://localhost/client.json#',
		'HTTPS://localhost/client.json',
	]) {
		assert.throws(() => validateClientID(invalid), /SIS CIMD client ID/u, invalid);
	}
	assert.throws(() => validateClientID(`${maxLengthClientId}a`), /SIS CIMD client ID/u);
});

test('metadata may omit public auth method and declared fields are validated', async () => {
	const mock = await startMockSIS();
	try {
		await completeAuthorization(mock);
		mock.metadata.client_id = `${mock.configuration.clientId}-different`;
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => true),
			/exactly match/u,
		);
		mock.metadata.client_id = mock.configuration.clientId;
		mock.metadata.token_endpoint_auth_method = 'client_secret_basic';
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => true),
			/token_endpoint_auth_method/u,
		);
		delete mock.metadata.token_endpoint_auth_method;
		mock.metadata.response_types = ['token'];
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => true),
			/code response type/u,
		);
		mock.metadata.response_types = ['code'];
		delete mock.metadata.scope;
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => true),
			/metadata scope must be a string/u,
		);
	} finally {
		await mock.close();
	}
});

test('discovery must advertise CIMD, public clients, authorization code, and S256 without registration', async () => {
	const mock = await startMockSIS();
	try {
		mock.discovery.registration_endpoint = `${mock.baseUrl}/register`;
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => true),
			/dynamic client registration/u,
		);
		delete mock.discovery.registration_endpoint;
		mock.discovery.code_challenge_methods_supported = ['plain'];
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => true),
			/PKCE method "S256"/u,
		);
	} finally {
		await mock.close();
	}
});

test('every metadata redirect URI must be HTTPS or plain loopback HTTP without userinfo', async () => {
	const mock = await startMockSIS();
	try {
		for (const invalidRedirectUri of [
			'http://example.com/callback',
			'http://[::1]:49152/callback',
			'http://localhost.evil.example/callback',
			'http://user@localhost/callback',
			'https://user@example.com/callback',
			'HTTPS://example.com/callback',
			'not-a-url',
		]) {
			mock.metadata.redirect_uris = [sisCIMDOAuthRedirectUri, invalidRedirectUri];
			await assert.rejects(
				authorizeWithSISCIMD(mock.configuration, async () => true),
				/redirect URI/u,
				invalidRedirectUri,
			);
		}
		mock.metadata.redirect_uris = [
			sisCIMDOAuthRedirectUri,
			'http://localhost:49152/callback',
			'https://example.com/callback',
		];
		await completeAuthorization(mock);
	} finally {
		await mock.close();
	}
});

test('an explicit development CA bundle is bounded and restricted to loopback configuration', async () => {
	const fixtureDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'obstudio-sis-cimd-ca-'));
	const bundlePath = path.join(fixtureDirectory, 'local-ca.pem');
	const leafCertificatePath = path.join(fixtureDirectory, 'leaf-certificate.pem');
	const oversizedBundlePath = path.join(fixtureDirectory, 'oversized-ca.pem');
	const malformedBundlePath = path.join(fixtureDirectory, 'malformed-ca.pem');
	await fs.writeFile(bundlePath, testRootCertificate);
	await fs.writeFile(leafCertificatePath, testCertificate);
	await fs.writeFile(oversizedBundlePath, Buffer.alloc(256 * 1024 + 1, 0x41));
	await fs.writeFile(malformedBundlePath, 'not a PEM certificate');

	const mock = await startMockSIS();
	const previousGlobalCA = https.globalAgent.options.ca;
	https.globalAgent.options.ca = originalCA;
	try {
		mock.configuration.developmentCaBundlePath = bundlePath;
		await completeAuthorization(mock);

		await assert.rejects(
			authorizeWithSISCIMD({
				...mock.configuration,
				clientId: 'https://clients.example.com/client-metadata.json',
			}, async () => true),
			/only when both the issuer and client ID use loopback hosts/u,
		);
		await assert.rejects(
			authorizeWithSISCIMD({
				...mock.configuration,
				developmentCaBundlePath: oversizedBundlePath,
			}, async () => true),
			/262144-byte limit/u,
		);
		await assert.rejects(
			authorizeWithSISCIMD({
				...mock.configuration,
				developmentCaBundlePath: malformedBundlePath,
			}, async () => true),
			/not valid PEM certificate data/u,
		);
		await assert.rejects(
			authorizeWithSISCIMD({
				...mock.configuration,
				developmentCaBundlePath: leafCertificatePath,
			}, async () => true),
			/must contain only CA certificates/u,
		);
		await assert.rejects(
			authorizeWithSISCIMD({
				...mock.configuration,
				developmentCaBundlePath: 'relative/local-ca.pem',
			}, async () => true),
			/path must be absolute/u,
		);
	} finally {
		https.globalAgent.options.ca = previousGlobalCA;
		await mock.close();
		await fs.rm(fixtureDirectory, { force: true, recursive: true });
	}
});

test('authorization uses PKCE S256 and exchanges exactly the five public-client fields', async () => {
	const mock = await startMockSIS();
	try {
		const { authorizationUrl, callbackResponse, session } = await completeAuthorization(mock);
		assert.equal(session.accessToken, 'sis-access-token');
		assert.equal(session.refreshToken, 'sis-refresh-token');
		assert.equal(session.idToken, 'sis-id-token');
		assert.equal(session.scope, 'openid offline_access');
		assert.equal(callbackResponse.statusCode, 200);
		const contentSecurityPolicy = callbackResponse.headers['content-security-policy'];
		assert.match(Array.isArray(contentSecurityPolicy) ? contentSecurityPolicy.join('; ') : contentSecurityPolicy ?? '', /default-src 'none'/u);
		assert.equal(callbackResponse.headers['referrer-policy'], 'no-referrer');

		assert.equal(authorizationUrl.searchParams.get('response_type'), 'code');
		assert.equal(authorizationUrl.searchParams.get('client_id'), mock.configuration.clientId);
		assert.equal(authorizationUrl.searchParams.get('redirect_uri'), sisCIMDOAuthRedirectUri);
		assert.equal(authorizationUrl.searchParams.get('scope'), 'openid offline_access');
		assert.equal(authorizationUrl.searchParams.get('code_challenge_method'), 'S256');

		assert.equal(mock.tokenRequestBodies.length, 1);
		const form = new URLSearchParams(mock.tokenRequestBodies[0]);
		assert.deepEqual(
			Array.from(form.keys()).sort(),
			['client_id', 'code', 'code_verifier', 'grant_type', 'redirect_uri'],
		);
		assert.equal(form.get('grant_type'), 'authorization_code');
		assert.equal(form.get('code'), 'test-authorization-code');
		assert.equal(form.get('client_id'), mock.configuration.clientId);
		assert.equal(form.get('redirect_uri'), sisCIMDOAuthRedirectUri);
		const expectedChallenge = crypto.createHash('sha256')
			.update(form.get('code_verifier') ?? '')
			.digest('base64url');
		assert.equal(authorizationUrl.searchParams.get('code_challenge'), expectedChallenge);
		assert.equal(mock.tokenRequestHeaders[0].authorization, undefined);
		assert.equal(mock.tokenRequestHeaders[0]['content-type'], 'application/x-www-form-urlencoded');
	} finally {
		await mock.close();
	}
});

test('a callback with the wrong state is rejected without a token request', async () => {
	const mock = await startMockSIS();
	let callbackResponse: Promise<HTTPResponse> | undefined;
	try {
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => {
				callbackResponse = getCallback({ code: 'code', state: 'wrong-state' });
				return true;
			}),
			/state did not match/u,
		);
		assert.equal((await callbackResponse)?.statusCode, 400);
		assert.equal(mock.tokenRequestBodies.length, 0);
	} finally {
		await mock.close();
	}
});

test('an OAuth callback error is surfaced without reflecting its description', async () => {
	const mock = await startMockSIS();
	let callbackResponse: Promise<HTTPResponse> | undefined;
	try {
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async (authorizationUrl) => {
				callbackResponse = getCallback({
					error: 'access_denied',
					error_description: '<script>sensitive detail</script>',
					state: authorizationUrl.searchParams.get('state') ?? '',
				});
				return true;
			}),
			/authorization failed \(access_denied\)/u,
		);
		const response = await callbackResponse;
		assert.equal(response?.statusCode, 400);
		assert.doesNotMatch(response?.body ?? '', /sensitive detail/u);
		assert.equal(mock.tokenRequestBodies.length, 0);
	} finally {
		await mock.close();
	}
});

test('authorization fails cleanly when the fixed callback port is occupied', async () => {
	const blocker = net.createServer();
	await listen(blocker, 33418, '127.0.0.1');
	const mock = await startMockSIS();
	let opened = false;
	try {
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => {
				opened = true;
				return true;
			}),
			/Could not start.*EADDRINUSE/u,
		);
		assert.equal(opened, false);
	} finally {
		await closeServer(blocker);
		await mock.close();
	}
});

test('cancelling authorization releases the fixed callback port', async () => {
	const mock = await startMockSIS();
	const abortController = new AbortController();
	try {
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async () => {
				abortController.abort();
				return true;
			}, abortController.signal),
			/cancelled/u,
		);
		const probe = net.createServer();
		await listen(probe, 33418, '127.0.0.1');
		await closeServer(probe);
	} finally {
		await mock.close();
	}
});

test('cancelling an in-flight token exchange cannot return a session', async () => {
	const mock = await startMockSIS();
	const abortController = new AbortController();
	let callbackResponse: Promise<HTTPResponse> | undefined;
	mock.setTokenResponseDelay(5_000);
	try {
		const authorization = authorizeWithSISCIMD(mock.configuration, async (authorizationUrl) => {
			callbackResponse = getCallback({
				code: 'code',
				state: authorizationUrl.searchParams.get('state') ?? '',
			});
			return true;
		}, abortController.signal);
		await mock.tokenRequestStarted;
		abortController.abort();
		await assert.rejects(authorization, /cancelled/u);
		assert.equal((await callbackResponse)?.statusCode, 502);
		assert.equal(mock.tokenRequestBodies.length, 1);
	} finally {
		await mock.close();
	}
});

test('HTTP requests enforce an overall timeout and the 64 KiB body cap', async () => {
	const slowServer = http.createServer((_request, response) => {
		setTimeout(() => response.end('{}'), 250);
	});
	await listen(slowServer, 0, '127.0.0.1');
	try {
		await assert.rejects(
			requestSISCIMD(serverUrl(slowServer), { timeoutMs: 25 }),
			/Timed out/u,
		);
	} finally {
		await closeServer(slowServer);
	}

	const largeServer = http.createServer((_request, response) => {
		response.end('x'.repeat(64 * 1024 + 1));
	});
	await listen(largeServer, 0, '127.0.0.1');
	try {
		await assert.rejects(requestSISCIMD(serverUrl(largeServer)), /64 KiB/u);
	} finally {
		await closeServer(largeServer);
	}
});

test('HTTP requests return redirects without following them', async () => {
	let redirectTargetHit = false;
	const server = http.createServer((request, response) => {
		if (request.url === '/target') {
			redirectTargetHit = true;
			response.end('{}');
			return;
		}
		response.statusCode = 302;
		response.setHeader('Location', '/target');
		response.end();
	});
	await listen(server, 0, '127.0.0.1');
	try {
		const response = await requestSISCIMD(serverUrl(server));
		assert.equal(response.statusCode, 302);
		assert.equal(redirectTargetHit, false);
	} finally {
		await closeServer(server);
	}
});

test('a token response that narrows requested scopes fails the flow', async () => {
	const mock = await startMockSIS();
	mock.tokenResponse.scope = 'openid';
	let callbackResponse: Promise<HTTPResponse> | undefined;
	try {
		await assert.rejects(
			authorizeWithSISCIMD(mock.configuration, async (authorizationUrl) => {
				callbackResponse = getCallback({
					code: 'code',
					state: authorizationUrl.searchParams.get('state') ?? '',
				});
				return true;
			}),
			/omitted requested scope "offline_access"/u,
		);
		assert.equal((await callbackResponse)?.statusCode, 502);
	} finally {
		await mock.close();
	}
});

test('a token response with extra scopes or no lifetime fails the flow', async () => {
	const extraScopeMock = await startMockSIS();
	extraScopeMock.tokenResponse.scope = 'openid offline_access admin';
	try {
		await assert.rejects(
			completeAuthorization(extraScopeMock),
			/unrequested scope "admin"/u,
		);
	} finally {
		await extraScopeMock.close();
	}

	const noLifetimeMock = await startMockSIS();
	delete noLifetimeMock.tokenResponse.expires_in;
	try {
		await assert.rejects(
			completeAuthorization(noLifetimeMock),
			/invalid expires_in value/u,
		);
	} finally {
		await noLifetimeMock.close();
	}
});

test('stored sessions parse defensively and match only their live configuration', () => {
	const configuration: SISCIMDOAuthConfiguration = {
		clientId: 'https://localhost:9192/oauth/client-metadata.json',
		issuer: 'https://sis.example.test/tenant/sis/v1/rg/example',
		redirectUri: sisCIMDOAuthRedirectUri,
		scope: 'openid offline_access',
	};
	const raw = JSON.stringify({
		accessToken: 'access-token',
		clientId: configuration.clientId,
		connectedAt: '2026-08-19T00:00:00.000Z',
		expiresAt: '2026-08-19T02:00:00.000Z',
		issuer: configuration.issuer,
		redirectUri: configuration.redirectUri,
		scope: 'offline_access openid',
		tokenType: 'bearer',
	});
	const session = parseSISCIMDOAuthSession(raw);
	assert.ok(session);
	assert.equal(session.tokenType, 'Bearer');
	assert.equal(
		sisCIMDOAuthSessionMatchesConfiguration(session, configuration, new Date('2026-08-19T01:00:00.000Z')),
		true,
	);
	assert.equal(
		sisCIMDOAuthSessionMatchesConfiguration(session, configuration, new Date('2026-08-19T03:00:00.000Z')),
		false,
	);
	assert.equal(
		sisCIMDOAuthSessionMatchesConfiguration(session, { ...configuration, clientId: 'https://localhost/other.json' }),
		false,
	);
	assert.equal(
		sisCIMDOAuthSessionMatchesConfiguration({ ...session, scope: 'openid offline_access admin' }, configuration),
		false,
	);
	assert.equal(
		sisCIMDOAuthSessionMatchesConfiguration(session, { ...configuration, scope: 'openid' }),
		false,
	);
	assert.equal(parseSISCIMDOAuthSession('{not-json'), undefined);
	assert.equal(parseSISCIMDOAuthSession({ ...session, expiresAt: undefined }), undefined);
	assert.equal(parseSISCIMDOAuthSession({ ...session, tokenType: 'Basic' }), undefined);
});

async function startMockSIS(): Promise<MockSIS> {
	const tokenRequestBodies: string[] = [];
	const tokenRequestHeaders: http.IncomingHttpHeaders[] = [];
	let tokenResponseDelayMs = 0;
	let markTokenRequestStarted: (() => void) | undefined;
	const tokenRequestStarted = new Promise<void>((resolve) => {
		markTokenRequestStarted = resolve;
	});
	const metadata: Record<string, unknown> = {};
	const discovery: Record<string, unknown> = {};
	const tokenResponse: Record<string, unknown> = {
		access_token: 'sis-access-token',
		expires_in: 3600,
		id_token: 'sis-id-token',
		refresh_token: 'sis-refresh-token',
		scope: 'openid offline_access',
		token_type: 'Bearer',
	};
	const server = https.createServer({ cert: testCertificate, key: testPrivateKey }, async (request, response) => {
		if (request.url === '/oauth/client-metadata.json') {
			writeJSON(response, metadata);
			return;
		}
		if (request.url === '/test-tenant/sis/v1/rg/cimd-demo/.well-known/openid-configuration') {
			writeJSON(response, discovery);
			return;
		}
		if (request.url === '/test-tenant/sis/v1/rg/cimd-demo/oauth2/token' && request.method === 'POST') {
			tokenRequestHeaders.push(request.headers);
			tokenRequestBodies.push(await readBody(request));
			markTokenRequestStarted?.();
			if (tokenResponseDelayMs > 0) {
				await waitForDelayOrClose(response, tokenResponseDelayMs);
				if (response.destroyed) {
					return;
				}
			}
			writeJSON(response, tokenResponse);
			return;
		}
		response.statusCode = 404;
		response.end();
	});
	await listen(server, 0, '127.0.0.1');
	const baseUrl = serverUrl(server).replace('http:', 'https:');
	const issuer = `${baseUrl}/test-tenant/sis/v1/rg/cimd-demo`;
	const clientId = `${baseUrl}/oauth/client-metadata.json`;
	Object.assign(metadata, {
		client_id: clientId,
		client_name: 'Obstudio (CIMD)',
		grant_types: ['authorization_code', 'refresh_token'],
		redirect_uris: [sisCIMDOAuthRedirectUri],
		response_types: ['code'],
		scope: 'openid offline_access',
	});
	Object.assign(discovery, {
		authorization_endpoint: `${issuer}/oauth2/authorize`,
		client_id_metadata_document_supported: true,
		code_challenge_methods_supported: ['S256', 'plain'],
		grant_types_supported: ['authorization_code', 'refresh_token'],
		issuer,
		response_types_supported: ['code'],
		scopes_supported: ['openid', 'offline_access'],
		token_endpoint: `${issuer}/oauth2/token`,
		token_endpoint_auth_methods_supported: ['private_key_jwt', 'none'],
	});
	return {
		baseUrl,
		close: () => closeServer(server),
		configuration: {
			clientId,
			issuer,
			redirectUri: sisCIMDOAuthRedirectUri,
			scope: 'openid offline_access',
		},
		discovery,
		metadata,
		setTokenResponseDelay: (delayMs) => {
			tokenResponseDelayMs = delayMs;
		},
		tokenRequestBodies,
		tokenRequestHeaders,
		tokenRequestStarted,
		tokenResponse,
	};
}

function waitForDelayOrClose(response: http.ServerResponse, delayMs: number): Promise<void> {
	return new Promise((resolve) => {
		let settled = false;
		const finish = (): void => {
			if (settled) {
				return;
			}
			settled = true;
			clearTimeout(timer);
			resolve();
		};
		const timer = setTimeout(finish, delayMs);
		response.once('close', finish);
	});
}

async function completeAuthorization(mock: MockSIS): Promise<{
	authorizationUrl: URL;
	callbackResponse: HTTPResponse;
	session: Awaited<ReturnType<typeof authorizeWithSISCIMD>>;
}> {
	let authorizationUrl: URL | undefined;
	let callbackResponse: Promise<HTTPResponse> | undefined;
	const session = await authorizeWithSISCIMD(mock.configuration, async (url) => {
		authorizationUrl = url;
		callbackResponse = getCallback({
			code: 'test-authorization-code',
			iss: mock.configuration.issuer,
			state: url.searchParams.get('state') ?? '',
		});
		return true;
	});
	assert.ok(authorizationUrl);
	assert.ok(callbackResponse);
	return { authorizationUrl, callbackResponse: await callbackResponse, session };
}

type HTTPResponse = {
	body: string;
	headers: http.IncomingHttpHeaders;
	statusCode: number;
};

function getCallback(parameters: Record<string, string>): Promise<HTTPResponse> {
	const callback = new URL(sisCIMDOAuthRedirectUri);
	for (const [key, value] of Object.entries(parameters)) {
		callback.searchParams.set(key, value);
	}
	return new Promise((resolve, reject) => {
		http.get(callback, (response) => {
			const chunks: Buffer[] = [];
			response.on('data', (chunk: Buffer) => chunks.push(chunk));
			response.on('end', () => resolve({
				body: Buffer.concat(chunks).toString('utf8'),
				headers: response.headers,
				statusCode: response.statusCode ?? 0,
			}));
		}).once('error', reject);
	});
}

function listen(server: net.Server, port: number, host: string): Promise<void> {
	return new Promise((resolve, reject) => {
		server.once('error', reject);
		server.listen(port, host, () => {
			server.off('error', reject);
			resolve();
		});
	});
}

function closeServer(server: net.Server): Promise<void> {
	return new Promise((resolve, reject) => {
		server.close((error) => error === undefined ? resolve() : reject(error));
	});
}

function serverUrl(server: net.Server): string {
	const address = server.address();
	assert.ok(address && typeof address !== 'string');
	return `http://127.0.0.1:${address.port}`;
}

function writeJSON(response: http.ServerResponse, value: Record<string, unknown>): void {
	response.setHeader('Content-Type', 'application/json');
	response.end(JSON.stringify(value));
}

function readBody(request: http.IncomingMessage): Promise<string> {
	return new Promise((resolve, reject) => {
		const chunks: Buffer[] = [];
		request.on('data', (chunk: Buffer) => chunks.push(chunk));
		request.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
		request.on('error', reject);
	});
}
