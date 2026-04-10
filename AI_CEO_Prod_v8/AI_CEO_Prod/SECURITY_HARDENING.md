# Security Hardening Notes

Implemented in code:
- HTTP-only session cookies
- encrypted secret storage at rest
- admin-only settings and approvals
- basic RBAC with admin vs authenticated user
- Docker-isolated code executor path
- rate limiting middleware
- audit logging middleware and task action logging
- browser step validation policy
- Python code pattern blocking for dangerous generated code
- task approvals for side-effecting tasks

Still required in deployment:
- HTTPS termination and secure cookies in production
- host firewall and fail2ban / equivalent
- secret rotation policy
- Docker daemon hardening
- database backups and encrypted disk
- per-environment allowed origins
- external credential provisioning and least-privilege service accounts
