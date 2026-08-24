# SIS client registration with CIMD

The VS Code extension can set up a public SIS OAuth client through a Client ID
Metadata Document (CIMD). Selecting **Set up OAuth client with CIMD** validates
the configured metadata and SIS discovery documents, opens SIS authorization in
the browser, exchanges the authorization code with PKCE, and stores the SIS
session in VS Code SecretStorage.

There is no separate dynamic-registration request or client secret. SIS fetches
the metadata document and creates or refreshes its shadow client as part of the
authorization request.

## Configuration

Configure the extension at machine scope:

```json
{
  "observability-studio.sisCimdOAuthIssuer": "http://127.0.0.1:9090/test-tenant/sis/v1/rg/cimd-demo",
  "observability-studio.sisCimdOAuthClientId": "https://localhost:9192/oauth/client-metadata.json",
  "observability-studio.sisCimdOAuthRedirectUri": "http://127.0.0.1:33418/callback",
  "observability-studio.sisCimdOAuthScope": "openid offline_access",
  "observability-studio.sisCimdOAuthDevelopmentCaBundlePath": "/absolute/path/to/ca.pem"
}
```

The client ID is the exact HTTPS URL of the metadata document. The redirect URI
is fixed so the extension can bind a loopback callback safely. Production SIS
issuers must use HTTPS; loopback HTTP is accepted only for local development.

The optional development CA bundle is accepted only when both the issuer and
metadata document use loopback hosts. It augments Node.js standard roots and
does not disable certificate verification.

The command **Splunk Observability Studio: Set Up SIS Sign-In with CIMD** starts
the same flow as the Cloud-panel button. **Clear Local SIS CIMD Session** removes
only the local SIS session.

## Client metadata

The configured URL must serve a document like this over HTTPS:

```json
{
  "client_id": "https://localhost:9192/oauth/client-metadata.json",
  "client_name": "Obstudio (CIMD)",
  "redirect_uris": [
    "http://127.0.0.1:33418/callback"
  ],
  "grant_types": [
    "authorization_code",
    "refresh_token"
  ],
  "response_types": [
    "code"
  ],
  "scope": "openid offline_access",
  "token_endpoint_auth_method": "none"
}
```

The SIS discovery document must advertise CIMD, public clients, authorization
code, the requested scopes, and PKCE `S256`. It must not advertise a dynamic
client `registration_endpoint`.

## Credential boundary

A successful setup means only that the local CIMD SIS session is ready. It does
not mean Splunk Observability Cloud is connected. The SIS access token is never
sent through the webview bridge or written into the Observer exporter.

This change does not provide the backend exchange that creates a Splunk
Observability Cloud API/INGEST named key. Until such a backend is available,
Cloud export remains **Not connected** and can still be configured through the
existing access-token form.

## Source material

- [Obstudio Client Registration CIMD Approach](https://splunk.atlassian.net/wiki/spaces/~bdrake/pages/1080354799970/Obstudio+Client+Registration+CIMD+Approach)
- [Draft CIMD Implementation Plan for Obstudio Registration](https://splunk.atlassian.net/wiki/spaces/~bdrake/pages/1080386945280/Draft+CIMD+Implementation+Plan+for+Obstudio+Registration)
- [Test Plan Walkthrough for CIMD Update for SIS](https://splunk.atlassian.net/wiki/spaces/~bdrake/pages/1080405393637/Test+Plan+Walkthrough+for+CIMD+Update+for+SIS)
- [sis-core merge request 343](https://cd.splunkdev.com/libraries/sis-core/-/merge_requests/343)
