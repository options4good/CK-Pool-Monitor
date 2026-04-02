import os
import re
import json
import time
import subprocess
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

# --- CONFIGURATION ---
VERSION = "V1.2.7"
LOG_PATH = "/home/crypto/8epool/src/logs/ckpool.log"
CLI_PATH = "/home/crypto/digibyte-8.26.2/bin/digibyte-cli"

console = Console()

# --- STATE MANAGEMENT ---
state = {
    "difficulty": "0",
    "block_hash": "Unknown",
    "reward": "0",
    "runtime_str": "00:00:00:00",
    "total_users": 0,
    "total_workers": 0,
    "hash_1m": "0", "hash_5m": "0", "hash_1h": "0", "hash_1d": "0",
    "accepted_shares": 0,
    "rejected_shares": 0,
    "sps_1m": 0, "sps_5m": 0, "sps_15m": 0, "sps_1h": 0,
    "current_effort": "0",
    "blocks_solved_total": 0,
    "last_block_time": "Never",
    "solved_height": "N/A",
    "winner_worker": "N/A",
    "solved_effort": "0",
    "solved_share_diff": "0",
    "last_updated_time": "Never"
}

active_workers = []

# --- HELPER FUNCTIONS ---

def format_runtime(seconds):
    try:
        seconds = int(seconds)
        days = seconds // (24 * 3600)
        seconds %= (24 * 3600)
        hours = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60
        return f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}"
    except:
        return "00:00:00:00"

def format_value(n):
    try:
        n = float(n)
        if n >= 1_000_000_000_000: return f"{n / 1_000_000_000_000:.2f} Th/s"
        if n >= 1_000_000_000: return f"{n / 1_000_000_000:.2f} Gh/s"
        if n >= 1_000_000: return f"{n / 1_000_000:.2f} Mh/s"
        if n >= 1_000: return f"{n / 1_000:.2f} Kh/s"
        return f"{n:.2f}"
    except: return "0"

def format_hashrate_str(s):
    if not s: return "0"
    s = str(s).replace("T", " Th/s").replace("G", " Gh/s").replace("M", " Mh/s").replace("K", " Kh/s")
    return s

def format_username(u):
    if not u or u == "None": return "NA"
    u = u.strip()
    if len(u) <= 31: return u
    return f"{u[:20]}...{u[-6:]}"

def get_cli_reward():
    try:
        result = subprocess.run([CLI_PATH, "getblockreward"], capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return str(data.get("blockreward", "0"))
    except: pass
    return "0"

# --- LOG PARSING ENGINE ---

def parse_line(line):
    global active_workers
    updated = False
    line = line.strip()

    ts_match = re.search(r'\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})', line)
    log_ts = ts_match.group(1) if ts_match else ""

    # 1. Network Difficulty and Hash Detection (RESTORED)
    if "Network difficulty changed:" in line or "Network diff set to" in line:
        val = line.split("changed: ")[1].strip() if "changed:" in line else line.split("set to ")[1].strip()
        state["difficulty"] = format_value(val)
        updated = True

    if "Block hash changed to" in line:
        state["block_hash"] = line.split("to ")[1].strip()
        updated = True

    # 2. Pool JSON Data
    if "Pool:{" in line:
        try:
            json_str = "{" + line.split("Pool:{")[1]
            data = json.loads(json_str)
            if "reward" in data: state["reward"] = str(data["reward"])
            if "runtime" in data: 
                state["runtime_str"] = format_runtime(data["runtime"])
                state["total_users"] = data.get("Users", 0)
                state["total_workers"] = data.get("Workers", 0)
            if "hashrate1m" in data:
                state["hash_1m"] = format_hashrate_str(data["hashrate1m"])
                state["hash_5m"] = format_hashrate_str(data["hashrate5m"])
                state["hash_1h"] = format_hashrate_str(data["hashrate1hr"])
                state["hash_1d"] = format_hashrate_str(data["hashrate1d"])
            if "accepted" in data:
                state["accepted_shares"] = data["accepted"]
                state["rejected_shares"] = data["rejected"]
                state["sps_1m"] = data.get("SPS1m", 0)
                state["sps_5m"] = data.get("SPS5m", 0)
                state["sps_15m"] = data.get("SPS15m", 0)
                state["sps_1h"] = data.get("SPS1h", 0)
                state["current_effort"] = data.get("diff", "0")
            updated = True
        except: pass

    # 3. Worker Authorization
    if "Authori" in line and "ed client" in line:
        ip_match = re.search(r'client \d+ ([\d\.]+)', line)
        worker_match = re.search(r'worker\s+\S+\.([a-zA-Z0-9_-]+)', line)
        user_match = re.search(r'as user\s+(\S+)', line)
        ip_val = ip_match.group(1) if ip_match else "NA"
        work_val = worker_match.group(1) if worker_match else "NA"
        user_val = user_match.group(1) if user_match else "NA"
        entry = f"{work_val} / {ip_val} / {format_username(user_val)}"
        active_workers = [w for w in active_workers if not w.startswith(work_val + " /")]
        active_workers.insert(0, entry)
        if len(active_workers) > 25: active_workers.pop()
        updated = True

    # 4. Block Solved Events
    if "BLOCK ACCEPTED!" in line:
        state["blocks_solved_total"] += 1
        state["last_block_time"] = log_ts
        updated = True

    if "Solved and confirmed block" in line:
        parts = line.split("confirmed block ")[1].split(" by ")
        state["solved_height"] = parts[0].strip()
        raw_worker = parts[1].strip()
        state["winner_worker"] = raw_worker.split('.')[-1] if '.' in raw_worker else raw_worker
        updated = True

    if "Block solved after" in line:
        effort_match = re.search(r'at ([\d.]+)% diff', line)
        if effort_match: state["solved_effort"] = effort_match.group(1)
        updated = True

    if "Submitting possible block solve share diff" in line:
        diff_val = line.split("share diff ")[1].split(" !")[0].strip()
        state["solved_share_diff"] = format_value(diff_val)
        updated = True

    if updated:
        state["last_updated_time"] = time.strftime('%H:%M:%S')
    return updated

# --- UI RENDERING ---

def generate_table():
    table = Table(show_header=False, border_style="grey23", expand=True, padding=(0,1))
    table.add_column("Label", style="cyan", width=25)
    table.add_column("Value", style="white")

    # 1. NETWORK
    table.add_row("[bold underline]NETWORK[/bold underline]", "")
    table.add_row("Difficulty", f"[yellow]{state['difficulty']}[/yellow]")
    table.add_row("Block Hash", f"[green]{state['block_hash']}[/green]")
    table.add_row("Current Reward", f"[bold gold1]{state['reward']}[/bold gold1]")
    table.add_section()

    # 2. SESSION
    table.add_row("[bold underline]SESSION[/bold underline]", "")
    table.add_row("Runtime", f"{state['runtime_str']} | Users: {state['total_users']} | Workers: {state['total_workers']}")
    table.add_section()

    # 3. USER
    table.add_row("[bold underline]USER[/bold underline]", "")
    if not active_workers:
        table.add_row("Worker / IP / Username", "[dim]No active workers found in log[/dim]")
    else:
        table.add_row("Worker / IP / Username", f"[bold yellow]1. {active_workers[0]}[/bold yellow]")
        for i, w in enumerate(active_workers[1:], 2):
            table.add_row("", f"[bold yellow]{i}. {w}[/bold yellow]")
    table.add_section()

    # 4. HASHRATE
    table.add_row("[bold underline]HASHRATE[/bold underline]", "")
    table.add_row("Performance", f"1m: [bold green]{state['hash_1m']}[/bold green] | 5m: [bold green]{state['hash_5m']}[/bold green] | 1h: [bold green]{state['hash_1h']}[/bold green] | 1d: [bold green]{state['hash_1d']}[/bold green]")
    table.add_section()

    # 5. SHARES
    table.add_row("[bold underline]SHARES[/bold underline]", "")
    table.add_row("Status", f"Accepted: [green]{state['accepted_shares']}[/green] | Rejected: [red]{state['rejected_shares']}[/red]")
    table.add_row("SPS", f"1m: {state['sps_1m']} | 5m: {state['sps_5m']} | 15m: {state['sps_15m']} | 1h: {state['sps_1h']}")
    table.add_row("Effort", f"Current Effort: [magenta]{state['current_effort']}%[/magenta]")
    table.add_section()

    # 6. BLOCKS
    table.add_row("[bold underline]BLOCKS[/bold underline]", "")
    table.add_row("Accepted", f"[bold green]{state['blocks_solved_total']}[/bold green]")
    table.add_row("Last Block Found", f"{state['last_block_time']}")
    table.add_row("Block Height", f"[bold cyan]{state['solved_height']}[/bold cyan]")
    table.add_row("Winner Worker", f"[bold yellow]{state['winner_worker']}[/bold yellow]")
    table.add_row("Solved Effort", f"{state['solved_effort']}%")
    table.add_row("Solved Share Difficulty", f"{state['solved_share_diff']}")

    header_text = f"CK Pool Monitor | {VERSION} | {time.strftime('%Y-%m-%d %H:%M:%S')}"
    footer_text = f"Last Updated: {state['last_updated_time']} | Press Ctrl+C to Exit"
    return Panel(table, title=f"[bold green]{header_text}[/bold green]", subtitle=f"[bold white]{footer_text}[/bold white]", border_style="green")

# --- MAIN EXECUTION ---

def main():
    if not os.path.exists(LOG_PATH):
        console.print(f"[bold red]Error: Log file not found at {LOG_PATH}[/bold red]")
        return

    with open(LOG_PATH, "r") as f:
        for line in f:
            parse_line(line)

    if state["reward"] == "0":
        state["reward"] = get_cli_reward()

    with open(LOG_PATH, "r") as f:
        f.seek(0, 2)
        with Live(generate_table(), refresh_per_second=2, screen=True) as live:
            while True:
                line = f.readline()
                if line:
                    if parse_line(line):
                        live.update(generate_table())
                else:
                    live.update(generate_table())
                    time.sleep(0.5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt: pass
