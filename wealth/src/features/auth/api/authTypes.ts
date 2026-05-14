export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  token: string;
  refresh_token?: string | null;
  access_token_expires_at?: string | null;
  username: string;
  is_admin: boolean;
  display_name?: string | null;
}

export interface CurrentUserResponse {
  id: number;
  username: string;
  display_name?: string | null;
  email?: string | null;
  account_state: string;
  is_admin: boolean;
  is_active: boolean;
  roles: string[];
  permissions: string[];
}

export interface RefreshTokenRequest {
  refresh_token: string;
}

export interface LogoutRequest {
  refresh_token?: string | null;
}

export interface AuthApiErrorPayload {
  code?: string;
  message?: string;
}

