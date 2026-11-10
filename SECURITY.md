# Security and approval rules

- Never commit `.env`, API keys, passwords, OAuth tokens, cookies, private keys or account recovery codes.
- Use OS credential storage or environment variables.
- Keep sensitive customer or personal information out of prompts unless necessary and explicitly authorized.
- Do not give an AI provider unrestricted filesystem, shell, browser, publishing or account access.
- Publishing, scheduling, messaging, replying, spending and account changes require explicit user approval for the specific action.
- Record approval against the exact content version and action.
- Re-approval is required after material changes.
- Use least-privilege platform permissions.
- Review dependencies and update them deliberately.
- **CSRF prevention:** Require `Content-Type: application/json` for all POST requests; reject cross-site form posts with 415.
- **DNS-rebinding protection:** The `Host` header must be a loopback name (`127.0.0.1`, `localhost`, `::1`); any other hostname is rejected with 403.
- **Origin guard:** State-changing requests with an `Origin` header not matching `http://127.0.0.1:<port>` or `http://localhost:<port>` are rejected with 403.
- **Request size limit:** Maximum body size is 2MB; oversized requests are rejected with 413.
- **Error resilience:** The API never crashes on malformed payloads; all errors return structured JSON `{"error": "..."}` with an appropriate HTTP status code. Stack traces are suppressed from clients.
- **Content-Security-Policy:** All HTML responses include `default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` to reduce XSS and data exfiltration risk.
