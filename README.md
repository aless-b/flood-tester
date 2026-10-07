# Fail2Ban HTTP Load & Threshold Tester (`flood.py`)

Standalone Python load-testing script designed to evaluate **Fail2Ban HTTP flood protection (`[http-flood]`)** and determine the exact request-rate thresholds across the three Dockerized microservices of the **Fragrance Corner** architecture:

1. **Frontend (`perfume-react-frontend`)** — `http://localhost:5173`
2. **Backend (`perfume-express-backend`)** — `http://localhost:3001`
3. **LDAP / Keycloak JWT (`keycloak`)** — `http://localhost:8081`

---

## 🎯 Specific Load Values Determined (`maxretry = 60` in `findtime = 10s`)

### 1. ✅ Load Value That DOES NOT Bring Down / Block the Service (Safe Load)
- **Maximum Sustained Rate**: **Up to `5 requests per second` (`5 req/s`)** — equivalent to **`50–59 requests in 10 seconds`**.
- **Specific Tested Parameters**:
  - `CONCURRENCY` (`--concurrency`): **`4`** to **`5`** workers
  - `REQUESTS_PER_SECOND` (`--rps`): **`4`** to **`5`** req/s
  - `DURATION` (`--duration`): **`10`** seconds
- **Result**: **100% `200 OK` responses (`0%` blocked)**, because the request volume never reaches 60 requests within any rolling 10-second window.

---

### 2. 🚫 Load Value That DOES Bring Down / Block Access (Trigger Threshold)
- **Exact Critical Activation Rate**: **Starting at `6 requests per second` (`6 req/s`)** — reaching **`60 requests within 10 seconds`**.
- **Specific Tested Parameters That Trigger the Ban**:
  1. **Minimum Ban-Triggering Load (`10 req/s`)**:
     - `CONCURRENCY` (`--concurrency`): **`10`** workers
     - `REQUESTS_PER_SECOND` (`--rps`): **`10`** req/s
     - `DURATION` (`--duration`): **`15`** seconds
     - **Behavior**: The first **`~60–64` requests** succeed (within the first ~6 seconds), and immediately afterward Fail2Ban bans the IP via `iptables-allports`, blocking the remaining **44%** of requests.
  2. **High-Volume Flood Load (`150 req/s`)**:
     - `CONCURRENCY` (`--concurrency`): **`150`** workers
     - `REQUESTS_PER_SECOND` (`--rps`): **`150`** req/s
     - `DURATION` (`--duration`): **`30`** segundos
     - **Behavior**: The 60-request limit is exceeded in **less than 1 second** (`~85` requests pass before Fail2Ban's polling cycle inserts the firewall rule), blocking **95%** of total requests (`1,782` blocked out of `1,867`).

### 📌 Quick Summary:
- **Safe Limit (Does NOT block)**: **$\le 5\text{ req/s}$** (`< 60 requests per 10s`)
- **Exact Ban Point (DOES block)**: **$\ge 6\text{ req/s}$** (`\ge 60 requests per 10s`)

---

## 🛠️ 1. Steps Followed to Modify `flood.py`

The original lab script (`attacker/flood.py`) was hardcoded to run inside an isolated Docker container and only targeted static hostnames (`victim-protected`, `victim-unprotected`) on port `80` using environment variables.

To make it work **outside the Docker images** and test any of the 3 services dynamically, the following modifications were implemented:

1. **Command-Line Arguments (`argparse`)**:
   - Added positional and named arguments for **`host`** (`--host`) and **`port`** (`--port`) so each container can be tested individually from the host machine (`localhost:5173`, `localhost:3001`, `localhost:8081`).
   - Added CLI flags **`--concurrency`**, **`--rps`** (`REQUESTS_PER_SECOND`), and **`--duration`** (`DURATION`) to adjust load parameters directly from the terminal without rebuilding containers.
2. **Dynamic URL Construction (`http://{host}:{port}/`)**:
   - Updated `request_status(opener, host, port)` to build the target URL dynamically with the specified TCP port instead of assuming port `80`.
3. **Default Multi-Service Sequential Mode**:
   - Configured `DEFAULT_TARGETS` with `(("localhost", 5173), ("localhost", 3001), ("localhost", 8081))` so running `python flood.py` without arguments sequentially tests all three containers.

---

## ⚙️ 2. Theoretical Threshold vs. Fail2Ban Configuration

Each of the 3 protected containers uses the following Fail2Ban rule in `/etc/fail2ban/jail.local`:

```ini
[http-flood]
enabled  = true
port     = http,https
filter   = http-flood
logpath  = /var/log/nginx/access.log
maxretry = 60
findtime = 10s
bantime  = 10m
banaction = iptables-allports
```

### Critical Threshold Calculation:
$$\text{Threshold Rate} = \frac{\text{maxretry}}{\text{findtime}} = \frac{60\text{ requests}}{10\text{ seconds}} = 6.0\text{ requests/second}$$

---

## 🧪 3. Step-by-Step Methodology & Experimental Results

### Step 1: Test Safe Load (`4 req/s` — Does NOT bring down / ban the service)
Run `flood.py` at **`4 requests/s`** with **`4 concurrent workers`** for **`10 seconds`** (`40 total requests < 60 maxretry`):

```powershell
python flood.py localhost 5173 --concurrency 4 --rps 4 --duration 10
python flood.py localhost 3001 --concurrency 4 --rps 4 --duration 10
python flood.py localhost 8081 --concurrency 4 --rps 4 --duration 10
```

#### Output:
```text
=== Bounded HTTP Fail2Ban test: 4 workers, up to 4 requests/s, 10s per target ===

--- Target: http://localhost:5173/ (4 workers, 4 requests/s max, 10s) ---
  [21:18:39] requests so far for localhost:5173: total=12 ok(200)=12 blocked/failed=0
  [21:18:42] requests so far for localhost:5173: total=24 ok(200)=24 blocked/failed=0
  [21:18:45] requests so far for localhost:5173: total=36 ok(200)=36 blocked/failed=0
  [21:18:46] requests so far for localhost:5173: total=39 ok(200)=39 blocked/failed=0
  RESULT for localhost:5173: total=40 ok(200)=40 blocked/failed=0
  -> 0% of responses were non-200
```

---

### Step 2: Test Threshold-Breaking Load (`10 req/s` — Triggers Fail2Ban Ban)
Increase the rate to **`10 requests/s`** with **`10 workers`** for **`15 seconds`**:

```powershell
python flood.py localhost 5173 --concurrency 10 --rps 10 --duration 15
python flood.py localhost 3001 --concurrency 10 --rps 10 --duration 15
python flood.py localhost 8081 --concurrency 10 --rps 10 --duration 15
```

#### Output:
```text
=== Bounded HTTP Fail2Ban test: 10 workers, up to 10 requests/s, 15s per target ===

--- Target: http://localhost:5173/ (10 workers, 10 requests/s max, 15s) ---
  [21:19:29] requests so far for localhost:5173: total=34 ok(200)=34 blocked/failed=0
  [21:19:32] requests so far for localhost:5173: total=65 ok(200)=64 blocked/failed=1
  [21:19:35] requests so far for localhost:5173: total=76 ok(200)=64 blocked/failed=12
  [21:19:38] requests so far for localhost:5173: total=93 ok(200)=64 blocked/failed=29
  [21:19:40] requests so far for localhost:5173: total=105 ok(200)=64 blocked/failed=41
  RESULT for localhost:5173: total=115 ok(200)=64 blocked/failed=51
  -> 44% of responses were non-200
```

---

### Step 3: Test High-Volume Flood (`150 req/s` — Immediate Ban)
Unban the IP first, then run **`150 requests/s`** with **`150 workers`** for **`30 seconds`**:

```powershell
docker exec perfume-react-frontend fail2ban-client unban --all
python flood.py localhost 5173 --concurrency 150 --rps 150 --duration 30
```

#### Output:
```text
=== Bounded HTTP Fail2Ban test: 150 workers, up to 150 requests/s, 30s per target ===

--- Target: http://localhost:5173/ (150 workers, 150 requests/s max, 30s) ---
  [21:20:56] requests so far for localhost:5173: total=615 ok(200)=85 blocked/failed=530
  [21:20:59] requests so far for localhost:5173: total=836 ok(200)=85 blocked/failed=751
  [21:21:02] requests so far for localhost:5173: total=1065 ok(200)=85 blocked/failed=980
  [21:21:05] requests so far for localhost:5173: total=1284 ok(200)=85 blocked/failed=1199
  [21:21:08] requests so far for localhost:5173: total=1513 ok(200)=85 blocked/failed=1428
  [21:21:11] requests so far for localhost:5173: total=1717 ok(200)=85 blocked/failed=1632
  RESULT for localhost:5173: total=1867 ok(200)=85 blocked/failed=1782
  -> 95% of responses were non-200
```

#### Fail2Ban Jail Verification:
```text
PS> docker exec perfume-react-frontend fail2ban-client status http-flood
Status for the jail: http-flood
|- Filter
|  |- Currently failed: 0
|  |- Total failed:     193
|  `- File list:        /var/log/nginx/access.log
`- Actions
   |- Currently banned: 1
   |- Total banned:     2
   `- Banned IP list:   172.26.0.1
```

---

## 📊 4. Summary Table of Load Thresholds

| Service | Port | Max Safe Load (No Ban) | Critical Trigger Threshold | High Flood Test (`150 req/s`) |
| :--- | :---: | :---: | :---: | :---: |
| **Frontend (`perfume-react-frontend`)** | `5173` | **$\le 5\text{ req/s}$** (`< 60 req / 10s`) | **$\ge 6\text{ req/s}$** (`60 req / 10s`) | Banned in `< 1s` (`95%` blocked) |
| **Backend (`perfume-express-backend`)** | `3001` | **$\le 5\text{ req/s}$** (`< 60 req / 10s`) | **$\ge 6\text{ req/s}$** (`60 req / 10s`) | Banned in `< 1s` (`95%` blocked) |
| **LDAP / Keycloak (`keycloak`)** | `8081` | **$\le 5\text{ req/s}$** (`< 60 req / 10s`) | **$\ge 6\text{ req/s}$** (`60 req / 10s`) | Banned in `< 1s` (`95%` blocked) |

---

## 🔓 Useful Commands to Unban IP After Testing

```powershell
docker exec perfume-react-frontend fail2ban-client unban --all
docker exec perfume-express-backend fail2ban-client unban --all
docker exec keycloak fail2ban-client unban --all
```
