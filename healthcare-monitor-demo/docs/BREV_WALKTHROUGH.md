# Brev Setup

This guide assumes a Linux/Brev host with Docker available.

## 1. Connect

```bash
brev login
brev shell <your-instance-name>
```

## 2. Configure Environment

```bash
cd ~/healthcare-monitor-demo
cp -n .env.example .env
chmod 600 .env
vi .env
```

Use `HOST=0.0.0.0` if the web app will be opened through a remote browser or port-forwarded URL.

## 3. Verify NVIDIA Build Endpoint

```bash
./scripts/probe-build-endpoint.sh
```

Expected result:

```text
Endpoint probe succeeded.
Model response: READY
```

## 4. Build The Sandbox

```bash
./scripts/brev-runtime-setup.sh
```

This can take several minutes because the custom sandbox image is built and uploaded into the OpenShell gateway.

## 5. Run Readiness Checks

```bash
./scripts/live-demo-ready.sh
```

## 6. Open The App

Use the forwarded URL for port `5188`, or from the host:

```text
http://127.0.0.1:5188
```

If the app is not reachable from the browser, restart it on all interfaces:

```bash
fuser -k 5188/tcp || true
HOST=0.0.0.0 PORT=5188 ./scripts/start-demo-app.sh
```

## 7. Confirm Runtime

```bash
curl -fsS http://127.0.0.1:5188/api/config
curl -fsS http://127.0.0.1:5188/api/topology
```
