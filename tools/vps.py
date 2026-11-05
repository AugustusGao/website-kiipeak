"""Local deploy helper. Credentials are read from the untracked AGENTS.md."""
import pathlib, re, sys, warnings
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
warnings.filterwarnings("ignore")
import paramiko
ROOT=pathlib.Path(__file__).resolve().parents[1]
def connect():
    vals=dict(re.findall(r"^(ip|ssh|pwd):(.*)$",(ROOT/"AGENTS.md").read_text(),re.M))
    client=paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(vals["ip"].strip(),username=vals["ssh"].strip(),password=vals["pwd"].strip(),timeout=20,look_for_keys=False,allow_agent=False)
    return client
if __name__=="__main__":
    c=connect()
    command=sys.stdin.read() if len(sys.argv)==1 else pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    _,o,e=c.exec_command(command,timeout=180)
    print(o.read().decode("utf-8",errors="replace"))
    print(e.read().decode("utf-8",errors="replace"),file=sys.stderr)
    code=o.channel.recv_exit_status()
    c.close()
    sys.exit(code)
