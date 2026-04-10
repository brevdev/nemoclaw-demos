#!/usr/bin/env python3
"""
Fake SSH server simulating a Slurm HPC headnode.
Listens on localhost:2222. No root/Docker required.

Usage:
    python fake_cluster_server.py
"""
import re
import socket
import threading
import time
import random
from pathlib import Path

import paramiko

HOST_KEY_PATH = Path(__file__).parent / "fake_host_key"
USERNAME = "user"
PASSWORD = "fake_pass"


# ---------------------------------------------------------------------------
# Host key
# ---------------------------------------------------------------------------

def get_host_key() -> paramiko.RSAKey:
    if not HOST_KEY_PATH.exists():
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(str(HOST_KEY_PATH))
        print(f"[server] Generated host key → {HOST_KEY_PATH}")
    return paramiko.RSAKey(filename=str(HOST_KEY_PATH))


# ---------------------------------------------------------------------------
# Fake Slurm command handlers
# Each handler receives the full command string and the open channel,
# writes output directly, and returns an exit code.
# ---------------------------------------------------------------------------

def cmd_hostname(cmd: str, channel: paramiko.Channel) -> int:
    channel.sendall(b"dlcluster-headnode\n")
    return 0


def cmd_sinfo(cmd: str, channel: paramiko.Channel) -> int:
    output = (
        "PARTITION    AVAIL  TIMELIMIT   NODES  STATE  NODELIST\n"
        "gpu-a100*    up     infinite        4  idle   node[01-04]\n"
        "gpu-h100     up     2-00:00:00      8  idle   node[05-12]\n"
        "gpu-gb200    up     4-00:00:00      2  idle   node[13-14]\n"
        "cpu-general  up     infinite       16  idle   node[15-30]\n"
    )
    channel.sendall(output.encode())
    return 0


def cmd_srun(cmd: str, channel: paramiko.Channel) -> int:
    gpus_match = re.search(r"gpu:(\d+)", cmd)
    gpus = int(gpus_match.group(1)) if gpus_match else 1

    channel.sendall(
        b"srun: job 42001 queued and waiting for resources\n"
        b"srun: job 42001 has been allocated resources\n"
    )
    channel.sendall(f"Allocated {gpus} GPU(s) on node01\n\n".encode())

    random.seed(42)
    epochs = 5
    loss, acc = 3.2, 0.05
    for epoch in range(1, epochs + 1):
        loss -= random.uniform(0.2, 0.5)
        acc  += random.uniform(0.05, 0.12)
        line = (
            f"Epoch [{epoch}/{epochs}]  loss={loss:.4f}  "
            f"acc={min(acc, 1.0):.4f}  lr=1e-4  gpu_util=94%\n"
        )
        channel.sendall(line.encode())
        time.sleep(0.4)          # simulate per-epoch time

    channel.sendall(
        b"\nTraining complete. Checkpoints saved to "
        b"/checkpoint/user/run_42001/\n"
    )
    return 0


def cmd_sbatch(cmd: str, channel: paramiko.Channel) -> int:
    job_id = 42001
    Path("/tmp/fake_cluster_jobs.txt").write_text(
        f"{job_id} RUNNING user gpu-a100 0:01 fake_train\n"
    )
    channel.sendall(f"Submitted batch job {job_id}\n".encode())
    return 0


def cmd_squeue(cmd: str, channel: paramiko.Channel) -> int:
    header = (
        "             JOBID PARTITION     NAME     USER  ST       TIME  "
        "NODES NODELIST\n"
    )
    channel.sendall(header.encode())
    job_file = Path("/tmp/fake_cluster_jobs.txt")
    if job_file.exists():
        for line in job_file.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 6:
                jid, state, user, part, elapsed, name = (
                    parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
                )
                row = (
                    f"             {jid:>5}  {part:<10} {name:<8} "
                    f"{user:<8}  R  {elapsed:<9}     1 node01\n"
                )
                channel.sendall(row.encode())
    return 0


def cmd_sacctmgr(cmd: str, channel: paramiko.Channel) -> int:
    output = (
        "   Cluster    Account       User  Partition  Share  MaxJobs  MaxTRES        QOS\n"
        "---------- ---------- --------- ---------- ------  ------- --------  ---------\n"
        "dlcluster        root                            1                      normal\n"
        "dlcluster        root      root                  1                      normal\n"
        "dlcluster     user                            1                      normal\n"
        "dlcluster     user   user                  1      200             normal\n"
    )
    channel.sendall(output.encode())
    return 0


def cmd_sreport(cmd: str, channel: paramiko.Channel) -> int:
    output = (
        "-----------------------------------------------------------\n"
        "Cluster/Account/User Utilization 2024-01-01 - 2024-01-31\n"
        "Usage reported in CPU Minutes\n"
        "-----------------------------------------------------------\n"
        "   Cluster         Account     Login       Used\n"
        "--------- --------------- --------- ----------\n"
        "dlcluster            root                12,400\n"
        "dlcluster         user   user    298,102\n"
    )
    channel.sendall(output.encode())
    return 0


# Map command prefixes → handlers
HANDLERS = {
    "hostname":  cmd_hostname,
    "sinfo":     cmd_sinfo,
    "srun":      cmd_srun,
    "sbatch":    cmd_sbatch,
    "squeue":    cmd_squeue,
    "sacctmgr":  cmd_sacctmgr,
    "sreport":   cmd_sreport,
}


def dispatch(cmd: str, channel: paramiko.Channel) -> int:
    """Route a command string to the right fake handler."""
    token = cmd.strip().split()[0] if cmd.strip() else ""
    handler = HANDLERS.get(token)
    if handler:
        return handler(cmd, channel)
    # Unknown command
    channel.sendall_stderr(
        f"bash: {token}: command not found\n".encode()
    )
    return 127


# ---------------------------------------------------------------------------
# Paramiko ServerInterface
# ---------------------------------------------------------------------------

class FakeClusterServer(paramiko.ServerInterface):

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        if username == USERNAME and password == PASSWORD:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        # Accept any key for the fake username — no real key verification
        if username == USERNAME:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_channel_exec_request(self, channel, command):
        cmd = command.decode()
        print(f"[server] exec → {cmd!r}")

        def _run():
            exit_code = dispatch(cmd, channel)
            channel.send_exit_status(exit_code)
            channel.close()

        threading.Thread(target=_run, daemon=True).start()
        return True

    def check_channel_pty_request(self, channel, term, width, height,
                                   pixelwidth, pixelheight, modes):
        return True

    def check_channel_shell_request(self, channel):
        def _shell():
            channel.sendall(b"[user@dlcluster-headnode ~]$ ")
            time.sleep(0.1)
            channel.sendall(b"exit\r\n")
            channel.send_exit_status(0)
            channel.close()
        threading.Thread(target=_shell, daemon=True).start()
        return True


# ---------------------------------------------------------------------------
# Per-connection handler (runs in its own thread)
# ---------------------------------------------------------------------------

def handle_connection(conn: socket.socket, addr, host_key: paramiko.RSAKey):
    transport = paramiko.Transport(conn)
    transport.add_server_key(host_key)
    try:
        transport.start_server(server=FakeClusterServer())
        # Accept channels in a loop so the transport stays alive for the
        # duration of the TCP connection (each exec_command opens one channel).
        while transport.is_active():
            chan = transport.accept(timeout=2)
            # chan is handled inside check_channel_exec_request via a thread;
            # we just need to keep pumping accept() so paramiko keeps going.
    except Exception as exc:
        print(f"[server] Connection error from {addr}: {exc}")
    finally:
        transport.close()


# ---------------------------------------------------------------------------
# Main server loop
# ---------------------------------------------------------------------------

def run_server(host: str = "127.0.0.1", port: int = 2222):
    host_key = get_host_key()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(10)
    print(f"[server] Fake Slurm headnode ready on {host}:{port}")
    print(f"[server] Credentials → username={USERNAME!r}  password={PASSWORD!r}")
    print("[server] Ctrl-C to stop\n")

    try:
        while True:
            conn, addr = sock.accept()
            print(f"[server] New connection from {addr}")
            t = threading.Thread(
                target=handle_connection, args=(conn, addr, host_key), daemon=True
            )
            t.start()
    except KeyboardInterrupt:
        print("\n[server] Shutting down.")
    finally:
        sock.close()


if __name__ == "__main__":
    run_server()
