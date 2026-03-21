# Observer

Workspace with separate Node.js server and React client packages.

## Packages

- `server/` contains the Express app and production server build
- `client/` contains the React app and frontend asset build

## Workspace Scripts

- `npm run dev` runs the client asset watcher and the server together
- `npm run build` builds the client and server through the server package
- `npm run start` starts the compiled server package
- `npm run typecheck` validates both packages

## App

The server serves the React single-page app and exposes `GET /api` for sample JSON.
