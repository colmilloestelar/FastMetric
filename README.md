# FastMetric

## Watch your machines without any drama

FastMetric is a tiny, self hosted monitoring tool. A small agent on each machine sends CPU, memory, disk and uptime to a simple server. The server keeps the data in one SQLite file and shows it on a web dashboard. No Kubernetes, no external database, no complex setup. One server process, one small agent script, and you are done.

It is built for startups and small teams that are just getting started. You do not need a monitoring expert or a big infrastructure. If you can run a Python file and open a browser, you can use FastMetric.

FastMetric works next to Grafana, not against it. Grafana is great for deep dashboards. FastMetric answers a simpler question: is my machine okay right now?

---

## How it works

Each machine runs a small agent. The agent connects to the server, sends a reporthola, and waits. The server never connects to the machines. That means you do not need open ports or SSH to reach your agents. This is safe and simple.

```
+--------------------+    agent reports by POST    +---------------------+
| Machine 1 (agent) |  ----------------------->  |                     |
+--------------------+                            |  FastMetric server  |
+--------------------+    agent reports by POST    |  SQLite + Web UI    |
| Machine 2 (agent) |  ----------------------->  |  port 8456          |
+--------------------+                            +---------------------+
+--------------------+                                     |
| Machine 3 (agent) |  ----------------------->            v
+--------------------+                             alerts only on change
```

The traffic flows only one way, from agent to server. Agents open the connection and the server just listens. This is ideal for machines inside a company network that have no public address, like databases, laptops and VMs.

---

## Try it now in Docker (3 minutes)

The repo includes a demo that starts everything with one command. It spins up the server plus three simulated machines: one healthy, one with a nearly full disk, one with high CPU and memory. Perfect to see the tool working before you touch your real machines.

```
docker compose up --build
```

Then open your browser at http://localhost:8456

You will see the three simulated clients with their status, CPU and memory bars. Click one to open the detail view with diagnostics, history, disks and events. Open the log and the settings to explore the alert options.

To stop the demo and clear all demo data:

```
docker compose down -v
```

---

## Use it with your real machines

Testing with docker is only the first step. To monitor real machines you run the server once and install the agent on each machine.

### Step 1. Start the server

Copy the project to a machine that is always on, like a small VM or an old laptop. Install the requirements and run:

```
pip install -r requirements.txt
python run.py
```

The server starts on port 8456 and shows the dashboard in your browser. Everything is stored in one SQLite file, so there is nothing else to configure for a quick start.

### Step 2. Get the shared token

Open the server in your browser and go to Settings. Copy the token shown there. Every agent uses the same token to report to the server. It is like a password shared between your machines.

### Step 3. Install the agent on each machine

Copy the agent file `agent/agent.py` to the target machine. It uses only the Python standard library, so there is nothing to install on the target machine. Python is enough.

Then set two environment variables. On Linux:

```
export MS_SERVER_URL=http://your-server:8456
export MS_TOKEN=your-token-from-settings
python3 agent.py
```

On Windows PowerShell:

```
$env:MS_SERVER_URL="http://your-server:8456"
$env:MS_TOKEN="your-token-from-settings"
python agent.py
```

You can follow the same steps for a database, a laptop or a VM. The agent is the same tiny file everywhere.

### Step 4. See your machines

Back in the web UI you will see your real machines on the dashboard as they report. Click any machine to see its diagnosis, live metrics, disks, event history and a remove button.

---

## Configure it for a real environment

All configuration is done with environment variables on the server. Open `.env.example` and copy it to `.env`. The defaults are fine for a small team.

| Variable | Default | Meaning |
|---|---|---|
| `SERVER_PORT` | `8456` | web and API port |
| `RETENTION_DAYS` | `7` | how many days of data to keep |
| `OFFLINE_AFTER_SECONDS` | `900` | mark a client offline after this silence |
| `TOKEN` | auto | shared agent token, shown in Settings |

For production, put a reverse proxy in front of the server to add HTTPS. The demo uses plain HTTP on purpose, for a trusted network. FastMetric stores everything in a single SQLite file inside the data folder, no external database needed.

---

## What the agent reports

- CPU percent
- Memory percent
- Per disk: mount, total, used, percent
- Uptime in seconds
- Hostname, detected IP, kind (pc, vm or container)

---

## Diagnostics

Every report is checked against rules. When a machine changes state, an event is recorded and, if configured, an alert is sent once. Alerts fire only on state transitions, never on every report.

| Metric | Warning | Critical |
|---|---|---|
| Disk | 90% or more | 98% or more |
| CPU | 90% or more | not set |
| Memory | 90% or more | not set |

Thresholds live in `server/diagnostics.py` and are easy to tune.

---

## Web UI

- Dashboard: all clients, status dots, search and filter chips, CPU and memory bars, grouped by project
- Client detail: diagnosis with evidence, metrics, disks, event history, remove button
- Log: full event history, searchable and filterable by level
- Settings: alert sound, optional SMTP email, webhooks, agent token, report interval

---

## Project layout

```
agent/      the agent, pure Python standard library
server/     FastAPI server, SQLite storage, diagnostics
web/        single page UI, no build step
docs/       screenshots and extra docs
docker-compose.yml   demo with server plus 3 simulated agents
```

---

## Extend it

- New checks: add rules in `server/diagnostics.py`
- More metrics: extend the payload in `agent/agent.py`
- New notification targets: add a transport in `server/notify.py`

---

## Notes

- HTTP is plain in the default setup, for use inside a trusted network. Add TLS with a reverse proxy when exposing it further.
- Data is stored in a SQLite file. No external database needed.

## License

MIT
