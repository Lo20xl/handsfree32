#!/usr/bin/env bash
# Relaunch Comet with CDP :9333 + clear-buffer mode after the user exits it from the tray.
# Waits for a full exit, snapshots nothing further (already backed up), relaunches, verifies port.
set -u
PS=/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
COMET_EXE='C:\Users\tangy\AppData\Local\Perplexity\Comet\Application\comet.exe'

echo "== waiting for comet to fully exit (up to 120s) =="
for i in $(seq 1 40); do
  n=$("$PS" -NoProfile -Command "(Get-Process comet -ErrorAction SilentlyContinue | Measure-Object).Count")
  n=$(echo "$n" | tr -d '[:space:]')
  if [ "$n" = "0" ]; then echo "comet fully exited after ~$((i*3))s"; break; fi
  sleep 3
done
if [ "${n:-1}" != "0" ]; then echo "STILL RUNNING ($n procs) — aborting; user may not have exited yet"; exit 1; fi

echo "== relaunch with CDP + restore session =="
"$PS" -NoProfile -Command "Start-Process -FilePath '$COMET_EXE' -ArgumentList '--remote-debugging-port=9333','--remote-allow-origins=*','--restore-last-session','--no-first-run'"

echo "== wait for the debug port =="
for i in $(seq 1 30); do
  code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9333/json/version)
  if [ "$code" = "200" ]; then echo "CDP LIVE after ~$((i*2))s"; break; fi
  sleep 2
done
curl -s -m 4 -w "\nHTTP=%{http_code}\n" http://127.0.0.1:9333/json/version
echo "== tabs now open =="
curl -s -m 5 http://127.0.0.1:9333/json/list | "$PS" -NoProfile -Command "\$j = [Console]::In.ReadToEnd() | ConvertFrom-Json; \$j | Where-Object { \$_.type -eq 'page' } | ForEach-Object { Write-Output \$_.url }" | head -30
