# Security policy

## Supported versions

Security fixes are made on the default branch. No earlier release series is
currently designated for security backports.

## Reporting a vulnerability

Please do not report suspected vulnerabilities in a public issue. Use GitHub's
private vulnerability reporting for this repository (the **Security** tab →
**Report a vulnerability**) when available. If that option is unavailable, use
the repository owner's private GitHub contact channel and ask for a secure
reporting route.

Include the affected version or commit, the impact, steps to reproduce, and any
suggested mitigation. Avoid including real user data, credentials, or exploit
payloads beyond what is necessary to establish the issue. Please allow time for
investigation and a coordinated fix before public disclosure.

## Security boundaries

- Never commit a real `.env` file or provider credential. Use `.env.example` as
  the documentation template and keep production secrets in the deployment
  platform's secret store.
- The ordinary test suite uses mock providers and must not require credentials
  or billable API calls.
- Do not upload confidential or third-party data to a public issue, pull
  request, or test fixture.
