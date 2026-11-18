# Deploy & record — local, cloud (free), and demo tunnels

## One-command local deploy (Windows)

From the project root:

```powershell
.\deploy.ps1
```

Optional:

```powershell
.\deploy.ps1 -SkipTests          # faster, skip pytest
.\deploy.ps1 -SkipRace           # skip 15/5 flash-sale script
.\deploy.ps1 -SkipBuild          # no image rebuild
.\deploy.ps1 -CloudGuide         # print free cloud options
```

What `deploy.ps1` does:

1. Ensures Docker is running and `.env` exists  
2. `docker compose up -d --build`  
3. Waits for **odoo-init** and **seed**  
4. Runs **Odoo branding** (OpenSource logo)  
5. Runs **pytest** and the **concurrency demo** (unless skipped)

### Credentials after deploy

| System | URL | Login |
|--------|-----|--------|
| Streamlit dashboard | http://localhost:8501 | `opsadmin` / `changeme` |
| Odoo ERP | http://localhost:8069 | Database **`inventory`**, `admin` / `admin` |
| API | http://localhost:8000/docs | — |

---

## Free cloud hosting (recommended paths)

This stack needs **~6 GB RAM** (Odoo + Postgres × 2 + API). Truly free options:

### 1. Oracle Cloud “Always Free” (best for 24/7)

- Create an **Ampere A1** VM (Ubuntu 22.04/24.04), **4 OCPU / 24 GB** eligible on Always Free.
- In the **VCN security list**, allow inbound TCP **22, 8000, 8501, 8069** (or only **22** if you use Cloudflare Tunnel below).

On the VM:

```bash
sudo apt update && sudo apt install -y git
git clone <YOUR_REPO_URL> inventory-middleware
cd inventory-middleware
bash scripts/deploy_linux.sh
```

Replace default passwords in `.env` before sharing the VM publicly.

### 2. Cloudflare Quick Tunnel (free HTTPS, no firewall holes)

Keep the stack on your PC or on a small VM; install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).

```powershell
.\scripts\cloudflare_tunnel_example.ps1
```

Example:

```text
cloudflared tunnel --url http://localhost:8000
cloudflared tunnel --url http://localhost:8501
cloudflared tunnel --url http://localhost:8069
```

You get temporary `https://*.trycloudflare.com` URLs—good for **recorded demos** and interviews.  
Named tunnels + your domain are still free on Cloudflare’s zero-trust tier for serious use.

### 3. What is **not** a good free fit

| Platform | Why |
|----------|-----|
| Render / Railway free credits | Odoo + dual Postgres exceeds free limits quickly |
| Vercel / Netlify | No long-running Odoo/Postgres |
| GitHub Codespaces | Too small for Odoo 17 init |

---

## Record a 2-minute demo video

1. Run `.\deploy.ps1`  
2. Reset race stock if needed:  
   `docker compose exec inventory-db psql -U inventory -d inventory -c "UPDATE warehouse_stock SET available_qty=15 WHERE warehouse_code='WH-BLR-01' AND sku='SKU-LAPTOP-PRO14'"`  
3. **OBS** or **Win+G** screen record:
   - Architecture (`README` diagram)
   - `simulate_concurrent_orders.py` → 15 / 5  
   - Dashboard `http://localhost:8501`  
   - Odoo draft PO + `POST /api/v1/procurement/evaluate`

---

## Version control (“record” what you shipped)

```powershell
git add .
git commit -m "Deployable inventory middleware stack"
git remote add origin <YOUR_GIT_URL>
git push -u origin main
```

Clone on any machine or Oracle VM and run `deploy.ps1` / `deploy_linux.sh` again.