"""Update the watch face gallery list (faces/faces.json).

Put your watch face .bin files in the faces/ folder, then run:

    python tools/add_face_v1.py

For every .bin file in faces/ this script
  - adds it to faces/faces.json when it is not listed yet,
  - makes a preview picture (faces/<name>.png) when there is none,
  - fills in the file size and the screen size read from the file.
Names and notes you wrote in faces.json are kept.  Use --rebuild to make all
preview pictures again.

Needs Pillow (pip install pillow) and wf_bin.py (in the same folder).
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FACES = os.path.join(ROOT, "faces")
MANIFEST = os.path.join(FACES, "faces.json")
sys.path.insert(0, HERE)

import wf_bin  # noqa: E402


def pretty_name(file_name):
    stem = os.path.splitext(file_name)[0]
    return stem.replace("_", " ").replace("-", " ").strip().title()


def load_manifest():
    try:
        with open(MANIFEST, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("faces", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        return []


def make_preview(data, out_path):
    """Render the face at a sample time (10:10:30) and save it as a PNG."""
    image = wf_bin.render_full(data, datetime.datetime(2026, 1, 1, 10, 10, 30))
    image.convert("RGB").save(out_path)


def main():
    rebuild = "--rebuild" in sys.argv
    os.makedirs(FACES, exist_ok=True)
    old = {item.get("file"): item for item in load_manifest()}
    faces = []
    for file_name in sorted(os.listdir(FACES)):
        if not file_name.lower().endswith(".bin"):
            continue
        path = os.path.join(FACES, file_name)
        with open(path, "rb") as handle:
            data = handle.read()
        item = dict(old.get("faces/" + file_name, {}))
        item["file"] = "faces/" + file_name
        item.setdefault("name", pretty_name(file_name))
        item.setdefault("note", "")
        item["kb"] = round(len(data) / 1024.0, 1)
        try:
            first = wf_bin.parse_bin(data)[0]
            item["screen"] = "%dx%d" % (first["w"], first["h"])
        except Exception as exc:  # noqa: BLE001
            item["screen"] = "?"
            print("Warning: could not read %s (%s)" % (file_name, exc))
        preview_name = os.path.splitext(file_name)[0] + ".png"
        preview_path = os.path.join(FACES, preview_name)
        if rebuild or not os.path.isfile(preview_path):
            try:
                make_preview(data, preview_path)
            except Exception as exc:  # noqa: BLE001
                print("Warning: no preview for %s (%s)" % (file_name, exc))
        if os.path.isfile(preview_path):
            item["preview"] = "faces/" + preview_name
        faces.append(item)
    # keep the order of the list the user already has, new faces go last
    order = {key: n for n, key in enumerate(old)}
    faces.sort(key=lambda it: order.get(it["file"], len(order)))
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump({"faces": faces}, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    print("%d face(s) listed in %s" % (len(faces), MANIFEST))


if __name__ == "__main__":
    main()
