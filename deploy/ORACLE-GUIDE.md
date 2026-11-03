# QuickSave — Oracle Cloud Always Free VPS (Step-by-Step)

Goal: ekta VPS ja **sarajibon free, ghumay na, 24/7 chole**. Server cholbe
Docker e (restart: unless-stopped — reboot hole nije chalu hoy).
Frontend age thekei live: https://quicksave.pages.dev — ses e sudhu
VPS er backend address ta okhane "Backend server" box e bosate hobe.

Ja lagbe: ekta card (verification er jonno, tk katbe na — chhoto hold
koyek din por ferot), ekta email.

---

## Step 1 — Account kholo
1. https://www.oracle.com/cloud/free/ → **Start for free**
2. Name, email, country (Bangladesh) → email verify koro.
3. ⚠️ **Home Region** mon diye select koro — **eta pore bodlano jay na.**
   Bangladesh er kachakachi + free capacity pawa jay emon:
   **India (Hyderabad)** ba **India (Mumbai)**, na pele **Singapore**.
4. Address + mobile verify (OTP ashbe).
5. Card verification: card details dao — Oracle ~1 USD er moto hold kore
   check kore, ta ferot chole jay. **Always Free te tk katbe na** —
   kintu nijer theke "Pay As You Go" te upgrade na kora porjonto charge nai.
6. Account ready hote 15–30 minute lagte pare (email ashbe)।

## Step 2 — VPS (Instance) banao
1. Oracle Console → menu → **Compute → Instances → Create instance**
2. Name: `quicksave`
3. Image: **Canonical Ubuntu 24.04** (ba 22.04) select koro.
4. Shape: **Ampere (ARM)** → `VM.Standard.A1.Flex` — gaye
   **"Always Free eligible"** lekha thakbe। OCPU **2**, Memory **12 GB**
   rakho (free limit: total 4 OCPU / 24 GB)।
5. Networking: default VCN auto-toiri hote dao, **Public IPv4 address**
   assign on thakbe।
6. **SSH keys:** "Generate a key pair for me" select kore **private key
   obosshoi download kore rakho** — eta pore ar pawa jay na। Harale
   instance e dhoka jabe na।
7. **Create** — 1–2 minute provisioning, tarpor **Public IP** ta note koro।

> "Out of host capacity" error ele: kichukhon por abar try, ba onno
> Availability Domain select kore Create koro — free ARM jonopriyo bole
> majhe majhe full thake।

## Step 3 — QuickSave install (ek command er kaj)
PC er terminal (Windows: PowerShell) theke SSH kore dhoko — key file
jekhane rekhecho:
```
ssh -i <private-key-file> ubuntu@<PUBLIC-IP>
```
Tarpor VPS er vitore:
```
curl -fsSL https://raw.githubusercontent.com/playscapecentral-svg/quicksave/main/deploy/setup-vps.sh -o setup-vps.sh
sh setup-vps.sh
```
Script nijei Docker install, GitHub theke code clone, build ar start
kore dibe। Ses e "QuickSave on this VPS: HTTP 200" dekhlei backend ready।

## Step 4 — Duniya theke access (2 option)
**Option A (shohoj, direct IP):**
1. Console → instance → **Subnet → Security Lists → Ingress Rules**:
   Source `0.0.0.0/0`, TCP port **5000** add koro।
2. VPS er Ubuntu firewall eo port kholo (Oracle image e default block thake):
   ```
   sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 5000 -j ACCEPT
   sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save
   ```
3. Backend address: `http://<PUBLIC-IP>:5000`

**Option B (valo, nijer domain + HTTPS — Cloudflare Tunnel):**
Age Cloudflare guide onujayi tunnel banao (cloudflare/README-CLOUDFLARE.md),
kintu eibar tunnel ta VPS theke chalao — PC lagbe na, VPS 24/7 on।
Backend address: `https://download.tomardomain.com`

## Step 5 — Pages site er sathe jure dao
1. https://quicksave.pages.dev kholo → **Backend server** section।
2. Backend URL box e Step 4 er address bosao → **Save backend**।
3. Upor e ekta video link paste kore **Download** → format list ashle
   **puro system live**।

## Update kivabe hobe
- Frontend: Maya GitHub e push korlei Pages auto-update (cholche)।
- Backend: VPS e `cd quicksave && sh deploy/update.sh` — latest code
  tene rebuild + restart korbe। Chaile cron diye daily auto-o kora jay:
  ```
  crontab -e
  0 4 * * * cd ~/quicksave && sh deploy/update.sh >> ~/quicksave-update.log 2>&1
  ```

## Mone rakhar moto
- **Idle reclaim:** Oracle onek din ekdom idle (CPU pray 0%) thaka free
  instance bondho kore dite pare bole policy te ache — normal use e
  thakle somossa hoy na।
- Card theke tk katle seta Always Free na, Pay-As-You-Go — console er
  billing page majhe majhe check koro, $0 thakar kotha।
- SSH key ta backup kore rakho (Google Drive/pendrive)।
