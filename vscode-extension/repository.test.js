"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { normalizeGitHubRepository } = require("./repository");

test("normalizes HTTPS GitHub remotes and removes credentials and .git", () => {
  assert.equal(
    normalizeGitHubRepository("https://token@example@github.com/Owner/Repo.git"),
    "owner/repo"
  );
});

test("normalizes SCP-like and ssh URL GitHub remotes", () => {
  assert.equal(normalizeGitHubRepository("git@github.com:Owner/Repo.git"), "owner/repo");
  assert.equal(normalizeGitHubRepository("ssh://git@github.com/Owner/Repo.git"), "owner/repo");
});

test("returns null for missing, non-GitHub, or malformed remotes", () => {
  assert.equal(normalizeGitHubRepository(null), null);
  assert.equal(normalizeGitHubRepository("https://gitlab.com/Owner/Repo.git"), null);
  assert.equal(normalizeGitHubRepository("C:\\work\\repo"), null);
  assert.equal(normalizeGitHubRepository("https://github.com/Owner"), null);
});
