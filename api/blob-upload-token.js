// Authorizes direct browser-to-Vercel-Blob uploads for files too large for a
// normal request (Vercel Functions cap request bodies at 4.5MB; real billing
// exports routinely exceed that). This is the ONLY piece of this app written
// in JavaScript instead of Python — Vercel Blob's client-upload flow only
// ships an official SDK for JS/TS, not Python. Everything else (reading the
// uploaded file, reconciliation, storage) stays in the Python backend
// (backend/app.py), which fetches the file from the Blob URL this hands back.
//
// This app has no user-login system anywhere, so there's no real session to
// check here (see onBeforeGenerateToken below) — the only safeguard is
// restricting the upload to spreadsheet file types.
import { handleUpload } from '@vercel/blob/client';

export default async function handler(request) {
  const body = await request.json();

  try {
    const jsonResponse = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async () => ({
        allowedContentTypes: [
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', // .xlsx
          'application/vnd.ms-excel', // .xls
        ],
        addRandomSuffix: true,
      }),
      onUploadCompleted: async () => {
        // Intentionally a no-op: the browser already has the blob URL the
        // moment upload() resolves and passes it straight to the Python
        // backend itself — no need to react to this webhook separately.
        // (It also can't reach localhost during local development anyway.)
      },
    });

    return Response.json(jsonResponse);
  } catch (error) {
    return Response.json({ error: error.message }, { status: 400 });
  }
}
