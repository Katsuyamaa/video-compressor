# Video Trim UI — Design Spec
**Date:** 2026-05-31

## Overview

Replace the manual start_time/end_time text inputs with a visual trim UI: an HTML5 video preview player, a canvas-based thumbnail strip, and a dual-handle drag slider for selecting trim points. All logic is client-side JavaScript — no changes to the Flask backend (app.py Python code).

## Requirements

- File selected → video previews immediately in browser (no upload)
- Thumbnail strip: ~20 evenly-spaced frames drawn onto a `<canvas>` element
- Dual-handle trim overlay: left handle (start) and right handle (end) draggable on the thumbnail canvas
- While dragging: video scrubs to that time (`video.currentTime`) AND time info updates live
- Info bar: "Başlangıç: M:SS | Bitiş: M:SS | Seçili: M:SS"
- Form submit: hidden `start_time` and `end_time` inputs populated as `HH:MM:SS` strings
- Backend unchanged — receives same start_time/end_time strings as before
- No external JS libraries

## Architecture

Only `HTML_TEMPLATE` in `app.py` changes. Python/Flask code untouched.

```
File input (change event)
  → URL.createObjectURL() → <video src>
  → video.loadedmetadata → generate_thumbnails()
      → seek to N points → video.seeked → ctx.drawImage() × N
      → draw_handles() on canvas overlay
  → user drags handle
      → mousemove → update handle pos → video.currentTime → redraw overlay
      → update info bar text
      → update hidden inputs (start_time, end_time)
  → form submit
      → hidden inputs already filled → /process receives HH:MM:SS strings
```

## Components

### 1. Video Player

```html
<video id="preview" controls style="display:none; width:100%; border-radius:6px; margin-top:8px;"></video>
```

Shown only after file is selected. `controls` attribute allows manual playback.

### 2. Thumbnail Canvas + Handle Overlay

A single `<canvas id="trimCanvas">` element rendered below the video. Width: 100% of form container (~560px). Height: 60px.

**Thumbnail generation:**
- On `video.loadedmetadata`: divide `video.duration` into N=20 equal intervals
- For each interval: set `video.currentTime`, listen for `seeked`, draw frame with `ctx.drawImage(video, x, 0, frameWidth, 60)`
- Frames drawn left-to-right; `frameWidth = canvasWidth / N`

**Handle overlay (drawn on same canvas after thumbnails):**
- Left handle: filled circle + vertical line at `startX`
- Right handle: filled circle + vertical line at `endX`
- Selected region: semi-transparent blue fill between startX and endX
- Unselected regions: semi-transparent dark overlay

### 3. Drag Logic

Track state: `dragging = null | 'left' | 'right'`

```
canvas mousedown:
  if click near left handle → dragging = 'left'
  if click near right handle → dragging = 'right'

canvas mousemove (if dragging):
  clamp x to [0, canvasWidth]
  if 'left': startX = min(x, endX - minGap)
  if 'right': endX = max(x, startX + minGap)
  video.currentTime = (x / canvasWidth) * video.duration
  redraw_overlay()
  update_info_bar()
  update_hidden_inputs()

canvas mouseup / mouseleave:
  dragging = null
```

`minGap` = 10px (prevents handles from overlapping).

### 4. Info Bar

```html
<div id="trimInfo">Başlangıç: 0:00 | Bitiş: 0:00 | Seçili: 0:00</div>
```

Updated on every mousemove during drag and on thumbnail generation complete.

### 5. Hidden Inputs

```html
<input type="hidden" id="start_time" name="start_time" value="">
<input type="hidden" id="end_time" name="end_time" value="">
```

Replaces the existing visible text inputs. Populated as `HH:MM:SS` by `update_hidden_inputs()`.

```js
function secs_to_hhmmss(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}
```

If start handle is at position 0: send empty string (backend = "from beginning").
If end handle is at full duration: send empty string (backend = "to end").

## CSS Additions

```css
#trimCanvas { width: 100%; height: 60px; border-radius: 6px; cursor: col-resize; display: none; }
#trimInfo { font-size: 0.8rem; color: #4b5563; margin-top: 6px; display: none; }
```

## Initialization Flow

```
file input change
  → revoke previous objectURL if exists
  → video.src = URL.createObjectURL(file)
  → video.load()
  → on loadedmetadata:
      show video element
      show trimCanvas, trimInfo
      startX = 0, endX = canvasWidth
      update_hidden_inputs() → both empty (full video)
      generate_thumbnails() → draws frames sequentially
      draw_handles()
```

## Constraints

- Thumbnail generation is sequential (one seek at a time) to avoid race conditions
- Canvas redraws thumbnails + overlay on each handle move (not expensive at 60px height)
- No touch events (personal desktop tool)
- `video.currentTime` scrub during drag may lag on large files — acceptable for personal use

## What Does NOT Change

- `app.py` Python code (all routes, functions, validation)
- The hidden `start_time` and `end_time` form fields still submit as `HH:MM:SS` to `/process`
- All other form fields (resolution, audio, compression) unchanged
