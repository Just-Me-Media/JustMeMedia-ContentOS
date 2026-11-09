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
