# Watch Face Uploader

A web page that sends watch face `.bin` files to a WEARFIT / Chronos watch over
Bluetooth. Pick a face from the gallery, or choose your own `.bin` file.

Open the page in **Bluefy** on iPhone (or **Chrome** on Android). Disconnect the
watch from the Chronos app first.

## Put it on GitHub Pages

1. Create a new repository on GitHub (public).
2. Upload everything in this folder to the repository root:
   `index.html`, `faces/`, `tools/`, `README.md`.
3. Open **Settings > Pages**. Under **Build and deployment** choose
   **Deploy from a branch**, branch `main`, folder `/ (root)`, then **Save**.
4. After a minute the page is live at
   `https://<your-user>.github.io/<repository>/`. Bluetooth needs this https
   address; opening `index.html` from a local file does not work.

## Add a face to the gallery

1. Copy the `.bin` file into the `faces/` folder.
2. On your PC run: `python tools/add_face_v1.py`
   (needs `pip install pillow`). It adds the face to `faces/faces.json`, makes
   its preview picture and reads its size.
3. Open `faces/faces.json` if you want to change the `name` or the `note` of a
   face. The script keeps what you wrote.
4. Commit and push the changes to GitHub.

Use `python tools/add_face_v1.py --rebuild` to make all preview pictures again.

## Notes

- The watch screen is 240x240. The page warns when a face has another size.
- A 569 KB face was rejected by the watch before, while faces up to about 470 KB
  worked. The page warns above 500 KB.
- After an upload wait about 15 seconds. The page then reconnects to the same
  watch without asking. If that fails, press the button once more and pick the
  watch from the list, or use **Advanced > Choose a different watch**.
- The upload protocol is the Chronos one (Nordic UART, 1024-byte blocks,
  CRC16/MODBUS), decoded from a real upload.
