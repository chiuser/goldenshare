export interface ApiErrorPayload {
  code?: string;
  message?: string;
  request_id?: string;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  requestId?: string;

  constructor(status: number, payload?: ApiErrorPayload) {
    super(payload?.message || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = payload?.code;
    this.requestId = payload?.request_id;
  }
}
