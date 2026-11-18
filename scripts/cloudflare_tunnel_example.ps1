# Expose local stack over HTTPS for free (demo / interview).
# Prereq: winget install Cloudflare.cloudflared  (or download from cloudflare.com)
# Run AFTER .\deploy.ps1 — each command opens a quick tunnel (ephemeral URL).

Write-Host @"
Cloudflare Quick Tunnels (free, no account required for trycloudflare.com URLs)

In separate terminals:

  cloudflared tunnel --url http://localhost:8000
  cloudflared tunnel --url http://localhost:8501
  cloudflared tunnel --url http://localhost:8069

Share the https://*.trycloudflare.com links from the output.
For production, use a named Cloudflare Tunnel + custom domain (still free tier).

See docs/DEPLOY.md for Oracle Cloud Always Free (full 24/7 hosting).
"@