import { createApp } from './app.js';

const PORT = process.env.PORT ? parseInt(process.env.PORT, 10) : 5001;

const app = createApp();
app.listen(PORT, () => {
  console.log(`Altego backend (TypeScript) listening on http://127.0.0.1:${PORT}`);
});
