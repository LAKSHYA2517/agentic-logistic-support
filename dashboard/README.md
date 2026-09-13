# Sauda Logistics Dashboard

React and Vite operations dashboard backed by the FastAPI read-only endpoints:

- `GET /api/shipments`
- `GET /api/drivers`

Start FastAPI from the repository root, then start the dashboard:

```bash
uvicorn app.main:app --reload
cd dashboard
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` requests to FastAPI on port 8000.

Quality checks:

```bash
npm run lint
npm run build
```
