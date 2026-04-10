"""
Fake-cluster client — mirrors access_cluster_and_launch_jobs.py
but connects to the local fake SSH server on localhost:2222.

Start the server first:
    python fake_cluster_server.py

Then run this script:
    python access_cluster_fake.py
"""
import paramiko

HEADNODE = "127.0.0.1"
PORT     = 2222
USERNAME = "user"
PASSWORD = "fake_pass"

user = USERNAME


def _make_client() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(hostname=HEADNODE, port=PORT, username=USERNAME, password=PASSWORD)
    return c


def run_remote(cmd: str) -> tuple[str, str]:
    """Open a fresh connection, run one command, close, return (stdout, stderr)."""
    c = _make_client()
    try:
        stdin, stdout, stderr = c.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
    finally:
        c.close()
    return out, err


def launch_interactive_job() -> tuple[str, str]:
    return run_remote("srun --gres gpu:8 --time=08:00:00 --pty /bin/bash -i")


if __name__ == "__main__":
    # ── Basic cluster info ───────────────────────────────────────────────
    print("=== Cluster hostname & partition overview ===")
    out, err = run_remote("hostname && sinfo | head")
    print(out)

    # ── What compute is this user allowed to use? ────────────────────────
    print("=== User compute allocation (sacctmgr) ===")
    out, err = run_remote(f"sacctmgr show associations user={user}")
    print(out)

    # ── Which nodes are currently idle? ─────────────────────────────────
    print("=== Idle nodes (sinfo | grep idle) ===")
    out, err = run_remote("sinfo | grep idle")
    print(out)

    # ── Account utilisation report ───────────────────────────────────────
    print("=== Account utilisation (sreport) ===")
    out, err = run_remote(f"sreport cluster AccountUtilizationByUser account={user}")
    print(out)

    # ── Launch a fake training job via srun ──────────────────────────────
    print("=== Launching fake training job (srun) ===")
    out, err = run_remote(
        "srun --gres gpu:4 --time=01:00:00 fake_train.py --epochs 5 --model resnet50"
    )
    print(out)
    if err:
        print("STDERR:", err)
