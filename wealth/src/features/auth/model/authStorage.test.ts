import { beforeEach, describe, expect, it } from "vitest";
import { clearAuthSession, readAuthSession, saveAuthSession } from "./authStorage";
import type { TokenResponse } from "../api/authTypes";

const payload: TokenResponse = { token: "access", refresh_token: "refresh", access_token_expires_at: "expires",
  username: "demo", display_name: "Demo", is_admin: false };
describe("authStorage original contract — U07", () => {
  beforeEach(() => localStorage.clear());
  it("maps only the five existing keys and clears only those keys", () => {
    const saved = saveAuthSession(payload);
    expect({ ...localStorage }).toEqual({ "wealth.auth.access-token": "access", "wealth.auth.refresh-token": "refresh",
      "wealth.auth.expires-at": "expires", "wealth.auth.username": "demo", "wealth.auth.display-name": "Demo" });
    expect(saved).toEqual({ accessToken: "access", refreshToken: "refresh", expiresAt: "expires", username: "demo", displayName: "Demo" });
    expect(readAuthSession()).toEqual(saved);
    localStorage.setItem("unrelated", "keep"); clearAuthSession();
    expect({ ...localStorage }).toEqual({ unrelated: "keep" }); expect(readAuthSession()).toBeNull();
  });
  it.each([undefined, null, ""])("does not retain stale optional data when new value is %s", (optional) => {
    saveAuthSession(payload);
    const session = saveAuthSession({ token: "new-access", username: "new-user", is_admin: true,
      refresh_token: optional, access_token_expires_at: optional, display_name: optional });
    expect(session.accessToken).toBe("new-access");
    expect({ ...localStorage }).toEqual({ "wealth.auth.access-token": "new-access", "wealth.auth.username": "new-user" });
    expect(readAuthSession()).toEqual({ accessToken: "new-access", username: "new-user", refreshToken: null, expiresAt: null, displayName: null });
  });
  it("requires an access token, not just refresh or identity", () => {
    localStorage.setItem("wealth.auth.refresh-token", "refresh"); localStorage.setItem("wealth.auth.username", "demo");
    expect(readAuthSession()).toBeNull();
  });
});
