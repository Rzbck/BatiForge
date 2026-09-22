# Security Policy

BatiForge is a public repository. Do not report credentials, tokens, private keys, personal data, or exploitable security details in a public Issue.

## Reporting a vulnerability

Prefer GitHub's private vulnerability reporting / Security Advisory flow when it is available for this repository.

If a secret has been committed or pushed:

1. Treat it as compromised immediately.
2. Revoke or rotate it at the provider first.
3. Do not rely on deleting the file from the latest commit; Git history may still contain it.
4. Remove the secret from history only after the credential has been invalidated.
5. Re-run secret scanning after remediation.

## Repository rules

- No credentials or private keys in Git.
- No `.env` files except documented examples without secrets.
- No downloaded LiDAR, imagery, caches, native tool bundles, COLMAP databases, or generated large meshes in Git.
- GitHub Actions must use minimal permissions.
- Third-party Actions must be pinned to immutable commit SHAs; Dependabot maintains those pins.
- Security checks are expected to pass before promotion to `main`.
