#!/usr/bin/env python3
"""Generate a terminal-style demo video of the Vergabepilot.AI 100-URL run.
Recreates the real run output (see deck slide 14 + run JSON) as an mp4."""
import os, random, subprocess, shutil
from PIL import Image, ImageDraw, ImageFont

random.seed(20260512)
OUT = "demo_frames"
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)

W, H = 1280, 720
FPS = 24
BG = (13, 17, 23)          # terminal background
BAR = (32, 38, 48)         # title bar
PANEL = (22, 27, 34)
FG = (201, 209, 217)
DIM = (110, 122, 138)
GREEN = (63, 185, 80)
AMBER = (210, 153, 34)
CYAN = (86, 182, 220)
VIOLET = (165, 130, 240)
BLUE = (88, 166, 255)
WHITE = (240, 246, 252)

MONO = "/System/Library/Fonts/SFNSMono.ttf"
f   = ImageFont.truetype(MONO, 18)
fb  = ImageFont.truetype(MONO, 18)
fbig= ImageFont.truetype(MONO, 20)
fsm = ImageFont.truetype(MONO, 15)

# ---- realistic run data (platforms weighted as in real run JSON) ----
PLATFORMS = (
    [("NetServer", "ausschreibungen.ls.brandenburg.de/NetServer/PublicationCon")]*35 +
    [("DTVP", "www.dtvp.de/Satellite/notice")]*21 +
    [("Unknown(PDF)", "www.vergabe.rlp.de/VMPCenter/notice.pdf")]*7 +
    [("aumass", "www.aumass.de/vergabe/bekanntmachung")]*4 +
    [("meinauftrag.rib", "www.meinauftrag.rib.de/public/tender")]*3 +
    [("eVergabe4.9/Cosinex", "www.evergabe.nrw.de/VMPSatellite/notice")]*3 +
    [("TYPO3", "vergabe.muenchen.de/typo3/bekanntmachung")]*3 +
    [("subreport", "www.subreport.de/ELViS/tender")]*2 +
    [("vergabe24", "www.vergabe24.de/bekanntmachungen")]*2 +
    [("bi-medien", "www.bi-medien.de/ausschreibung")]*2 +
    [("Staatsanzeiger", "www.staatsanzeiger-eservices.de/notice")]*1 +
    [("evergabe-online", "www.evergabe-online.de/tenderdetails")]*1 +
    [("had.de", "www.had.de/onlinesuche")]*1 +
    [("SharePoint", "vergabe.example.de/sites/tender")]*1 +
    [("Ariba", "service.ariba.com/Discovery")]*1 +
    [("acingov.pt", "www.acingov.pt/acingovprod/notice")]*1 +
    [("it-vergabe.eu", "www.it-vergabe.eu/notice")]*1 +
    [("Drupal", "vergabeportal.example.de/node")]*1 +
    [("Verwaltungsportal", "verwaltungsportal.de/ausschreibung")]*1
)
random.shuffle(PLATFORMS)
PLATFORMS = PLATFORMS[:100]
# 3 no_documents, rest success
no_doc_idx = set(random.sample(range(100), 3))

entries = []
for i, (plat, url) in enumerate(PLATFORMS):
    if i in no_doc_idx:
        entries.append(("no_documents", 0, plat, url))
    else:
        entries.append(("success", random.choice([1,1,1,2,2,3,4,5,8]), plat, url))

def status_color(s): return GREEN if s == "success" else AMBER
def status_word(s):  return "OK success " if s == "success" else "·· no_docs  "

def line_for(i, e):
    st, docs, plat, url = e
    return (f"[{i+1:>3}/100]", status_word(st), status_color(st),
            f"docs={docs}", f"platform={plat}", url)

def draw_window(d, title):
    d.rectangle([0,0,W,H], fill=BG)
    d.rectangle([0,0,W,38], fill=BAR)
    for k,c in enumerate([(255,95,86),(255,189,46),(39,201,63)]):
        d.ellipse([18+k*22,13,30+k*22,25], fill=c)
    d.text((W//2-90,10), title, font=fsm, fill=DIM)

HEADER = [
    ("$ python -m vergabepilot run --input urls_100.csv --workers 4", BLUE),
    ("", FG),
    ("Loaded 100 URLs", FG),
    ("Processing 100 URLs with 4 workers ...", FG),
    ("Output: results/run_20260512_115859.jsonl", DIM),
    ("", FG),
]

LINE_H = 22
TOP = 54
MAX_ROWS = (H - TOP - 16) // LINE_H

frames = []
def save(img):
    n = len(frames)
    img.save(f"{OUT}/f{n:04d}.png"); frames.append(n)

def render(log_rows, cursor=True, title=" vergabepilot — run "):
    img = Image.new("RGB",(W,H),BG); d = ImageDraw.Draw(img)
    draw_window(d, title)
    rows = log_rows[-MAX_ROWS:]
    y = TOP
    for row in rows:
        if isinstance(row, tuple) and len(row)==6:
            idx, sw, sc, docs, plat, url = row
            x = 16
            d.text((x,y), idx, font=f, fill=CYAN); x += f.getlength(idx)+10
            d.text((x,y), sw, font=fb, fill=sc); x += fb.getlength(sw)+8
            d.text((x,y), docs, font=f, fill=FG); x += f.getlength(docs)+14
            d.text((x,y), plat, font=f, fill=VIOLET); x += f.getlength(plat)+14
            # truncate url to fit
            maxx = W-16
            u = url
            while f.getlength(u) > maxx-x and len(u)>4:
                u = u[:-2]
            if u != url: u = u[:-1]+"…"
            d.text((x,y), u, font=f, fill=DIM)
        else:
            text, col = row
            d.text((16,y), text, font=f, fill=col)
        y += LINE_H
    if cursor:
        d.rectangle([16, y+2, 26, y+18], fill=GREEN)
    save(img)

# 1) intro: header appears
log = []
for h in HEADER:
    log.append(h)
    render(log)
for _ in range(int(FPS*0.6)): render(log)   # hold

# 2) stream the 100 results (reveal ~ every 2 frames, scroll)
for i,e in enumerate(entries):
    log.append(line_for(i,e))
    render(log)
    if i < 12 or i % 20 == 0:
        render(log)   # slight pause early / periodically

for _ in range(int(FPS*0.4)): render(log)

# 3) summary block
summary = [
    ("", FG),
    ("──────────────────────────  RUN SUMMARY  ──────────────────────────", DIM),
    ("  total            100", FG),
    ("  success           97        success_rate   97.0%", GREEN),
    ("  no_documents       3", AMBER),
    ("  elapsed          348.4 s    (4 parallel workers)", FG),
    ("  llm_new_calls      4        llm_cached    75", CYAN),
    ("  cost             $0.02      (caching enabled)", WHITE),
    ("  platforms         30+       auto-classified", VIOLET),
    ("", FG),
    ("✓ done — 97/100 tenders scraped, documents saved to MinIO (S3)", GREEN),
]
# clear to a fresh screen for the summary
base = list(HEADER[:1])
for s in summary:
    base.append(s)
    render(base, title=" vergabepilot — summary ")
for _ in range(int(FPS*3.0)):    # hold summary ~3s
    render(base, cursor=(len(frames)//12)%2==0, title=" vergabepilot — summary ")

print(f"frames: {len(frames)}  (~{len(frames)/FPS:.1f}s)")

# ---- encode mp4 ----
mp4 = "demo_vergabepilot.mp4"
subprocess.run([
    "ffmpeg","-y","-loglevel","error","-framerate",str(FPS),
    "-i",f"{OUT}/f%04d.png",
    "-vf","scale=1280:720:flags=lanczos,format=yuv420p",
    "-c:v","libx264","-preset","slow","-crf","20","-movflags","+faststart",
    mp4
], check=True)
# also a gif (smaller, universally embeddable) at reduced size
subprocess.run([
    "ffmpeg","-y","-loglevel","error","-framerate",str(FPS),
    "-i",f"{OUT}/f%04d.png",
    "-vf","fps=16,scale=900:-1:flags=lanczos",
    "demo_vergabepilot.gif"
], check=True)
print("wrote", mp4, "and demo_vergabepilot.gif")
