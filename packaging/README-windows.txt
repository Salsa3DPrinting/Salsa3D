Salsa Duct Adapter Generator
============================

Makes 3D-printable duct adapters between a fan and a pipe fitting (PVC Sch 40 spigot/socket,
NPT male/female, tri-clamp ferrule). Everything runs on your PC; no internet or account needed.

Start
-----
1. Double-click SalsaAdapter.exe. The first start takes 10-20 seconds while it unpacks.
2. Windows may show "Windows protected your PC" because the program isn't signed:
   click "More info", then "Run anyway". Some antivirus tools also flag unsigned programs
   built this way; ask IT to allow it if it gets blocked.
3. A black console window opens and your browser opens the app. Leave the console open while
   you work; closing it stops the app. If the browser doesn't open, go to the address printed
   in the console (normally http://127.0.0.1:8765/).

Make an adapter
---------------
Pick the fan, pick the fitting type and size (or type it, e.g. "4in sch40 pvc spigot",
"2\" fnpt", "1.5 tri-clamp"), and click Generate. Download the 3MF for Bambu Studio.
PRINT THE FIT-TEST PIECE FIRST and try it on the real fitting; adjust the fit under Advanced.

Notes
-----
- PLA softens around 55-60 C. Use PETG or ASA for warm air, sun or a hot vehicle.
- Printed NPT threads are for low-pressure air with tape or sealant, not for pressure.
- Fans are added on the Fans tab. Mark a fan "verified" only after checking it against the
  drawing or the real fan.
- To share fans with colleagues, set the fan library file (Settings tab) to a file on a shared
  drive, e.g. \\server\share\Adapters\fans.json. Everyone points at the same file.
- Your settings, library and generated files are in %APPDATA%\SalsaAdapter unless you change it.
