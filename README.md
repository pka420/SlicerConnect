# SlicerConnect: Real-Time Collaborative Segmentation

SlicerConnect is a 3D Slicer extension designed to enable "Google Docs-style" collaboration for medical image segmentation. It allows multiple researchers or clinicians to work on the same segmentation simultaneously, synchronizing edits in real-time across different locations.

## Extension Structure

The extension consists of three specialized modules that manage the lifecycle of a collaborative session:

### Login

- Handles secure user authentication.
- Exchanges credentials for a session token from the central server.
- Ensures encrypted communication for all subsequent steps.

### CollaborativeSegmentation

The Project Hub of the extension.

- Implements Role-Based Access Control (RBAC) to manage user permissions.
- Displays available projects and active collaborators.
- Handles the initial download/sync of the volume data.

### SlicerConnectEditor

The Real-Time Engine.

- Hooks directly into Slicer's Segment Editor.
- Broadcasts local voxel changes (deltas) and applies incoming edits from remote users.
- Optimized with zlib compression and debounced updates for smooth performance.

## Installation & Setup

### Prerequisites

- 3D Slicer (Stable or Preview).
- Python Dependencies: `numpy`, `websockets`, and `requests` (installed via Slicer's Python console if not present).
- Backend Server: A running SlicerConnect WebSocket/API server.

### Installation

Clone this repository to your local machine:

```
git clone https://github.com/your-repo/SlicerConnect.git
```

1. Open 3D Slicer.
2. Navigate to **Edit -> Application Settings -> Modules**.
3. Click **Add** and select the root `SlicerConnect` folder.
4. Restart Slicer to initialize the modules.

## Testing on a Single Computer

You can test the full collaborative experience on a single Linux machine by launching two isolated Slicer instances.

### 1. Launch Instance A (User 1)

Open a terminal and run:

```bash
mkdir /tmp/slicer_bob/
./Slicer -HOME=/tmp/slicer_bob -settings-disabled --additional-module-paths /path/to/SlicerConnect/
```

Go to **Login**, sign in as `User_A`. In **CollaborativeSegmentation**, select a project and enter **Edit Mode**.

### 2. Launch Instance B (User 2)

Open a second terminal and run the same command:

```bash
mkdir /tmp/slicer_alice
./Slicer HOME=/tmp/slicer_alice --settings-disabled --additional-module-paths /path/to/SlicerConnect/
```

Log in as `User_B` and join the same project.

### 3. Verify Synchronization

- Place the two Slicer windows side-by-side.
- Pick a tool (e.g., **Paint**) in Instance A and draw on a slice.
- The segmentation should appear in Instance B after a brief transmission delay.

> **Note:** Using the `--settings-disabled` flag is essential for local testing. It prevents both instances from trying to write to the same `.ini` file simultaneously, which causes crashes.

## Architecture Highlights

- **Voxel Delta Sync:** Instead of sending full volumes, SlicerConnect only transmits changed voxels to save bandwidth.
- **Stateful Recovery:** The server maintains the "Source of Truth," allowing new users to join an ongoing session and receive the current state immediately.
- **Event Guarding:** Prevents "Echo Loops" by distinguishing between local user edits and incoming remote updates.

---

# Collaborative Segmentation Sync Protocol

## 1. Data Pipeline Overview

The system uses a Master-Client or Peer-to-Peer model where segmentation changes are synchronized via two types of messages:

- **Full Sync:** Sends the entire labelmap (used for initialization or large changes).
- **Delta Sync:** Sends only the modified voxels (used for real-time brush strokes).

### Coordinate Systems

To ensure "Placement" is preserved, we map data across three spaces:

- **Numpy Space:** `(Z, Y, X)` indexed array.
- **IJK Space:** `(X, Y, Z)` voxel indices in Slicer.
- **RAS Space:** `(Right, Anterior, Superior)` physical millimeters in the 3D world.

## 2. Sending Segmentations

### Full Segmentation Transfer

When a full sync is triggered, the module exports the `vtkMRMLSegmentationNode` to a temporary `vtkMRMLLabelMapVolumeNode`.

**Process:**

1. **Export:** Convert the segmentation to a labelmap to flatten all segments into a single 3D array.
2. **Metadata Extraction:** Capture the Origin, Spacing, and IJKToRAS Direction Matrix.
3. **Compression:** Convert the volume to a Numpy array. Compress using zlib and encode to base64 for JSON transport.

**Payload Structure:**

```json
{
  "type": "full_segmentation",
  "data": {
    "array": "base64_string",
    "origin": [x, y, z],
    "spacing": [sx, sy, sz],
    "direction": [m00, m01, "...", m33],
    "dimensions": [w, h, d]
  }
}
```

### Delta Updates

Deltas are sent during active interaction (e.g., `python checkBrushStrokes`).

**Process:**

1. **Identify Changes:** Capture only the indices $(i, j, k)$ and the new values $v$ that changed since the last update.
2. **Encoding:** Use `numpy.frombuffer` to convert indices to a byte stream.
3. **Payload:** Contains the specific sparse coordinates and the same geometry metadata to ensure the "canvas" matches on both ends.

## 3. Applying Segmentations (Receiver Side)

The receiver must reconstruct the physical "placement" before painting the pixels.

### Step A: Geometry Alignment

The `_getOrCreateMasterLabelmap` function ensures a "Proxy Volume" exists with the correct orientation:

- Sets `node.SetOrigin()` and `node.SetSpacing()`.
- Applies the 4x4 Direction Matrix via `SetIJKToRASMatrix()`. This ensures that even if the image is tilted (oblique), the pixels land in the correct anatomical location.

### Step B: The Data Bridge (Numpy to VTK)

To avoid UI lag and "Invalid Labelmap" errors, we bypass standard Slicer utilities and talk directly to VTK memory:

- **Memory Allocation:** Create a `vtkOrientedImageData` object.
- **Extent Definition:** Use `SetExtent(0, X-1, 0, Y-1, 0, Z-1)` to define the voxel grid boundaries.
- **Direct Copy:** Use `vtk.util.numpy_support.numpy_to_vtk` to pour the received Numpy array into the VTK scalar pointer.

### Step C: Segment Injection

Rather than re-importing the whole volume (which is slow), we update specific segments:

1. Extract a Binary Mask for each `labelValue` (e.g., `array == 1`).
2. Assign the `orientedMask` (with its geometry) to the specific `vtkSegment`.
3. Trigger `OnSegmentModified()` to refresh the Slicer 3D and 2D views.

## 4. Key Logic Components

| Component | Responsibility |
|---|---|
| `SlicerConnectLogic` | Manages WebSocket state and triggers cleanup to prevent "ghost" connections. |
| `_getOrCreateMasterLabelmap` | Maintains a persistent MRML node to store incoming pixel data across reloads. |
| `_applyArrayToSegmentation` | The core engine that converts Numpy arrays into physical VTK segments. |
| `vtkOrientedImageData` | The internal Slicer data structure that stores the Direction Matrix alongside the pixels. |
