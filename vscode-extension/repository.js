"use strict";

/** Return a canonical lowercase GitHub owner/repository, or null.
 *
 * Only github.com remotes are accepted. URL credentials, query strings, and
 * fragments are never included in the returned value.
 */
function normalizeGitHubRepository(remoteUrl) {
  if (!remoteUrl || typeof remoteUrl !== "string") return null;
  const value = remoteUrl.trim();
  let host;
  let pathname;

  const scpLike = value.match(/^(?:[^@\s]+@)?([^:\s/]+):(.+)$/);
  if (scpLike && !value.includes("://")) {
    host = scpLike[1];
    pathname = scpLike[2];
  } else {
    try {
      const parsed = new URL(value);
      host = parsed.hostname;
      pathname = parsed.pathname;
    } catch {
      return null;
    }
  }

  if ((host || "").toLowerCase() !== "github.com") return null;
  const parts = (pathname || "")
    .replace(/^\/+|\/+$/g, "")
    .replace(/\.git$/i, "")
    .split("/");
  if (parts.length !== 2) return null;

  const validPart = /^[A-Za-z0-9_.-]+$/;
  if (!parts.every((part) => part && validPart.test(part))) return null;
  return `${parts[0]}/${parts[1]}`.toLowerCase();
}

module.exports = { normalizeGitHubRepository };
