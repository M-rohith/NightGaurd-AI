# NightGuard AI

NightGuard AI is a local person-tracking and restricted-zone demo. The Next.js frontend accepts a recorded video and a user-drawn polygon. FastAPI runs YOLO person detection with ByteTrack, detects outside-to-inside transitions using each track's bottom-centre point, and returns synchronized boxes, track IDs, incidents, and evidence snapshots.

## Run the classroom demo

Requirements: Windows, Node.js, Python, and the existing Ultralytics/PyTorch environment used to train the model. CUDA is optional but strongly recommended.

```powershell
npm install
npm run setup:backend
npm run demo
```

Open `http://localhost:3000`, then sign in with:

- Email: `admin@nightguard.local`
- Password: `nightguard-demo`

Open **Live Demo**, upload a short video, click at least three points around the restricted area, and select **Analyze video**. When processing finishes, play the video to see synchronized person boxes and track IDs. Clicking a detected entry jumps to the relevant moment.

## Trained model location

The backend uses the first trained model it finds:

1. `NIGHTGUARD_MODEL_PATH` from the environment
2. `runs/detect/train-3/weights/best.pt`
3. `weights/best.pt`
4. `best.pt`

This repository snapshot does not currently contain `best.pt` even though the original Python scripts reference `runs/detect/train-3/weights/best.pt`. Copy the team's trained weight file to that location before the presentation. Until then, the demo clearly labels and uses the pretrained `yolo26n.pt` person-detector fallback; Ultralytics downloads it on first use if it is not already local.

## Useful commands

```powershell
npm run dev           # frontend only
npm run backend       # FastAPI only
npm run demo          # both processes
npm run lint
npm run build
npm run test:backend
```

API documentation is available at `http://127.0.0.1:8000/docs` while the backend is running. Generated uploads, snapshots, incident state, and other demo runtime files stay under `runtime/` and are ignored by Git.

## Demo architecture

1. The browser keeps a local object URL for reliable playback and sends the video plus normalized polygon points to FastAPI.
2. YOLO detects people and ByteTrack assigns temporary track IDs.
3. The backend tests each person's bottom-centre point against the polygon and records an incident on an outside-to-inside transition.
4. Frame annotations return as JSON and the browser overlays them at the matching video timestamp.
5. Incidents and snapshots feed the existing dashboard and incident-review screens through the shared API contract.

The prototype identifies temporary tracks, not real-world identities or faces. It reports observable zone entries and does not claim criminal intent.
