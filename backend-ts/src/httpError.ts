/** Mirrors FastAPI's HTTPException: throw this from any route handler (sync
 * or async) and the error-handling middleware in app.ts turns it into a JSON
 * {"detail": "..."} response with the given status -- the exact shape the
 * frontend already expects from the Python backend. */
export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
